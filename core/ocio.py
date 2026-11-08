"""OCIO display transform for flipbook sequences via hoiiotool (OpenImageIO that ships with Houdini).

Linear EXR flipbook -> OCIO display/view (same as the viewer shows) -> 16-bit PNG sequence -> ffmpeg.
"""
import shutil
import subprocess
from pathlib import Path

import hou

from .log import log

# Color space of flipbook EXRs. scene_linear is an OCIO role, resolved by the active config
DEFAULT_INPUT_SPACE = "scene_linear"


def findOiiotool(custom_path: str = "") -> str:
    """Find oiiotool executable.

    1. custom_path from settings (advanced.oiiotool_path)
    2. hoiiotool that ships with Houdini: $HFS/bin/hoiiotool
    3. hoiiotool / oiiotool from system PATH

    Returns:
        str: Path to executable or empty string if nothing found
    """
    candidates = []
    if custom_path:
        candidates.append(hou.text.expandString(custom_path))
    hfs = hou.getenv("HFS")
    if hfs:
        exe = ".exe" if hou.getenv("OS") == "Windows_NT" else ""
        candidates.append((Path(hfs) / "bin" / f"hoiiotool{exe}").as_posix())

    for candidate in candidates:
        if Path(candidate).is_file():
            return candidate
        log.warning("oiiotool not found at: %s", candidate)

    return shutil.which("hoiiotool") or shutil.which("oiiotool") or ""


def configPath() -> str:
    """Path to the OCIO config Houdini is using (empty if unknown)"""
    try:
        return hou.Color.ocio_configPath() or ""
    except (AttributeError, hou.Error):
        return hou.getenv("OCIO") or ""


def displayView(scene_viewer=None, display: str = "", view: str = "") -> tuple:
    """Resolve OCIO display/view: explicit settings -> current Scene Viewer -> config defaults.

    Args:
        scene_viewer (hou.SceneViewer, optional): viewer the flipbook is recorded from
        display (str, optional): display from settings, empty means "take from viewer"
        view (str, optional): view from settings, empty means "take from viewer"
    """
    if scene_viewer is not None and (not display or not view):
        try:
            if scene_viewer.usingOCIO():
                display = display or scene_viewer.getOCIODisplay()
                view = view or scene_viewer.getOCIOView()
        except (AttributeError, hou.Error) as e:
            log.warning("Can't read OCIO display/view from viewer: %s", e)
    try:
        display = display or hou.Color.ocio_defaultDisplay()
        view = view or hou.Color.ocio_defaultView()
    except (AttributeError, hou.Error) as e:
        log.warning("Can't read OCIO defaults: %s", e)
    return display, view


def displayCommand(tool: str, config: str, input_pattern: str, output_pattern: str,
                   frame_range: tuple, padding: int, display: str, view: str,
                   input_space: str = DEFAULT_INPUT_SPACE) -> list:
    """Build oiiotool argv for a whole sequence.

    Patterns use '#' as the frame number wildcard, padding is set by --framepadding:
        hoiiotool --colorconfig cfg --frames 1001-1100 --framepadding 4 in.#.exr
                  --ociodisplay:from=scene_linear "sRGB - Display" "ACES 1.0 - SDR Video"
                  -d uint16 -o out.#.png
    """
    start, end = frame_range
    cmd = [tool]
    if config:
        cmd += ["--colorconfig", config]
    cmd += ["--frames", f"{int(start)}-{int(end)}", "--framepadding", str(int(padding)), input_pattern]
    ociodisplay = f"--ociodisplay:from={input_space}" if input_space else "--ociodisplay"
    cmd += [ociodisplay, display, view, "-d", "uint16", "-o", output_pattern]
    return cmd


def applyDisplayTransform(tool: str, config: str, input_pattern: str, output_pattern: str,
                          frame_range: tuple, padding: int, display: str, view: str,
                          input_space: str = DEFAULT_INPUT_SPACE) -> bool:
    """Run oiiotool display transform. Returns True on success."""
    cmd = displayCommand(tool, config, input_pattern, output_pattern, frame_range, padding,
                         display, view, input_space)
    Path(output_pattern).parent.mkdir(parents=True, exist_ok=True)
    log.info("OCIO display transform '%s' / '%s', running: %s", display, view, subprocess.list2cmdline(cmd))
    try:
        subprocess.run(cmd, check=True, capture_output=True, text=True, stdin=subprocess.DEVNULL)
    except subprocess.CalledProcessError as e:
        output = (e.stderr or "") + (e.stdout or "")
        tail = "\n".join(output.strip().splitlines()[-15:])
        log.error("oiiotool failed with exit code %s:\n%s", e.returncode, tail)
        return False
    except FileNotFoundError as e:
        log.error("oiiotool executable not found: %s", e)
        return False
    return True
