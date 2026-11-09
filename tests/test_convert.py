"""Conversion job: sRGB for EXR, encoder fallback, cancel and cleanup"""
import shutil
import subprocess
import time
from pathlib import Path
from types import SimpleNamespace

import pytest

from DinoWrite import config, flipbook
from DinoWrite.core import conversion, process


@pytest.fixture
def settings(monkeypatch, tmp_path):
    monkeypatch.setenv(config.USER_SETTINGS_ENV, (tmp_path / "user.json").as_posix())
    return config.load()


@pytest.fixture
def sequence(tmp_path, hou, monkeypatch):
    monkeypatch.setattr(hou, "fps", lambda: 24.0, raising=False)
    folder = tmp_path / "v001"
    folder.mkdir()
    for frame in range(1001, 1011):
        (folder / f"shot.v001.{frame}.exr").write_bytes(b"exr")
    (folder / "notes.txt").write_text("keep me")
    return folder / "shot.v001.$F4.exr"


class FakeProcesses:
    """Instead of running ffmpeg: 'writes' the video. exit_code(cmd) decides success."""
    launched = []
    exit_code = staticmethod(lambda cmd: 0)

    def __init__(self, cmd, label):
        self.cmds, self.label = [cmd], label
        FakeProcesses.launched.append(self)

    def poll(self):
        codes = [FakeProcesses.exit_code(cmd) for cmd in self.cmds]
        for cmd, code in zip(self.cmds, codes):
            if code == 0 and "--frames" in cmd:  # hoiiotool: one file per frame of its range
                first, last = map(int, cmd[cmd.index("--frames") + 1].split("-"))
                for frame in range(first, last + 1):
                    Path(cmd[-1].replace("#", f"{frame:04d}")).write_text("acescg")
            elif code == 0:
                open(cmd[-1], "w").close()
        failed = [c for c in codes if c]
        return process.Result(returncode=failed[0] if failed else 0)

    def cancel(self):
        return process.Result(cancelled=True)


@pytest.fixture
def ocio_viewer(monkeypatch, hou):
    """Viewer with ACES SDR on Rec.1886, ACES config, hoiiotool 2.5"""
    from DinoWrite.core import acescg
    monkeypatch.setattr(hou, "Color", SimpleNamespace(ocio_spaces=lambda: ("ACEScg", "Linear Rec.709 (sRGB)"),
                                                      ocio_configPath=lambda: "config.ocio"), raising=False)
    monkeypatch.setattr(acescg, "findOiiotool", lambda custom="": "hoiiotool")
    monkeypatch.setattr(acescg, "bakeTransform", lambda config, display, view, ctf: Path(ctf).write_text("ctf"))
    return SimpleNamespace(usingOCIO=lambda: True, getOCIODisplay=lambda: "Rec.1886 Rec.709 - Display",
                           getOCIOView=lambda: "ACES 1.0 - SDR Video")


def _codec(cmd):
    return cmd[cmd.index("-c:v") + 1] if "-c:v" in cmd else None


@pytest.fixture
def tools(monkeypatch):
    FakeProcesses.launched = []
    FakeProcesses.exit_code = staticmethod(lambda cmd: 0)
    monkeypatch.setattr(conversion.process, "Process", FakeProcesses)
    monkeypatch.setattr(conversion.ffmpeg, "findFFmpeg", lambda custom="": "hffmpeg")
    monkeypatch.setattr(conversion.ffmpeg, "availableEncoders", lambda binary: {"h264_mf", "mpeg4"})
    return FakeProcesses


def _job(settings, sequence):
    return conversion.ConversionJob(settings, sequence, "$F4", (1001, 1010), (1920, 1080), 1.0, "mov")


def _run(job):
    for _ in range(50):
        if job.step():
            return job
    raise AssertionError("job didn't finish")


def test_exr_is_encoded_with_srgb_curve(settings, sequence, tools):
    job = _run(_job(settings, sequence))
    assert job.succeeded and job.video == sequence.parent / "shot.v001.mov"
    encode = tools.launched[-1].cmds[0]
    assert encode[encode.index("-i") + 1].endswith("v001/shot.v001.%04d.exr")
    assert "lutrgb" in " ".join(encode) and "color_trc=iec61966-2-1" in " ".join(encode)


def test_jpg_is_encoded_as_is(settings, sequence, tools):
    job = _run(_job(settings, sequence.with_name("shot.v001.$F4.jpg")))
    encode = tools.launched[-1].cmds[0]
    assert job.succeeded and "lutrgb" not in " ".join(encode)


