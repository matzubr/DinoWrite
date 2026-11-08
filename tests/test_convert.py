"""Conversion job: color transform selection, parallel OCIO, encoder fallback, cancel and cleanup"""
import shutil
import subprocess
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
    """Instead of running tools: hoiiotool 'writes' PNGs for its frame range, ffmpeg 'writes' the video.
    exit_code(cmd) decides success."""
    launched = []
    exit_code = staticmethod(lambda cmd: 0)

    def __init__(self, cmds, label):
        self.cmds, self.label = cmds, label
        FakeProcesses.launched.append(self)

    def poll(self):
        codes = [FakeProcesses.exit_code(cmd) for cmd in self.cmds]
        for cmd, code in zip(self.cmds, codes):
            if code == 0 and "--ociodisplay" in " ".join(cmd):
                first, last = map(int, cmd[cmd.index("--frames") + 1].split("-"))
                pattern = cmd[-1]
                for frame in range(first, last + 1):
                    open(pattern.replace("#", f"{frame:04d}"), "w").close()
            elif code == 0:
                open(cmd[-1], "w").close()
        failed = [c for c in codes if c]
        return process.Result(returncode=failed[0] if failed else 0)

    def cancel(self):
        return process.Result(cancelled=True)


def _codec(cmd):
    return cmd[cmd.index("-c:v") + 1] if "-c:v" in cmd else None


@pytest.fixture
def tools(monkeypatch):
    FakeProcesses.launched = []
    FakeProcesses.exit_code = staticmethod(lambda cmd: 0)
    monkeypatch.setattr(conversion.process, "Processes", FakeProcesses)
    monkeypatch.setattr(conversion.ffmpeg, "findFFmpeg", lambda custom="": "hffmpeg")
    monkeypatch.setattr(conversion.ffmpeg, "availableEncoders", lambda binary: {"h264_mf", "mpeg4"})
    monkeypatch.setattr(conversion.ocio, "findOiiotool", lambda custom="": "hoiiotool")
    monkeypatch.setattr(conversion.ocio, "displayView", lambda viewer, display="", view="", source="mplay": ("sRGB", "ACES SDR"))
    monkeypatch.setattr(conversion.ocio, "configPath", lambda: "config.ocio")
    return FakeProcesses


def _job(settings, sequence, display_referred=False):
    """display_referred=False: beauty pass flipbook (linear EXR), the OCIO path"""
    return conversion.ConversionJob(settings, None, sequence, "$F4", (1001, 1010), (1920, 1080), 1.0, "mov",
                                    display_referred=display_referred)


def _run(job):
    for _ in range(50):
        if job.step():
            return job
    raise AssertionError("job didn't finish")


def test_ocio_runs_in_parallel_parts_then_encodes_pngs(settings, sequence, tools):
    settings["advanced"]["ocio_processes"] = 3
    job = _run(_job(settings, sequence))

    assert job.succeeded and job.video == sequence.parent / "shot.v001.mov"
    ocio_run, encode_run = tools.launched
    ranges = [cmd[cmd.index("--frames") + 1] for cmd in ocio_run.cmds]
    assert ranges == ["1001-1004", "1005-1007", "1008-1010"]
    encode = encode_run.cmds[0]
    assert encode[encode.index("-i") + 1].endswith("_ocio_tmp/shot.v001.%04d.png")
    assert "lutrgb" not in " ".join(encode), "PNGs are display-encoded already"
    assert "color_trc=iec61966-2-1" in " ".join(encode), "sRGB display -> sRGB transfer tag"
    assert "comment=DinoWrite: OCIO sRGB / ACES SDR" in encode
    assert not job.temp_folder.exists(), "temp PNGs removed"


def test_ocio_failure_falls_back_to_srgb(settings, sequence, tools):
    tools.exit_code = staticmethod(lambda cmd: 1 if cmd[0] == "hoiiotool" else 0)
    job = _run(_job(settings, sequence))
    encode = tools.launched[-1].cmds[0]
    assert job.succeeded
    assert encode[encode.index("-i") + 1].endswith("v001/shot.v001.%04d.exr")
    assert "lutrgb" in " ".join(encode)


