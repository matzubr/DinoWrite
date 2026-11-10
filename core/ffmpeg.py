"""ffmpeg lookup, command building and video conversion"""
import shutil
import string
import subprocess
from os import environ as osenviron
from pathlib import Path

import hou

from . import process
from .log import hmsg, log

def findFFmpeg(custom_path: str = "") -> str:
    """Find ffmpeg executable, same lookup order as Houdini's FFmpeg Encode Video TOP.

    1. custom_path from settings.json (advanced.ffmpeg_path)
    2. $PDG_FFMPEG environment variable
    3. ffmpeg that ships with Houdini: $HFS/bin/hffmpeg
    4. ffmpeg from system PATH

    Returns:
        str: Path to executable or empty string if nothing found
    """
    candidates = []
    if custom_path:
        candidates.append(hou.text.expandString(custom_path))
    if osenviron.get("PDG_FFMPEG"):
        candidates.append(osenviron["PDG_FFMPEG"])
    hfs = hou.getenv("HFS")
    if hfs:
        exe = ".exe" if hou.getenv("OS") == "Windows_NT" else ""
        candidates.append((Path(hfs) / "bin" / f"hffmpeg{exe}").as_posix())

    for candidate in candidates:
        if Path(candidate).is_file():
            return candidate
        log.warning("ffmpeg not found at: %s", candidate)

    return shutil.which("ffmpeg") or ""

# Linear EXR -> sRGB curve, applied as a 16-bit LUT before RGB -> YUV (same as "EXR Transfer Func" of the
# FFmpeg Encode Video TOP). Done with lutrgb filter: the exr decoder "-apply_trc" option was removed in newer ffmpeg.
SRGB_EXPRESSION = "if(lte(val/maxval,0.0031308),12.92*val,maxval*(1.055*pow(val/maxval,1/2.4)-0.055))"


EVEN_CROP = "crop=trunc(iw/2)*2:trunc(ih/2)*2:0:0"


def videoFilter(srgb: bool = False, color_trc: str = "iec61966-2-1") -> str:
    """ffmpeg -vf chain: optional linear -> sRGB curve, then BT.709 RGB -> YUV conversion.

    Without explicit out_color_matrix swscale converts with BT.601 matrix while the file is tagged BT.709,
    which shifts hues (reds/greens) in players.
    """
    filters = []
    if srgb:
        filters += ["format=rgb48le", f"lutrgb=r='{SRGB_EXPRESSION}':g='{SRGB_EXPRESSION}':b='{SRGB_EXPRESSION}'"]
    # yuv420p (H.264 and most codecs) needs even width and height: an odd size loses its last column/row
    filters += [EVEN_CROP, "scale=out_color_matrix=bt709:out_range=tv", "format=yuv420p",
                # Tag frames explicitly: newer ffmpeg passes EXR "linear" trc through filters
                # and it overrides -color_trc/-color_primaries output options
                f"setparams=color_primaries=bt709:color_trc={color_trc}:colorspace=bt709:range=tv"]
    return ",".join(filters)

# Video encoders, best first. ffmpeg that ships with Houdini (hffmpeg) is built without GPL parts,
# so it has no libx264: H.264 comes from OS/GPU encoders when they are compiled in, mpeg4 is always there.
# {bitrate} is filled by videoBitrate() for encoders without a constant quality mode.
CODECS = {
    "libx264":           ["-c:v", "libx264", "-crf", "15", "-preset", "slow"],
    "h264_videotoolbox": ["-c:v", "h264_videotoolbox", "-b:v", "{bitrate}"],
    "h264_mf":           ["-c:v", "h264_mf", "-b:v", "{bitrate}"],
    "h264_nvenc":        ["-c:v", "h264_nvenc", "-b:v", "{bitrate}"],
    "h264_amf":          ["-c:v", "h264_amf", "-b:v", "{bitrate}"],
    "h264_qsv":          ["-c:v", "h264_qsv", "-b:v", "{bitrate}"],
    "mpeg4":             ["-c:v", "mpeg4", "-q:v", "2"],
}
AUTO_CODECS = tuple(CODECS)
CODEC_PLACEHOLDER = "{codec}"

_encoders_cache = {}


def availableEncoders(binary: str) -> set:
    """Encoder names compiled into this ffmpeg (cached per executable). Empty set if it can't be asked."""
    if not binary:
        return set()
    if binary not in _encoders_cache:
        try:
            output = subprocess.run([binary, "-hide_banner", "-encoders"], capture_output=True, text=True,
                                    stdin=subprocess.DEVNULL, timeout=30, **process.NO_WINDOW).stdout
        except (OSError, subprocess.SubprocessError) as e:
            log.warning("Can't list ffmpeg encoders: %s", e)
            return set()
        _encoders_cache[binary] = parseEncoders(output)
    return _encoders_cache[binary]


