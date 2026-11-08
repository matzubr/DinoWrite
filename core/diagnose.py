"""Color diagnostics: which input color space makes the video look like MPlay.

Run in Houdini's Python Shell:
    import DinoWrite
    DinoWrite.diagnose_colors(r"C:/path/to/preview/flipbook/v004")

Logs the color metadata of the first EXR and writes that frame through the OCIO display/view
once per candidate input color space into <folder>/_color_check. Compare the PNGs with MPlay
and set the matching one in Settings -> Video -> EXR color space (advanced.ocio_input_space).
"""
import re
import subprocess
import webbrowser
from pathlib import Path

from . import ocio
from .log import log
from .process import NO_WINDOW

CHECK_FOLDER = "_color_check"
FROM_FILE = ""  # no from=: oiiotool uses the color space stored in the file (or its default)
# Linear spaces a flipbook EXR may be in, matched case-insensitively against the config's names
CANDIDATE_PATTERNS = (r"linear.*rec\.?\s?709|lin_rec709|linear.*srgb", r"acescg", r"aces2065")
METADATA_KEYS = re.compile(r"colorspace|chromaticities|oiio:|whiteLuminance|primaries", re.IGNORECASE)


def candidates(spaces: list) -> list:
    """(label, from space) pairs: file metadata, scene_linear role, then matching config spaces"""
    result = [("file metadata", FROM_FILE), ("scene_linear role", "scene_linear")]
    for pattern in CANDIDATE_PATTERNS:
        for space in spaces:
            if re.search(pattern, space, re.IGNORECASE) and space not in [c[1] for c in result]:
                result.append((space, space))
    return result


def firstExr(path: Path) -> Path:
    path = Path(path)
    if path.is_file():
        return path
    exrs = sorted(path.glob("*.exr"))
    if not exrs:
        raise FileNotFoundError(f"No .exr files in {path}")
    return exrs[0]


def checkCommand(tool: str, config: str, exr: Path, output: Path, display: str, view: str, space: str) -> list:
    cmd = [tool]
    if config:
        cmd += ["--colorconfig", config]
    ociodisplay = f"--ociodisplay:from={space}" if space else "--ociodisplay"
    return cmd + [exr.as_posix(), "--ch", "R,G,B", ociodisplay, display, view, "-d", "uint8",
                  "-o", output.as_posix()]


def _safeName(text: str) -> str:
    return re.sub(r"[^A-Za-z0-9_.-]+", "_", text).strip("_")


def diagnoseColors(path, display: str = "", view: str = "", oiiotool: str = "", spaces=None,
                   open_folder: bool = True) -> Path:
    """Write the first EXR of a flipbook through each candidate input space. Returns the output folder."""
    exr = firstExr(path)
    tool = ocio.findOiiotool(oiiotool)
    if not tool:
        raise RuntimeError("hoiiotool/oiiotool not found")
    config = ocio.configPath()
    if not display or not view:
        display, view = ocio.displayView(None, display, view)  # config default = what MPlay uses
    if spaces is None:
        try:
            import hou
            spaces = list(hou.Color.ocio_spaces())
        except Exception:
            spaces = []

    info = subprocess.run([tool, "--info", "-v", exr.as_posix()], capture_output=True, text=True,
                          stdin=subprocess.DEVNULL, timeout=60, **NO_WINDOW).stdout
    metadata = [line.strip() for line in info.splitlines() if METADATA_KEYS.search(line)]
    log.info("Color check of %s\n  OCIO config: %s\n  display/view: %s / %s\n  EXR color metadata:\n    %s",
             exr.name, config or "?", display, view, "\n    ".join(metadata) or "(none)")

    out = exr.parent / CHECK_FOLDER
    out.mkdir(exist_ok=True)
    lines = [f"Frame: {exr.name}", f"Display / view: {display} / {view}", f"OCIO config: {config}",
             "EXR color metadata:", *["  " + m for m in metadata or ["(none)"]], "", "Files:"]
    for index, (label, space) in enumerate(candidates(spaces), start=1):
        output = out / f"{index:02d}_{_safeName(label)}.png"
        result = subprocess.run(checkCommand(tool, config, exr, output, display, view, space),
                                capture_output=True, text=True, stdin=subprocess.DEVNULL, timeout=120, **NO_WINDOW)
        status = "ok" if result.returncode == 0 else f"FAILED: {(result.stderr or result.stdout).strip()[-200:]}"
        lines.append(f"  {output.name}: input color space = {space or 'from file metadata'} ({status})")
        log.info("Color check %s: %s", output.name, status)
    (out / "README.txt").write_text("\n".join(lines) + "\n\nPick the PNG that looks like MPlay and set its "
                                    "input color space in Settings -> Video -> EXR color space.\n",
                                    encoding="utf-8")
    log.info("Color check written to %s", out)
    if open_folder:
        webbrowser.open(out.as_uri())
    return out