def test_encoder_fallback_until_one_works(settings, sequence, tools):
    """hffmpeg: libx264 missing, h264_mf compiled in but fails on this machine -> mpeg4"""
    tools.exit_code = staticmethod(lambda cmd: 0 if _codec(cmd) == "mpeg4" else 1)
    job = _run(_job(settings, sequence))
    assert job.succeeded
    assert [_codec(run.cmds[0]) for run in tools.launched] == ["h264_mf", "mpeg4"]


def test_all_encoders_fail(settings, sequence, tools):
    settings["advanced"]["conversion_delete_input_sequence"] = True
    tools.exit_code = staticmethod(lambda cmd: 1)
    job = _run(_job(settings, sequence))
    assert job.stage == conversion.FAILED
    assert len(list(sequence.parent.glob("*.exr"))) == 10, "sequence is kept"
    assert not job.video.exists()


def test_success_deletes_only_sequence_frames(settings, sequence, tools):
    settings["advanced"]["conversion_delete_input_sequence"] = True
    _run(_job(settings, sequence))
    assert sorted(f.name for f in sequence.parent.iterdir()) == ["notes.txt", "shot.v001.mov"]


def test_cancel_keeps_sequence(settings, sequence, tools):
    settings["advanced"]["conversion_delete_input_sequence"] = True
    job = _job(settings, sequence)
    job.start()
    job.cancel()
    assert job.stage == conversion.CANCELLED and job.finished
    assert len(list(sequence.parent.glob("*.exr"))) == 10


def test_status_and_progress(settings, sequence, tools):
    job = _job(settings, sequence)
    assert job.status == "Starting..."
    job.start()
    assert job.stage == conversion.ENCODE and job.status.startswith("Encoding h264_mf")
    job.step()
    assert job.status == "Done: shot.v001.mov" and job.progress == 1.0


def test_no_ffmpeg_fails_without_running_anything(settings, sequence, tools, monkeypatch):
    monkeypatch.setattr(conversion.ffmpeg, "findFFmpeg", lambda custom="": "")
    monkeypatch.setattr(conversion.ffmpeg, "hmsg", lambda *a, **k: None)
    job = _run(_job(settings, sequence))
    assert job.stage == conversion.FAILED and tools.launched == []


def test_open_result(monkeypatch, tmp_path):
    opened = []
    monkeypatch.setattr(flipbook, "openPath", lambda path, select=False: opened.append((path, select)))
    video = tmp_path / "v001" / "shot.v001.mov"
    video.parent.mkdir()
    video.touch()

    flipbook.openResult("video", video, video.parent, tmp_path)
    flipbook.openResult("folder", video, video.parent, tmp_path)
    flipbook.openResult("video", None, video.parent, tmp_path)
    flipbook.openResult("video", None, tmp_path / "deleted", tmp_path)
    # folder: the one above vNNN, with vNNN selected (drag into Nuke)
    assert opened == [(video, False), (video.parent, True), (video.parent, True), (tmp_path, False)]

    opened.clear()
    flipbook.openResult("video_folder", video, video.parent, tmp_path)
    flipbook.openResult("video_folder", None, video.parent, tmp_path)
    assert opened == [(video, True), (video, False), (video.parent, True)]  # folder with the video selected


def test_open_command_selects_sequence_folder():
    folder = Path("C:/preview/shot/v001")
    assert flipbook.openCommand(folder, select=True, platform="win32") == f'explorer /select,"{folder}"'
    assert flipbook.openCommand(folder, platform="win32") == ["explorer", str(folder)]
    assert flipbook.openCommand(folder, select=True, platform="darwin") == ["open", "-R", str(folder)]
    assert flipbook.openCommand(folder, select=True, platform="linux") == ["xdg-open", str(folder.parent)]



def _local_encoders():
    from DinoWrite.core import ffmpeg
    return ffmpeg.availableEncoders(shutil.which("ffmpeg") or "")


