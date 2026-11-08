"""OCIO display transform for flipbook sequences via hoiiotool (OpenImageIO that ships with Houdini).

Linear EXR flipbook -> OCIO display/view (same as the viewer shows) -> 16-bit PNG sequence -> ffmpeg.
"""
import os
import shutil
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
                   input_space: str = DEFAULT_INPUT_SPACE, threads: int = 0) -> list:
    """Build oiiotool argv for a frame range.

    Patterns use '#' as the frame number wildcard, padding is set by --framepadding:
        hoiiotool --colorconfig cfg --frames 1001-1100 --framepadding 4 in.#.exr --ch R,G,B
                  --ociodisplay:from=scene_linear "sRGB - Display" "ACES 1.0 - SDR Video"
                  -d uint16 -o out.#.png
    Alpha is dropped (--ch R,G,B): video has no alpha, a quarter less work and disk.
    """
    start, end = frame_range
    cmd = [tool]
    if threads:
        cmd += ["--threads", str(int(threads))]
    if config:
        cmd += ["--colorconfig", config]
    cmd += ["--frames", f"{int(start)}-{int(end)}", "--framepadding", str(int(padding)), input_pattern,
            "--ch", "R,G,B"]
    ociodisplay = f"--ociodisplay:from={input_space}" if input_space else "--ociodisplay"
    cmd += [ociodisplay, display, view, "-d", "uint16", "-o", output_pattern]
    return cmd


def processCount(setting: int, frames: int) -> int:
    """How many hoiiotool processes to run: setting, or half of the CPU cores (max 8) for 0/auto.

    One process reads EXR / writes PNG frame by frame, so several processes on parts of the
    range scale much better than one process with more threads.
    """
    count = int(setting or 0) or min(8, max(1, (os.cpu_count() or 2) // 2))
    return max(1, min(count, frames))


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


def displayCommands(tool: str, config: str, input_pattern: str, output_pattern: str,
                    frame_range: tuple, padding: int, display: str, view: str,
                    input_space: str = DEFAULT_INPUT_SPACE, processes: int = 0) -> list:
    """One oiiotool command per part of the frame range, to run in parallel"""
    start, end = int(frame_range[0]), int(frame_range[1])
    count = processCount(processes, end - start + 1)
    threads = max(1, (os.cpu_count() or 2) // count)
    return [displayCommand(tool, config, input_pattern, output_pattern, part, padding,
                           display, view, input_space, threads=threads)
            for part in splitFrames(start, end, count)]
