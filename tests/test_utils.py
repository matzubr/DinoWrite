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


def _fake_env(monkeypatch, utils, env):
    monkeypatch.setattr(utils.hou, "getenv", lambda name, default=None: env.get(name, default))


def test_find_ffmpeg_prefers_houdini_hffmpeg(utils, tmp_path, monkeypatch):
    hffmpeg = tmp_path / "bin" / "hffmpeg"
    hffmpeg.parent.mkdir()
    hffmpeg.touch()
    _fake_env(monkeypatch, utils, {"HFS": tmp_path.as_posix()})
    monkeypatch.delenv("PDG_FFMPEG", raising=False)
    assert utils.findFFmpeg() == hffmpeg.as_posix()


def test_find_ffmpeg_custom_path_wins(utils, tmp_path, monkeypatch):
    custom = tmp_path / "my_ffmpeg"
    custom.touch()
    _fake_env(monkeypatch, utils, {})
    assert utils.findFFmpeg(custom.as_posix()) == custom.as_posix()


def test_find_ffmpeg_falls_back_to_path(utils, tmp_path, monkeypatch):
    _fake_env(monkeypatch, utils, {"HFS": (tmp_path / "no_houdini").as_posix()})
    monkeypatch.delenv("PDG_FFMPEG", raising=False)
    monkeypatch.setattr(utils.shutil, "which", lambda name: "/usr/bin/ffmpeg")
    assert utils.findFFmpeg() == "/usr/bin/ffmpeg"


def test_ffmpeg_cmd_uses_resolved_binary(utils):
    ffmpeg = utils.FFmpeg.__new__(utils.FFmpeg)
    ffmpeg.cmdvar = ["ffmpeg", "-i {input}", "{output}"]
    ffmpeg.binary = "/opt/hfs/bin/hffmpeg"
    assert ffmpeg.cmd(input="in.exr", output="out.mov")[0] == "/opt/hfs/bin/hffmpeg"


def test_video_filter(utils):
    assert utils.videoFilter("").startswith("scale=out_color_matrix=bt709:out_range=tv,format=yuv420p,setparams=")
    vf = utils.videoFilter("srgb")
    assert vf.startswith("format=rgb48le,lutrgb=r='")
    assert "lutrgb" in vf and vf.endswith(utils.videoFilter(""))
    assert utils.videoFilter("unknown") == utils.videoFilter("")


def test_ffmpeg_cmd_puts_filter_as_single_argument(utils):
    ffmpeg = utils.FFmpeg.__new__(utils.FFmpeg)
    ffmpeg.cmdvar = ["ffmpeg", "-i {input}", "-vf {vf}", "{output}"]
    ffmpeg.binary = ""
    cmd = ffmpeg.cmd(input="in.exr", output="out.mov", exr_transfer="srgb")
    assert cmd[3:5] == ["-vf", utils.videoFilter("srgb")]


def test_ffmpeg_cmd_skips_entry_with_empty_placeholder(utils):
    ffmpeg = utils.FFmpeg.__new__(utils.FFmpeg)
    ffmpeg.cmdvar = ["ffmpeg", "-start_number {start_frame}", "-i {input}", "{output}"]
    ffmpeg.binary = ""
    assert ffmpeg.cmd(start_frame="", input="in.png", output="out.mov") == ["ffmpeg", "-i", "in.png", "out.mov"]