@pytest.mark.skipif(not shutil.which("ffmpeg"), reason="needs ffmpeg in PATH")
@pytest.mark.parametrize("codec", ["libx264", "mpeg4", "h264_videotoolbox"])
def test_real_ffmpeg_srgb_encode(settings, tmp_path, hou, monkeypatch, codec):
    """Linear 0.18 grey EXR -> video -> decoded pixel must be sRGB 118/255 (mpeg4 = what Houdini's hffmpeg has)"""
    if codec not in _local_encoders():
        pytest.skip(f"local ffmpeg has no {codec}")
    settings["advanced"]["video_codec"] = codec
    monkeypatch.setattr(hou, "fps", lambda: 24.0, raising=False)
    monkeypatch.setattr(hou, "getenv", lambda name, default=None: default)
    folder = tmp_path / "v001"
    folder.mkdir()
    for frame in (1001, 1002):
        subprocess.run(["ffmpeg", "-nostdin", "-v", "error", "-y", "-f", "lavfi", "-i", "color=c=black:s=64x32",
                        "-frames:v", "1", "-vf",
                        "format=rgb48le,lutrgb=r=0.18*maxval:g=0.18*maxval:b=0.18*maxval,format=gbrpf32le",
                        "-c:v", "exr", "-compression", "0", (folder / f"grey.v001.{frame}.exr").as_posix()],
                       check=True, stdin=subprocess.DEVNULL, timeout=60)
    settings["advanced"]["conversion_delete_input_sequence"] = False
    sequence = folder / "grey.v001.$F4.exr"
    job = conversion.ConversionJob(settings, sequence, "$F4", (1001, 1002), (64, 32), 1.0, "mov")
    while not job.step():
        time.sleep(0.05)
    assert job.succeeded, job.error

    pixel = subprocess.run(["ffmpeg", "-nostdin", "-v", "error", "-i", (folder / "grey.v001.mov").as_posix(),
                            "-frames:v", "1", "-vf",
                            "scale=in_color_matrix=bt709:in_range=tv,format=rgb24,crop=1:1:32:16",
                            "-f", "rawvideo", "-"], check=True, capture_output=True, stdin=subprocess.DEVNULL,
                           timeout=60).stdout
    assert all(abs(channel - 118) <= 2 for channel in pixel)
    tags = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format_tags", "-of", "default=nw=1",
                           (folder / "grey.v001.mov").as_posix()], capture_output=True, text=True,
                          stdin=subprocess.DEVNULL, timeout=60).stdout
    assert "dinowrite_video_color=sRGB" in tags and "dinowrite_frame_range=1001-1002" in tags, "passport kept"



def _acescgJob(settings, sequence, viewer, convert_video):
    return conversion.ConversionJob(settings, sequence, "$F4", (1001, 1010), (1920, 1080), 1.0, "mov",
                                    convert_video=convert_video, scene_viewer=viewer)


def test_exr_converted_to_acescg_in_place_without_video(settings, sequence, tools, ocio_viewer):
    job = _run(_acescgJob(settings, sequence, ocio_viewer, convert_video=False))
    assert job.succeeded and job.video is None and job.title == "shot.v001.####.exr"
    cmd = tools.launched[0].cmds[0]
    assert cmd[cmd.index("--ociofiletransform") + 1].endswith("screen_to_acescg.ctf")
    assert (sequence.parent / "shot.v001.1005.exr").read_text() == "acescg", "originals replaced"
    assert not job.temp_folder.exists()


def test_video_from_recorded_exr_then_acescg(settings, sequence, tools, ocio_viewer):
    settings["advanced"]["conversion_delete_input_sequence"] = False
    job = _run(_acescgJob(settings, sequence, ocio_viewer, convert_video=True))
    assert job.succeeded
    encode, *convert = tools.launched
    assert "lutrgb" in " ".join(encode.cmds[0]), "video is encoded from the recorded EXR"
    assert convert and "hoiiotool" == convert[0].cmds[0][0]
    assert job.video.exists()


def test_no_acescg_when_sequence_is_deleted_after_video(settings, sequence, tools, ocio_viewer):
    settings["advanced"]["conversion_delete_input_sequence"] = True
    job = _run(_acescgJob(settings, sequence, ocio_viewer, convert_video=True))
    assert job.succeeded and len(tools.launched) == 1 and not job.exr_commands


def test_acescg_failure_keeps_recorded_exr_and_video(settings, sequence, tools, ocio_viewer):
    settings["advanced"]["conversion_delete_input_sequence"] = False
    tools.exit_code = staticmethod(lambda cmd: 1 if cmd[0] == "hoiiotool" else 0)
    job = _run(_acescgJob(settings, sequence, ocio_viewer, convert_video=True))
    assert job.stage == conversion.FAILED and "kept as recorded" in job.error
    assert (sequence.parent / "shot.v001.1005.exr").read_bytes() == b"exr"
    assert job.video.exists() and not job.temp_folder.exists()


def _hasColorTransform(job):
    return any("--ociofiletransform" in cmd for cmd in job.exr_commands)