def test_encoder_fallback_until_one_works(settings, sequence, tools):
    """hffmpeg: libx264 missing, h264_mf compiled in but fails on this machine -> mpeg4"""
    settings["advanced"]["color_transform"] = "srgb"
    tools.exit_code = staticmethod(lambda cmd: 0 if _codec(cmd) == "mpeg4" else 1)
    job = _run(_job(settings, sequence))
    assert job.succeeded
    assert [_codec(run.cmds[0]) for run in tools.launched] == ["h264_mf", "mpeg4"]


def test_all_encoders_fail(settings, sequence, tools):
    settings["advanced"]["color_transform"] = "srgb"
    settings["advanced"]["conversion_delete_input_sequence"] = True
    tools.exit_code = staticmethod(lambda cmd: 1)
    job = _run(_job(settings, sequence))
    assert job.stage == conversion.FAILED
    assert len(list(sequence.parent.glob("*.exr"))) == 10, "sequence is kept"
    assert not job.video.exists()


def test_success_deletes_only_sequence_frames(settings, sequence, tools):
    settings["advanced"]["color_transform"] = "srgb"
    settings["advanced"]["conversion_delete_input_sequence"] = True
    _run(_job(settings, sequence))
    assert sorted(f.name for f in sequence.parent.iterdir()) == ["notes.txt", "shot.v001.mov"]


def test_cancel_during_ocio_keeps_sequence_and_skips_encode(settings, sequence, tools):
    settings["advanced"]["conversion_delete_input_sequence"] = True
    job = _job(settings, sequence)
    job.start()
    assert job.stage == conversion.OCIO
    job.cancel()
    assert job.stage == conversion.CANCELLED and job.finished
    assert len(tools.launched) == 1, "no ffmpeg after cancel"
    assert len(list(sequence.parent.glob("*.exr"))) == 10
    assert not job.temp_folder.exists()


def test_status_and_progress(settings, sequence, tools):
    job = _job(settings, sequence)
    job.start()
    assert job.status.startswith("OCIO ACES SDR: 0/10 frames · ")  # process count depends on CPU cores
    job.step()
    assert job.stage == conversion.ENCODE and job.status.startswith("Encoding h264_mf")
    job.step()
    assert job.status == "Done: shot.v001.mov" and job.progress == 1.0


def test_no_ffmpeg_fails_without_running_anything(settings, sequence, tools, monkeypatch):
    monkeypatch.setattr(conversion.ffmpeg, "findFFmpeg", lambda custom="": "")
    monkeypatch.setattr(conversion.ffmpeg, "hmsg", lambda *a, **k: None)
    job = _run(_job(settings, sequence))
    assert job.stage == conversion.FAILED and tools.launched == []


def test_convert_blocking_returns_video_path(settings, sequence, tools):
    settings["advanced"]["color_transform"] = "srgb"
    viewer = SimpleNamespace(getPaneTab=lambda: None, isDisplayReferred=lambda: False)
    video = flipbook.convert(settings, viewer, sequence, "$F4", (1001, 1010), (1920, 1080), 1.0, "mov")
    assert video == sequence.parent / "shot.v001.mov"


def test_open_result(monkeypatch, tmp_path):
    opened = []
    monkeypatch.setattr(flipbook.wb, "open", opened.append)
    video = tmp_path / "v001" / "shot.v001.mov"
    video.parent.mkdir()
    video.touch()

    flipbook.openResult("video", video, video.parent, tmp_path)
    flipbook.openResult("folder", video, video.parent, tmp_path)
    flipbook.openResult("video", None, video.parent, tmp_path)
    flipbook.openResult("video", None, tmp_path / "deleted", tmp_path)
    assert opened == [video.as_uri(), video.parent.as_uri(), video.parent.as_uri(), tmp_path.as_uri()]



