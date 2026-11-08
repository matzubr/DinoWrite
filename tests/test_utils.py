def test_next_version_empty_or_missing(utils, tmp_path):
    assert utils.nextVersion(tmp_path / "missing") == "v001"
    assert utils.nextVersion(tmp_path) == "v001"


def test_next_version_ignores_non_version_folders_and_sorts_numerically(utils, tmp_path):
    for name in ["v003", "old", "v003_backup", "v999", "v1000"]:
        (tmp_path / name).mkdir()
    (tmp_path / "v2000").touch()  # file, not a folder
    assert utils.nextVersion(tmp_path) == "v1001"


def test_next_version_keeps_padding(utils, tmp_path):
    (tmp_path / "v0007").mkdir()
    assert utils.nextVersion(tmp_path) == "v0008"


def test_ffmpeg_fps(utils):
    assert utils.ffmpegFps(24.0) == "24"
    assert utils.ffmpegFps(23.976023976) == "24000/1001"
    assert utils.ffmpegFps(29.97) == "30000/1001"
    assert utils.ffmpegFps(12.5) == "12.500"


def test_eval_frame(utils):
    assert utils.evalFrame("1001") == 1001
    assert utils.evalFrame("$F+10") == 1011
    assert utils.evalFrame("") is None
    assert utils.evalFrame("$BAD") is None


def test_to_int(utils):
    assert utils.toInt("12") == 12
    assert utils.toInt("") is None
    assert utils.toInt("-", 5) == 5


def test_ffmpeg_cmd_keeps_paths_with_spaces(utils):
    ffmpeg = utils.FFmpeg.__new__(utils.FFmpeg)
    ffmpeg.cmdvar = ["ffmpeg", "-i {input}", "-r {fps}", "{output}"]
    cmd = ffmpeg.cmd(fps="24", input="/My Projects/a.%04d.exr", output="/My Projects/a.mov")
    assert cmd == ["ffmpeg", "-i", "/My Projects/a.%04d.exr", "-r", "24", "/My Projects/a.mov"]


def test_logger_has_single_handler_after_reload(utils):
    logger = utils.getLogger()
    utils.getLogger()
    # pytest adds its own LogCaptureHandler, count only ours
    ours = [h for h in logger.handlers if isinstance(h, utils._HoudiniConsoleHandler)]
    assert len(ours) == 1
    assert logger.name == "DinoWrite"
