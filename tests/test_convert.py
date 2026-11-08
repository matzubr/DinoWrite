"""flipbook.convert(): color transform selection, fallbacks and cleanup"""
import shutil
import subprocess
from types import SimpleNamespace

import pytest

from DinoWrite import config, flipbook


@pytest.fixture
def settings(monkeypatch, tmp_path):
    monkeypatch.setenv(config.USER_SETTINGS_ENV, (tmp_path / "user.json").as_posix())
    return config.load()


@pytest.fixture
def sequence(tmp_path, hou, monkeypatch):
    monkeypatch.setattr(hou, "fps", lambda: 24.0, raising=False)
    folder = tmp_path / "v001"
    folder.mkdir()
    for frame in (1001, 1002, 1003):
        (folder / f"shot.v001.{frame}.exr").write_bytes(b"exr")
    (folder / "notes.txt").write_text("keep me")
    return folder / "shot.v001.$F4.exr"


class FakeFFmpeg:
    calls = []

    def __init__(self, cmd, binary="", codec="auto"):
        self.available = True

    def convert_to_video(self, **kwargs):
        FakeFFmpeg.calls.append(kwargs)
        return True


@pytest.fixture
def fake_ffmpeg(monkeypatch):
    FakeFFmpeg.calls = []
    monkeypatch.setattr(flipbook.ffmpeg, "FFmpeg", FakeFFmpeg)
    return FakeFFmpeg


VIEWPORT = SimpleNamespace(getPaneTab=lambda: None)


def _convert(settings, sequence):
    return flipbook.convert(settings, VIEWPORT, sequence, "$F4", (1001, 1003), (1920, 1080), 1.0, "mov")


def test_ocio_success_encodes_display_pngs_without_extra_transfer(settings, sequence, fake_ffmpeg, monkeypatch):
    seen = {}

    def fake_transform(advanced, viewport, seq, display_sequence, *args):
        seen["display_sequence"] = display_sequence
        display_sequence.parent.mkdir(parents=True)
        return True

    monkeypatch.setattr(flipbook, "ocioTransform", fake_transform)
    assert _convert(settings, sequence)

    call = fake_ffmpeg.calls[0]
    assert call["input"].endswith("_ocio_tmp/shot.v001.%04d.png")
    assert call["exr_transfer"] == ""
    assert call["output"].endswith("v001/shot.v001.mov")
    assert not seen["display_sequence"].parent.exists(), "temp PNG folder must be removed"


def test_ocio_failure_falls_back_to_srgb(settings, sequence, fake_ffmpeg, monkeypatch):
    monkeypatch.setattr(flipbook, "ocioTransform", lambda *args: False)
    assert _convert(settings, sequence)
    call = fake_ffmpeg.calls[0]
    assert call["input"].endswith("v001/shot.v001.%04d.exr")
    assert call["exr_transfer"] == "srgb"


def test_delete_input_removes_only_sequence_frames(settings, sequence, fake_ffmpeg):
    settings["advanced"]["color_transform"] = "srgb"
    settings["advanced"]["conversion_delete_input_sequence"] = True
    assert _convert(settings, sequence)
    assert sorted(f.name for f in sequence.parent.iterdir()) == ["notes.txt"]


def test_failed_conversion_keeps_sequence(settings, sequence, monkeypatch):
    class FailingFFmpeg(FakeFFmpeg):
        def convert_to_video(self, **kwargs):
            return False

    monkeypatch.setattr(flipbook.ffmpeg, "FFmpeg", FailingFFmpeg)
    settings["advanced"]["color_transform"] = "srgb"
    settings["advanced"]["conversion_delete_input_sequence"] = True
    assert not _convert(settings, sequence)
    assert len(list(sequence.parent.glob("*.exr"))) == 3


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


def test_cancel_during_ocio_keeps_sequence_and_skips_encode(settings, sequence, fake_ffmpeg, monkeypatch):
    from DinoWrite.core.process import Result

    settings["advanced"]["conversion_delete_input_sequence"] = True
    monkeypatch.setattr(flipbook, "ocioTransform", lambda *args: Result(cancelled=True))
    assert not _convert(settings, sequence)
    assert fake_ffmpeg.calls == []
    assert len(list(sequence.parent.glob("*.exr"))) == 3
    assert not (sequence.parent / "_ocio_tmp").exists()


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


def test_convert_returns_video_path(settings, sequence, fake_ffmpeg):
    settings["advanced"]["color_transform"] = "srgb"
    video = _convert(settings, sequence)
    assert video == sequence.parent / "shot.v001.mov"
