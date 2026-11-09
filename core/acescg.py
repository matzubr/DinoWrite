"""Kept flipbook EXR rewritten by hoiiotool: -> ACEScg (opens right in Nuke/comp with an ACES config),
DWAA compression and the flipbook passport in the header.

A viewport flipbook EXR is the viewport image as seen (OCIO display/view, e.g. Rec.1886 / ACES SDR,
already applied), linearized with the inverse sRGB curve. To get scene-linear ACEScg back:

    EXR --sRGB curve--> pixels on screen --inverse display/view of the viewer--> ACEScg

An ACES viewer with the same display/view (Nuke, MPlay, Houdini) then shows exactly what the viewport
showed. Highlights are limited to what fit on screen: it's a preview, not a render.

The exact transform is baked with PyOpenColorIO (ships with Houdini) into a .ctf file and applied by
hoiiotool with --ociofiletransform, which every OpenImageIO with OCIO 2 has. (--ociodisplay:inverse=1
isn't used: Houdini's hoiiotool silently ignores it and applies the forward transform.)
Color spaces are addressed by aliases that every ACES cg/studio config has.

Kept PNG/JPG get the same treatment, into the config's 'matte_paint' role instead of ACEScg: that's what
Nuke reads 8-bit files as by default, so they look right with no Read node changes. They are screen
pixels already (no sRGB curve step). In the ACES 1.3 configs since cg-config v2.1 matte_paint is ACEScct
(log: keeps the highlights, error ~1/255); older ones (cg-config v1, Nuke's aces_1.2) use sRGB - Texture,
which can't hold anything brighter than scene 1.0: the brightest parts come out greyish in Nuke.
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
MATTE_PAINT = "matte_paint"  # OCIO role: Nuke's default colorspace for 8-bit files
CTF_NAME = "screen_to_acescg.ctf"
LDR_EXTS = ("png", "jpg", "jpeg")

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


def readColorspace(ext: str, scene_viewer, acescg_on: bool = True, keeps_exr: bool = True,
                   matte_on: bool = True) -> tuple:
    """(short name, how to read it in Nuke) of the colorspace a flipbook file is written in"""
    display, view = viewerDisplayView(scene_viewer)
    shown = f"{display} / {view}" if display else "sRGB"
    if not keeps_exr:
        return "temporary", f"Only for the video: the {ext.upper()} are deleted after conversion"
    if ext == "exr":
        if acescg_on and display and configHasSpaces():
            return ACESCG_NAME, (f"Converted to ACEScg after recording.\nNuke: Read colorspace ACEScg (the default "
                                 f"for EXR with an ACES config), viewer {shown}: looks like the Houdini viewport")
        return "Linear Rec.709", ("As recorded: the viewport look linearized with the inverse sRGB curve.\n"
                                  "Nuke: Read colorspace 'Linear Rec.709 (sRGB)', viewer sRGB without tone mapping\n"
                                  "(Un-tone-mapped / Raw): looks like the Houdini viewport")
    if display and matte_on and configHasSpaces():
        return MATTE_PAINT, (f"Converted after recording to the OCIO role matte_paint: Nuke's default for 8-bit files.\n"
                             f"Nuke: Read as is, viewer {shown}: looks like the Houdini viewport.\n"
                             "Other image viewers show it flat (ACEScct) or too bright (sRGB - Texture): use the video")
    if display:
        return view, (f"The viewport look as is ({shown} already applied).\nNuke: Read with the inverse of this "
                      f"display/view (e.g. '{view} ({display})' in the colorspace menu),\nor Raw with a Raw viewer")
    return "sRGB", "The viewport look as is, sRGB.\nNuke: Read colorspace sRGB, or Raw with a Raw viewer"


def bakeTransform(config_path: str, display: str, view: str, ctf_path: Path, target: str = ACESCG,
                  linearized: bool = True) -> Path:
    """Write [sRGB curve] + inverse display/view -> ACEScg [-> target] as one exact .ctf (raises on failure)

    linearized: the input is the screen linearized with the inverse sRGB curve (EXR); False: screen pixels (PNG/JPG)
    """
    import PyOpenColorIO as OCIO  # ships with Houdini

    config = OCIO.Config.CreateFromFile(config_path) if config_path else OCIO.GetCurrentConfig()
    group = OCIO.GroupTransform()
    if linearized:
        group.appendTransform(OCIO.ColorSpaceTransform(src=LINEAR_REC709, dst=SRGB_TEXTURE))
    group.appendTransform(OCIO.DisplayViewTransform(src=ACESCG, display=display, view=view,
                                                    direction=OCIO.TRANSFORM_DIR_INVERSE))
    if target != ACESCG:
        group.appendTransform(OCIO.ColorSpaceTransform(src=ACESCG, dst=target))
    processor = config.getProcessor(group).getOptimizedProcessor(OCIO.OPTIMIZATION_NONE)
    processor.createGroupTransform().write(formatName="Color Transform Format", fileName=str(ctf_path),
                                           config=config)
    return Path(ctf_path)


COMPRESSION = {"dwaa": "dwaa:45", "zip": "zip", "piz": "piz", "none": "none"}


def compressionArg(setting: str) -> str:
    """advanced.exr_compression -> OpenImageIO compression name (dwaa:45 by default)"""
    return COMPRESSION.get(str(setting or "dwaa").lower(), COMPRESSION["dwaa"])


def outputArgs(ext: str, compression: str = "dwaa:45") -> list:
    """Pixel type and compression of the rewritten files: half EXR, 8-bit PNG/JPG like the recorded ones"""
    ext = ext.lower().lstrip(".")
    if ext == "exr":
        return ["--compression", compression, "-d", "half"]
    if ext in ("jpg", "jpeg"):
        return ["--compression", "jpeg:95", "-d", "uint8"]
    return ["-d", "uint8"]


def command(tool: str, input_pattern: str, output_pattern: str, frame_range: tuple, padding: int,
            ctf_path: str = "", threads: int = 0, compression: str = "dwaa:45", attributes: list = (),
            colorspace: str = ACESCG_NAME) -> list:
    """hoiiotool argv for a part of the frame range ('#' in patterns is the frame number).

    ctf_path: color transform to ACEScg / matte_paint (empty: colors stay as recorded)
    attributes: extra '--attrib name value' args (the flipbook passport)
    colorspace: what the ctf converts to, written in the header
    """
    start, end = frame_range
    cmd = [tool]
    if threads:
        cmd += ["--threads", str(int(threads))]
    cmd += ["--frames", f"{int(start)}-{int(end)}", "--framepadding", str(int(padding)), input_pattern]
    if ctf_path:
        cmd += ["--ociofiletransform", str(ctf_path), "--attrib", "oiio:ColorSpace", colorspace]
    cmd += list(attributes)
    return cmd + outputArgs(Path(output_pattern).suffix, compression) + ["-o", output_pattern]


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


def commands(tool: str, input_pattern: str, output_pattern: str, frame_range: tuple, padding: int,
             ctf_path: str = "", compression: str = "dwaa:45", attributes: list = (),
             colorspace: str = ACESCG_NAME) -> list:
    """One hoiiotool command per part of the frame range, to run in parallel"""
    start, end = int(frame_range[0]), int(frame_range[1])
    count = processCount(end - start + 1)
    threads = max(1, (os.cpu_count() or 2) // count)
    return [command(tool, input_pattern, output_pattern, part, padding, ctf_path, threads, compression, attributes,
                    colorspace)
            for part in splitFrames(start, end, count)]


def plan(scene_viewer, ctf_path: Path, ext: str = "exr"):
    """Bake the transform of a kept sequence to ctf_path: EXR -> ACEScg, PNG/JPG -> matte_paint.
    Returns (display, view) or None when it isn't possible (logged)"""
    kind = ext.upper()
    display, view = viewerDisplayView(scene_viewer)
    if not display or not view:
        log.info("%s colors kept as recorded: the viewer doesn't use OCIO", kind)
        return None
    if not configHasSpaces():
        log.warning("%s colors kept as recorded: the OCIO config has no ACEScg / Linear Rec.709 (not ACES)", kind)
        return None
    ldr = ext.lower() in LDR_EXTS
    try:
        bakeTransform(configPath(), display, view, ctf_path, target=MATTE_PAINT if ldr else ACESCG, linearized=not ldr)
    except Exception as e:  # noqa: BLE001 - no PyOpenColorIO, unknown display/view, no matte_paint role...
        log.warning("%s colors kept as recorded: can't build the OCIO transform: %s", kind, e)
        return None
    return display, view
