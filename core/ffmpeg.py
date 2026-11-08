"""ffmpeg lookup, command building and video conversion"""
import shutil
import string
import subprocess
from os import environ as osenviron
from pathlib import Path

import hou

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

# Transfer functions to encode linear EXR for display, applied as a 16-bit LUT before RGB -> YUV.
# Done with lutrgb filter instead of exr decoder "-apply_trc" option: that option was removed in newer ffmpeg.
EXR_TRANSFER_EXPRESSIONS = {
    "srgb":    "if(lte(val/maxval,0.0031308),12.92*val,maxval*(1.055*pow(val/maxval,1/2.4)-0.055))",
    "gamma22": "maxval*pow(val/maxval,1/2.2)",
    "bt709":   "if(lt(val/maxval,0.018),4.5*val,maxval*(1.099*pow(val/maxval,0.45)-0.099))",
}

def videoFilter(exr_transfer: str = "") -> str:
    """ffmpeg -vf chain: optional linear -> display transfer, then BT.709 RGB -> YUV conversion.

    Without explicit out_color_matrix swscale converts with BT.601 matrix while the file is tagged BT.709,
    which shifts hues (reds/greens) in players.
    """
    filters = []
    if exr_transfer:
        expr = EXR_TRANSFER_EXPRESSIONS.get(exr_transfer)
        if expr is None:
            log.warning("Unknown exr_transfer '%s', expected one of: %s", exr_transfer, ", ".join(EXR_TRANSFER_EXPRESSIONS))
        else:
            filters += ["format=rgb48le", f"lutrgb=r='{expr}':g='{expr}':b='{expr}'"]
    filters += ["scale=out_color_matrix=bt709:out_range=tv", "format=yuv420p",
                # Tag frames explicitly: newer ffmpeg passes EXR "linear" trc through filters
                # and it overrides -color_trc/-color_primaries output options
                "setparams=color_primaries=bt709:color_trc=iec61966-2-1:colorspace=bt709:range=tv"]
    return ",".join(filters)

class FFmpeg:
    """Wrapper around ffmpeg
    """
    def __init__(self, cmd: list, binary: str = "") -> None:

        self.cmdvar = cmd
        self.binary = findFFmpeg(binary)
        self.available = bool(self.binary)

        if not cmd:
            log.warning("No ffmpeg_cmd set in settings")

        if self.available:
            log.info("Using ffmpeg: %s", self.binary)
        else:
            hmsg("No ffmpeg found (settings, $PDG_FFMPEG, $HFS/bin/hffmpeg, system PATH)\n"
                 "Video conversion skipped, sequence is kept")

    def cmd(self, fps=24, resolution="1920x1080", aspect=1, start_frame=1001, input="", output="", exr_transfer="") -> list:
        """Build ffmpeg argv from template.

        Template entry whose placeholder is empty is skipped entirely,
        so optional flags can be switched off from settings.json.
        {vf} is the video filter chain built by videoFilter().
        """

        if input == "" or output == "":
            log.error("No input or output set")
            return 0

        template = self.cmdvar or []

        # Split template entries before formatting, so paths with spaces stay single arguments
        values = dict(fps=fps, resolution=resolution, aspect=aspect,
                    start_frame=start_frame, input=input, output=output,
                    vf=videoFilter(exr_transfer))
        commands = []
        for key in template:
            fields = [field for _, field, _, _ in string.Formatter().parse(key) if field]
            if any(str(values.get(field, "")) == "" for field in fields):
                continue
            for token in key.split():
                commands.append(token.format(**values))

        # "ffmpeg" in template means "the resolved executable"
        if commands and commands[0] == "ffmpeg" and getattr(self, "binary", ""):
            commands[0] = self.binary

        return commands

    def convert_to_video(self, fps=24, resolution="1920x1080", aspect=1, start_frame=1001, input="", output="", delete_input=False, exr_transfer=""):
        if not self.available:
            log.warning("ffmpeg is not available, video conversion skipped")
            return 0

        ffmpeg_cmd = self.cmd(fps=fps, resolution=resolution, aspect=aspect, exr_transfer=exr_transfer,
                            start_frame=start_frame, input=input, output=output)
        
        folder = Path(input).parent
        if folder.exists():
            files = [x for x in folder.iterdir()]
        else:
            files = []

        log.info("Running: %s", subprocess.list2cmdline(ffmpeg_cmd))
        try:
            subprocess.run(ffmpeg_cmd, check=True, capture_output=True, text=True, stdin=subprocess.DEVNULL)
        except subprocess.CalledProcessError as e:
            stderr_tail = "\n".join((e.stderr or "").strip().splitlines()[-15:])
            log.error("ffmpeg failed with exit code %s:\n%s", e.returncode, stderr_tail)
            return 0
        except FileNotFoundError as e:
            log.error("ffmpeg executable not found: %s", e)
            return 0

        if len(files) != 0 and delete_input:
            for file in files:
                file.unlink()