def test_acescg_skipped_without_ocio_or_transform(settings, sequence, tools, ocio_viewer, monkeypatch):
    """Colors stay as recorded, the EXR still get compressed and the passport"""
    from DinoWrite.core import acescg
    no_ocio = SimpleNamespace(usingOCIO=lambda: False)
    job = _acescgJob(settings, sequence, no_ocio, convert_video=False)
    assert job.hasWork and not _hasColorTransform(job) and job.exrLabel() == "EXR -> DWAA"

    def no_pyocio(*args):
        raise ImportError("No module named 'PyOpenColorIO'")
    monkeypatch.setattr(acescg, "bakeTransform", no_pyocio)
    assert not _hasColorTransform(_acescgJob(settings, sequence, ocio_viewer, convert_video=False))
    settings["advanced"]["exr_acescg"] = False
    assert not _hasColorTransform(_acescgJob(settings, sequence, no_ocio, convert_video=False))


def test_exr_pass_compression_and_passport(settings, sequence, tools, ocio_viewer, hou, monkeypatch):
    monkeypatch.setattr(hou, "hipFile", SimpleNamespace(path=lambda: "/shots/sh010/fx.v012.hip"), raising=False)
    job = _acescgJob(settings, sequence, ocio_viewer, convert_video=False)
    cmd = job.exr_commands[0]
    assert cmd[cmd.index("--compression") + 1] == "dwaa:45"
    assert cmd[cmd.index("dinowrite:hip") + 1] == "/shots/sh010/fx.v012.hip"
    assert job.exrLabel() == "EXR -> ACEScg, DWAA"
    settings["advanced"]["exr_compression"] = "zip"
    cmd = _acescgJob(settings, sequence, ocio_viewer, convert_video=False).exr_commands[0]
    assert cmd[cmd.index("--compression") + 1] == "zip"


def test_no_exr_pass_without_oiiotool(settings, sequence, tools, ocio_viewer, monkeypatch):
    from DinoWrite.core import acescg
    monkeypatch.setattr(acescg, "findOiiotool", lambda custom="": "")
    assert not _acescgJob(settings, sequence, ocio_viewer, convert_video=False).hasWork


def test_baked_transform_inverts_the_viewer_display_view(tmp_path):
    """Real OCIO: screen pixels -> baked ctf -> ACEScg -> ACES SDR display gives the screen pixels back"""
    OCIO = pytest.importorskip("PyOpenColorIO")
    from DinoWrite.core import acescg
    config = "ocio://cg-config-v2.1.0_aces-v1.3_ocio-v2.3"
    display, view = "Rec.1886 Rec.709 - Display", "ACES 1.0 - SDR Video"
    ctf = acescg.bakeTransform(config, display, view, tmp_path / "t.ctf")
    cfg = OCIO.Config.CreateFromFile(config)
    linear = [0.0, 0.02, 0.18, 0.5]  # recorded EXR values (linearized screen)
    pixels = [value for value in linear for _ in range(3)]
    # applyRGB returns new values for Python lists
    screen = cfg.getProcessor("lin_rec709_srgb", "srgb_tx").getDefaultCPUProcessor().applyRGB(list(pixels))
    to_acescg = cfg.getProcessor(OCIO.FileTransform(src=str(ctf))).getDefaultCPUProcessor()
    acescg_pixels = to_acescg.applyRGB(list(pixels))
    back = cfg.getProcessor("ACEScg", display, view, OCIO.TRANSFORM_DIR_FORWARD).getDefaultCPUProcessor() \
        .applyRGB(list(acescg_pixels))
    assert all(abs(a - b) < 1 / 255 for a, b in zip(back, screen))
    assert acescg_pixels[6] > pixels[6], "mid grey is lifted back to scene linear (inverse, not forward)"


def test_parse_oiiotool_version():
    from DinoWrite.core import acescg
    assert acescg.parseVersion("oiiotool OpenImageIO 2.5.16.0 http://www.openimageio.org") == (2, 5, 16, 0)
    assert acescg.parseVersion("") == ()


def test_read_colorspace_for_nuke(ocio_viewer):
    from DinoWrite.core import acescg
    assert acescg.readColorspace("exr", ocio_viewer)[0] == "ACEScg"
    assert acescg.readColorspace("exr", ocio_viewer, acescg_on=False)[0] == "Linear Rec.709"
    assert acescg.readColorspace("exr", ocio_viewer, keeps_exr=False)[0] == "temporary"
    name, how = acescg.readColorspace("png", ocio_viewer)
    assert name == "ACES 1.0 - SDR Video" and "Rec.1886 Rec.709 - Display" in how
    no_ocio = SimpleNamespace(usingOCIO=lambda: False)
    assert acescg.readColorspace("jpg", no_ocio)[0] == "sRGB"
    assert acescg.readColorspace("exr", no_ocio)[0] == "Linear Rec.709"
