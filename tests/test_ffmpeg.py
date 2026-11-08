from DinoWrite.core import ffmpeg


def test_ffmpeg_cmd_keeps_paths_with_spaces():
    converter = ffmpeg.FFmpeg.__new__(ffmpeg.FFmpeg)
    converter.cmdvar = ["ffmpeg", "-i {input}", "-r {fps}", "{output}"]
    cmd = converter.cmd(fps="24", input="/My Projects/a.%04d.exr", output="/My Projects/a.mov")
    assert cmd == ["ffmpeg", "-i", "/My Projects/a.%04d.exr", "-r", "24", "/My Projects/a.mov"]


def _fake_env(monkeypatch, env):
    monkeypatch.setattr(ffmpeg.hou, "getenv", lambda name, default=None: env.get(name, default))


def test_find_ffmpeg_prefers_houdini_hffmpeg(tmp_path, monkeypatch):
    hffmpeg = tmp_path / "bin" / "hffmpeg"
    hffmpeg.parent.mkdir()
    hffmpeg.touch()
    _fake_env(monkeypatch, {"HFS": tmp_path.as_posix()})
    monkeypatch.delenv("PDG_FFMPEG", raising=False)
    assert ffmpeg.findFFmpeg() == hffmpeg.as_posix()


def test_find_ffmpeg_custom_path_wins(tmp_path, monkeypatch):
    custom = tmp_path / "my_ffmpeg"
    custom.touch()
    _fake_env(monkeypatch, {})
    assert ffmpeg.findFFmpeg(custom.as_posix()) == custom.as_posix()


def test_find_ffmpeg_falls_back_to_path(tmp_path, monkeypatch):
    _fake_env(monkeypatch, {"HFS": (tmp_path / "no_houdini").as_posix()})
    monkeypatch.delenv("PDG_FFMPEG", raising=False)
    monkeypatch.setattr(ffmpeg.shutil, "which", lambda name: "/usr/bin/ffmpeg")
    assert ffmpeg.findFFmpeg() == "/usr/bin/ffmpeg"


def test_ffmpeg_cmd_uses_resolved_binary():
    converter = ffmpeg.FFmpeg.__new__(ffmpeg.FFmpeg)
    converter.cmdvar = ["ffmpeg", "-i {input}", "{output}"]
    converter.binary = "/opt/hfs/bin/hffmpeg"
    assert converter.cmd(input="in.exr", output="out.mov")[0] == "/opt/hfs/bin/hffmpeg"


def test_video_filter():
    assert ffmpeg.videoFilter("").startswith("scale=out_color_matrix=bt709:out_range=tv,format=yuv420p,setparams=")
    vf = ffmpeg.videoFilter("srgb")
    assert vf.startswith("format=rgb48le,lutrgb=r='")
    assert "lutrgb" in vf and vf.endswith(ffmpeg.videoFilter(""))
    assert ffmpeg.videoFilter("unknown") == ffmpeg.videoFilter("")


def test_ffmpeg_cmd_puts_filter_as_single_argument():
    converter = ffmpeg.FFmpeg.__new__(ffmpeg.FFmpeg)
    converter.cmdvar = ["ffmpeg", "-i {input}", "-vf {vf}", "{output}"]
    converter.binary = ""
    cmd = converter.cmd(input="in.exr", output="out.mov", exr_transfer="srgb")
    assert cmd[3:5] == ["-vf", ffmpeg.videoFilter("srgb")]


def test_ffmpeg_cmd_skips_entry_with_empty_placeholder():
    converter = ffmpeg.FFmpeg.__new__(ffmpeg.FFmpeg)
    converter.cmdvar = ["ffmpeg", "-start_number {start_frame}", "-i {input}", "{output}"]
    converter.binary = ""
    assert converter.cmd(start_frame="", input="in.png", output="out.mov") == ["ffmpeg", "-i", "in.png", "out.mov"]