def parseEncoders(output: str) -> set:
    """Names from 'ffmpeg -encoders' lines like ' V....D libx264   libx264 H.264 ...'"""
    names = set()
    _, separator, table = output.partition("------")  # legend above the separator, encoders below
    for line in (table if separator else output).splitlines():
        parts = line.split()
        if len(parts) >= 2 and len(parts[0]) == 6 and parts[0][0] in "VAS":
            names.add(parts[1])
    return names


def codecCandidates(setting: str, available: set) -> list:
    """Encoders to try in order. 'auto': every known encoder this ffmpeg has (all known if unknown)."""
    if setting and setting != "auto":
        return [setting]
    if not available:
        return list(AUTO_CODECS)
    return [codec for codec in AUTO_CODECS if codec in available]


def videoBitrate(resolution: str, fps: str) -> str:
    """~0.25 bits per pixel: visually clean preview, e.g. 1920x1080@24 -> 12M, 3840x2160@24 -> 50M"""
    try:
        width, height = (int(v) for v in resolution.lower().split("x"))
        num, _, den = str(fps).partition("/")
        rate = float(num) / float(den or 1)
    except ValueError:
        return "20M"
    return f"{max(4, round(width * height * rate * 0.25 / 1e6))}M"


class FFmpeg:
    """Wrapper around ffmpeg
    """
    def __init__(self, cmd: list, binary: str = "", codec: str = "auto") -> None:

        self.cmdvar = cmd
        self.codec = codec or "auto"
        self.binary = findFFmpeg(binary)
        self.available = bool(self.binary)

        if not cmd:
            log.warning("No ffmpeg_cmd set in settings")

        if self.available:
            log.info("Using ffmpeg: %s", self.binary)
        else:
            hmsg("No ffmpeg found (settings, $PDG_FFMPEG, $HFS/bin/hffmpeg, system PATH)\n"
                 "Video conversion skipped, sequence is kept")

    def cmd(self, fps=24, resolution="1920x1080", aspect=1, start_frame=1001, input="", output="", srgb=False,
            codec="libx264", color_trc="iec61966-2-1", comment="", audio_input=(), audio=(), metadata=()) -> list:
        """Build ffmpeg argv from template.

        Template entry whose placeholder is empty is skipped entirely,
        so optional flags can be switched off from settings.json.
        {vf} is the video filter chain built by videoFilter().
        {codec} expands to the encoder arguments from CODECS.
        {audio_input}, {audio}, {metadata} expand to argument lists (scene sound input / its mapping and
        codec / the flipbook passport); a template without them just has no sound or passport.
        """

        if input == "" or output == "":
            log.error("No input or output set")
            return []

        template = self.cmdvar or []

        # Split template entries before formatting, so paths with spaces stay single arguments
        values = dict(fps=fps, resolution=resolution, aspect=aspect,
                    start_frame=start_frame, input=input, output=output, color_trc=color_trc, comment=comment,
                    vf=videoFilter(srgb, color_trc))
        lists = {"{audio_input}": audio_input, "{audio}": audio, "{metadata}": metadata}
        commands = []
        for key in template:
            if key.strip() in lists:
                commands += [str(arg) for arg in lists[key.strip()]]
                continue
            if key.strip() == CODEC_PLACEHOLDER:
                bitrate = videoBitrate(str(resolution), str(fps))
                commands += [arg.format(bitrate=bitrate) for arg in CODECS.get(codec, ["-c:v", codec])]
                continue
            fields = [field for _, field, _, _ in string.Formatter().parse(key) if field]
            if any(str(values.get(field, "")) == "" for field in fields):
                continue
            for token in key.split():
                commands.append(token.format(**values))

        # "ffmpeg" in template means "the resolved executable"
        if commands and commands[0] == "ffmpeg" and self.binary:
            commands[0] = self.binary

        return commands

    def usesCodecPlaceholder(self) -> bool:
        return any(key.strip() == CODEC_PLACEHOLDER for key in (self.cmdvar or []))

    def codecs(self) -> list:
        """Encoders to try in order; [None] when the encoder is written in the ffmpeg command itself"""
        if not self.usesCodecPlaceholder():
            return [None]
        return codecCandidates(self.codec, availableEncoders(self.binary))

    def encodeCommand(self, codec, progress_file: Path, **values) -> list:
        """ffmpeg argv for one encoder, writing machine readable progress (frame=N) to progress_file"""
        cmd = self.cmd(codec=codec, **values)
        cmd[1:1] = ["-nostats", "-progress", Path(progress_file).as_posix()]
        return cmd


def progressFromFile(progress_file: Path, total_frames: int):
    """Last 'frame=N' from ffmpeg -progress output as 0..1, None if unknown"""
    if not total_frames:
        return None
    try:
        text = progress_file.read_text(errors="replace")
    except OSError:
        return None
    frames = [line.split("=", 1)[1] for line in text.splitlines() if line.startswith("frame=")]
    if not frames or not frames[-1].strip().isdigit():
        return None
    return int(frames[-1]) / total_frames
