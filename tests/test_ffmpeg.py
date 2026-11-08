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


ENCODERS_OUTPUT = """Encoders:
 V..... = Video
 ------
 V....D h264_mf              H264 via MediaFoundation (codec h264)
 V....D h264_nvenc           NVIDIA NVENC H.264 encoder (codec h264)
 V....D mpeg4                MPEG-4 part 2
 A....D aac                  AAC (Advanced Audio Coding)
"""


def test_parse_encoders():
    assert ffmpeg.parseEncoders(ENCODERS_OUTPUT) == {"h264_mf", "h264_nvenc", "mpeg4", "aac"}


def test_codec_candidates_for_houdini_ffmpeg_without_libx264():
    available = ffmpeg.parseEncoders(ENCODERS_OUTPUT)
    assert ffmpeg.codecCandidates("auto", available) == ["h264_mf", "h264_nvenc", "mpeg4"]
    assert ffmpeg.codecCandidates("mpeg4", available) == ["mpeg4"]
    assert ffmpeg.codecCandidates("auto", set()) == list(ffmpeg.AUTO_CODECS)


def test_video_bitrate():
    assert ffmpeg.videoBitrate("1920x1080", "24") == "12M"
    assert ffmpeg.videoBitrate("3840x2160", "24000/1001") == "50M"
    assert ffmpeg.videoBitrate("320x240", "24") == "4M"


def test_codec_placeholder_expands_to_encoder_args():
    converter = ffmpeg.FFmpeg.__new__(ffmpeg.FFmpeg)
    converter.cmdvar = ["ffmpeg", "-i {input}", "{codec}", "{output}"]
    converter.binary = ""
    assert converter.cmd(input="in.png", output="out.mov", codec="h264_mf", resolution="1920x1080", fps="24") == \
        ["ffmpeg", "-i", "in.png", "-c:v", "h264_mf", "-b:v", "12M", "out.mov"]


def test_convert_falls_back_to_next_encoder(monkeypatch):
    from DinoWrite.core import process

    tried = []

    def fake_run(cmd, label, progress=None):
        codec = cmd[cmd.index("-c:v") + 1]
        tried.append(codec)
        return process.Result(returncode=0 if codec == "mpeg4" else 1)

    monkeypatch.setattr(ffmpeg.process, "run", fake_run)
    monkeypatch.setattr(ffmpeg, "availableEncoders", lambda binary: ffmpeg.parseEncoders(ENCODERS_OUTPUT))
    converter = ffmpeg.FFmpeg.__new__(ffmpeg.FFmpeg)
    converter.cmdvar = ["ffmpeg", "-i {input}", "{codec}", "{output}"]
    converter.binary, converter.available, converter.codec = "hffmpeg", True, "auto"
    assert converter.convert_to_video(input="in.png", output="out.mov")
    assert tried == ["h264_mf", "h264_nvenc", "mpeg4"]
