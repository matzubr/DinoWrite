"""Flipbook EXR -> ACEScg, so it opens right in Nuke/comp with an ACES config.

A viewport flipbook EXR is the viewport image as seen (OCIO display/view, e.g. Rec.1886 / ACES SDR,
already applied), linearized with the inverse sRGB curve. To get scene-linear ACEScg back:

    EXR --sRGB curve--> pixels on screen --inverse display/view of the viewer--> ACEScg

An ACES viewer with the same display/view (Nuke, MPlay, Houdini) then shows exactly what the viewport
showed. Highlights are limited to what fit on screen: it's a preview, not a render.

Done with hoiiotool that ships with Houdini. --ociodisplay:inverse=1 needs OpenImageIO 2.5+
(older versions silently ignore it and would apply the forward transform).
Color spaces are addressed by aliases that every ACES cg/studio config has.
"""
import os
import re
import shutil
import subprocess
from pathlib import Path

import hou

from .log import log
from .process import NO_WINDOW

LINEAR_REC709 = "lin_rec709_srgb"
SRGB_TEXTURE = "srgb_tx"
ACESCG = "lin_ap1"
ACESCG_NAME = "ACEScg"
MIN_OIIO_VERSION = (2, 5)

_version_cache = {}


def findOiiotool(custom_path: str = "") -> str:
    """advanced.oiiotool_path -> $HFS/bin/hoiiotool -> hoiiotool/oiiotool in PATH. Empty if not found."""
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
    return shutil.which("hoiiotool") or shutil.which("oiiotool") or ""


def parseVersion(text: str) -> tuple:
    """'oiiotool OpenImageIO 2.5.16.0 http://...' -> (2, 5, 16, 0); () if there's no version"""
    match = re.search(r"(\d+)\.(\d+)(?:\.(\d+))?(?:\.(\d+))?", text or "")
    return tuple(int(part) for part in match.groups() if part is not None) if match else ()


def oiiotoolVersion(tool: str) -> tuple:
    if tool not in _version_cache:
        try:
            output = subprocess.run([tool, "--version"], capture_output=True, text=True, timeout=30,
                                    stdin=subprocess.DEVNULL, **NO_WINDOW).stdout
        except (OSError, subprocess.SubprocessError) as e:
            log.warning("Can't run %s --version: %s", tool, e)
            output = ""
        _version_cache[tool] = parseVersion(output)
    return _version_cache[tool]


def configPath() -> str:
    try:
        return hou.Color.ocio_configPath() or ""
    except (AttributeError, hou.Error):
        return hou.getenv("OCIO") or ""


def configHasSpaces() -> bool:
    """The config knows the aliases we use (every ACES cg/studio config does)"""
    try:
        spaces = {name.lower() for name in hou.Color.ocio_spaces()}
    except (AttributeError, hou.Error):
        return False
    return {"acescg", "linear rec.709 (srgb)"} <= spaces


def viewerDisplayView(scene_viewer) -> tuple:
    """OCIO display/view the viewport is shown with; ("", "") when the viewer doesn't use OCIO"""
    try:
        if scene_viewer is not None and scene_viewer.usingOCIO():
            return scene_viewer.getOCIODisplay(), scene_viewer.getOCIOView()
    except (AttributeError, hou.Error) as e:
        log.warning("Can't read OCIO display/view of the viewer: %s", e)
    return "", ""


def command(tool: str, config: str, input_pattern: str, output_pattern: str, frame_range: tuple,
            padding: int, display: str, view: str, threads: int = 0) -> list:
    """hoiiotool argv for a part of the frame range ('#' in patterns is the frame number)"""
    start, end = frame_range
    cmd = [tool]
    if threads:
        cmd += ["--threads", str(int(threads))]
    if config:
        cmd += ["--colorconfig", config]
    return cmd + ["--frames", f"{int(start)}-{int(end)}", "--framepadding", str(int(padding)), input_pattern,
                  "--colorconvert", LINEAR_REC709, SRGB_TEXTURE,
                  f"--ociodisplay:from={ACESCG}:inverse=1", display, view,
                  "--attrib", "oiio:ColorSpace", ACESCG_NAME,
                  "-d", "half", "-o", output_pattern]


def processCount(frames: int) -> int:
    """Half of the CPU cores, max 8: one process per part of the range scales better than threads"""
    return max(1, min(8, (os.cpu_count() or 2) // 2, frames))


def splitFrames(start: int, end: int, parts: int) -> list:
    """Split start..end (inclusive) into contiguous ranges of nearly equal size"""
    frames = end - start + 1
    parts = max(1, min(parts, frames))
    size, extra = divmod(frames, parts)
    ranges, first = [], start
    for index in range(parts):
        last = first + size - 1 + (1 if index < extra else 0)
        ranges.append((first, last))
        first = last + 1
    return ranges


def commands(tool: str, config: str, input_pattern: str, output_pattern: str, frame_range: tuple,
             padding: int, display: str, view: str) -> list:
    """One hoiiotool command per part of the frame range, to run in parallel"""
    start, end = int(frame_range[0]), int(frame_range[1])
    count = processCount(end - start + 1)
    threads = max(1, (os.cpu_count() or 2) // count)
    return [command(tool, config, input_pattern, output_pattern, part, padding, display, view, threads)
            for part in splitFrames(start, end, count)]


def plan(scene_viewer, oiiotool_path: str = ""):
    """(tool, config, display, view) when the conversion is possible, otherwise None (reason logged)"""
    display, view = viewerDisplayView(scene_viewer)
    if not display or not view:
        log.info("EXR kept as recorded: the viewer doesn't use OCIO")
        return None
    if not configHasSpaces():
        log.warning("EXR kept as recorded: the OCIO config has no ACEScg / Linear Rec.709 (not an ACES config)")
        return None
    tool = findOiiotool(oiiotool_path)
    if not tool:
        log.warning("EXR kept as recorded: hoiiotool/oiiotool not found")
        return None
    version = oiiotoolVersion(tool)
    if version[:2] < MIN_OIIO_VERSION:
        log.warning("EXR kept as recorded: %s is OpenImageIO %s, inverse display transform needs %s+",
                    tool, ".".join(map(str, version)) or "?", ".".join(map(str, MIN_OIIO_VERSION)))
        return None
    return tool, configPath(), display, view