VIEWPORT = SimpleNamespace(getPaneTab=lambda: None, isDisplayReferred=lambda: False)


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
    settings["advanced"]["color_transform"] = "srgb"
    settings["advanced"]["conversion_delete_input_sequence"] = False
    sequence = folder / "grey.v001.$F4.exr"
    assert flipbook.convert(settings, VIEWPORT, sequence, "$F4", (1001, 1002), (64, 32), 1.0, "mov")

    pixel = subprocess.run(["ffmpeg", "-nostdin", "-v", "error", "-i", (folder / "grey.v001.mov").as_posix(),
                            "-frames:v", "1", "-vf",
                            "scale=in_color_matrix=bt709:in_range=tv,format=rgb24,crop=1:1:32:16",
                            "-f", "rawvideo", "-"], check=True, capture_output=True, stdin=subprocess.DEVNULL,
                           timeout=60).stdout
    assert all(abs(channel - 118) <= 2 for channel in pixel)
    tags = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format_tags=comment", "-of", "default=nw=1",
                           (folder / "grey.v001.mov").as_posix()], capture_output=True, text=True,
                          stdin=subprocess.DEVNULL, timeout=60).stdout
    assert "DinoWrite: srgb transfer" in tags


def test_auto_viewport_flipbook_is_encoded_as_recorded(settings, sequence, tools):
    """Without beauty pass the EXR already has the viewer's display transform: no OCIO/LUT again"""
    assert settings["advanced"]["color_transform"] == "auto"
    job = _run(_job(settings, sequence, display_referred=True))
    assert job.succeeded
    assert len(tools.launched) == 1, "no hoiiotool"
    encode = " ".join(tools.launched[0].cmds[0])
    assert "lutrgb" not in encode
    assert "shot.v001.%04d.exr" in encode


def test_auto_beauty_pass_flipbook_uses_ocio(settings, sequence, tools):
    job = _job(settings, sequence, display_referred=False)
    assert job.color_transform == "ocio" and job.ocio_commands


@pytest.mark.skipif(not shutil.which("ffmpeg"), reason="needs ffmpeg in PATH")
def test_real_ffmpeg_display_referred_values_pass_through(settings, tmp_path, hou, monkeypatch):
    """Viewport flipbook EXR holds display values: 0.4627 must stay 118/255 in the video (no transfer)"""
    monkeypatch.setattr(hou, "fps", lambda: 24.0, raising=False)
    monkeypatch.setattr(hou, "getenv", lambda name, default=None: default)
    folder = tmp_path / "v001"
    folder.mkdir()
    for frame in (1, 2):
        subprocess.run(["ffmpeg", "-nostdin", "-v", "error", "-y", "-f", "lavfi", "-i", "color=c=black:s=64x32",
                        "-frames:v", "1", "-vf",
                        "format=rgb48le,lutrgb=r=0.4627*maxval:g=0.4627*maxval:b=0.4627*maxval,format=gbrpf32le",
                        "-c:v", "exr", "-compression", "0", (folder / f"vp.v001.{frame:04d}.exr").as_posix()],
                       check=True, stdin=subprocess.DEVNULL, timeout=60)
    settings["advanced"]["conversion_delete_input_sequence"] = False
    viewer = SimpleNamespace(getPaneTab=lambda: None, isDisplayReferred=lambda: True)
    assert flipbook.convert(settings, viewer, folder / "vp.v001.$F4.exr", "$F4", (1, 2), (64, 32), 1.0, "mov")
    pixel = subprocess.run(["ffmpeg", "-nostdin", "-v", "error", "-i", (folder / "vp.v001.mov").as_posix(),
                            "-frames:v", "1", "-vf",
                            "scale=in_color_matrix=bt709:in_range=tv,format=rgb24,crop=1:1:32:16",
                            "-f", "rawvideo", "-"], check=True, capture_output=True, stdin=subprocess.DEVNULL,
                           timeout=60).stdout
    assert all(abs(channel - 118) <= 2 for channel in pixel), list(pixel)
