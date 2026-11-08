"""Conversion job: sRGB for EXR, encoder fallback, cancel and cleanup"""
import shutil
import subprocess
from pathlib import Path

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

    def __init__(self, cmds, label):
        self.cmds, self.label = cmds, label
        FakeProcesses.launched.append(self)

    def poll(self):
        codes = [FakeProcesses.exit_code(cmd) for cmd in self.cmds]
        for cmd, code in zip(self.cmds, codes):
            if code == 0:
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


def test_convert_blocking_returns_video_path(settings, sequence, tools):
    video = flipbook.convert(settings, sequence, "$F4", (1001, 1010), (1920, 1080), 1.0, "mov")
    assert video == sequence.parent / "shot.v001.mov"


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
    assert flipbook.convert(settings, sequence, "$F4", (1001, 1002), (64, 32), 1.0, "mov")

    pixel = subprocess.run(["ffmpeg", "-nostdin", "-v", "error", "-i", (folder / "grey.v001.mov").as_posix(),
                            "-frames:v", "1", "-vf",
                            "scale=in_color_matrix=bt709:in_range=tv,format=rgb24,crop=1:1:32:16",
                            "-f", "rawvideo", "-"], check=True, capture_output=True, stdin=subprocess.DEVNULL,
                           timeout=60).stdout
    assert all(abs(channel - 118) <= 2 for channel in pixel)
    tags = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format_tags=comment", "-of", "default=nw=1",
                           (folder / "grey.v001.mov").as_posix()], capture_output=True, text=True,
                          stdin=subprocess.DEVNULL, timeout=60).stdout
    assert "DinoWrite: sRGB" in tags

