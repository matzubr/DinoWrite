from DinoWrite.core import helpers


def test_next_version_empty_or_missing(tmp_path):
    assert helpers.nextVersion(tmp_path / "missing") == "v001"
    assert helpers.nextVersion(tmp_path) == "v001"


def test_next_version_ignores_non_version_folders_and_sorts_numerically(tmp_path):
    for name in ["v003", "old", "v003_backup", "v999", "v1000"]:
        (tmp_path / name).mkdir()
    (tmp_path / "v2000").touch()  # file, not a folder
    assert helpers.nextVersion(tmp_path) == "v1001"


def test_next_version_keeps_padding(tmp_path):
    (tmp_path / "v0007").mkdir()
    assert helpers.nextVersion(tmp_path) == "v0008"


def test_flipbook_version(tmp_path):
    (tmp_path / "shot" / "v002").mkdir(parents=True)
    template = (tmp_path / "{name}").as_posix()
    assert helpers.flipbookVersion(template, "shot") == "v003"
    assert helpers.flipbookVersion(template, "") == "v001"


def test_ffmpeg_fps():
    assert helpers.ffmpegFps(24.0) == "24"
    assert helpers.ffmpegFps(23.976023976) == "24000/1001"
    assert helpers.ffmpegFps(29.97) == "30000/1001"
    assert helpers.ffmpegFps(12.5) == "12.500"


def test_eval_frame():
    assert helpers.evalFrame("1001") == 1001
    assert helpers.evalFrame("$F+10") == 1011
    assert helpers.evalFrame("") is None
    assert helpers.evalFrame("$BAD") is None


def test_to_int():
    assert helpers.toInt("12") == 12
    assert helpers.toInt("") is None
    assert helpers.toInt("-", 5) == 5
