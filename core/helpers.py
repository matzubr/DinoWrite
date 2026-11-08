"""Pure helpers: versioning, frame/number parsing. No Qt here, only hou."""
import re
from pathlib import Path

import hou

VERSION_FOLDER_PATTERN = re.compile(r"^v(\d+)$")
VERSION_MIN_PADDING = 3

# Flipbook name becomes a folder and a file name: keep it portable
NAME_ALLOWED = re.compile(r"[A-Za-z0-9_\-.]")


def nameProblem(name: str) -> str:
    """Why the flipbook name can't be used, empty string if it's fine"""
    if not name.strip():
        return "Name is empty"
    bad = sorted({c for c in name if not NAME_ALLOWED.fullmatch(c)})
    if bad:
        shown = " ".join("space" if c == " " else c for c in bad)
        return f"Not allowed in name: {shown}"
    if name.startswith(".") or name.endswith("."):
        return "Name can't start or end with a dot"
    return ""


def nextVersion(folder: Path) -> str:
    """Get next version string (like 'v004') based on 'vNNN' subfolders in folder.

    Folders that don't match 'vNNN' pattern are ignored.
    Versions compared as numbers, so v1000 is newer than v999.
    """
    last_digit = 0
    padding = VERSION_MIN_PADDING
    if folder.exists():
        for x in folder.iterdir():
            match = VERSION_FOLDER_PATTERN.match(x.name)
            if x.is_dir() and match:
                digit = int(match[1])
                if digit >= last_digit:
                    last_digit = digit
                    padding = max(padding, len(match[1]))
    return f"v{str(last_digit+1).zfill(padding)}"

def evalFrame(value: str):
    """Evaluate frame value from line edit: plain number or hscript expression like '$F+10'.

    Returns:
        int | float | None: Frame number or None if value can't be evaluated
    """
    value = str(value).strip()
    if not value:
        return None
    try:
        return int(value)
    except ValueError:
        pass
    try:
        result = hou.hscriptExpression(value)
        return int(result) if float(result).is_integer() else float(result)
    except (hou.Error, TypeError, ValueError):
        return None

def toInt(value: str, default=None):
    """Safe int conversion of line edit text"""
    try:
        return int(value)
    except (TypeError, ValueError):
        return default

def ffmpegFps(fps: float) -> str:
    """Format fps for ffmpeg, keeping fractional (NTSC) frame rates exact"""
    if float(fps).is_integer():
        return str(int(fps))
    ntsc = round(fps * 1.001)
    if abs(ntsc * 1000 / 1001 - fps) < 0.001:
        return f"{ntsc*1000}/1001"
    return f"{fps:.3f}"

def flipbookVersion(fb_folder_template: str, flipbook_name: str) -> str:
    """Next version for flipbook name, using 'paths.fb_folder' template from settings"""
    if not flipbook_name:
        return "v001"
    fb_folder = Path(hou.text.expandString(fb_folder_template).format(name=flipbook_name)).resolve()
    return nextVersion(fb_folder)
