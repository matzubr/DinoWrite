"""Flipbook passport: where a flipbook came from, written into the EXR headers and the video metadata.

Collected on the main thread (needs hou) right after recording. In Nuke: Read node -> Metadata tab
(exr/dinowrite/hip, ...); video: ffprobe / any player's media info.
"""
import datetime
import getpass
import platform

import hou

from .log import log

PREFIX = "dinowrite"


def _safe(getter, default=""):
    try:
        value = getter()
    except Exception as e:  # noqa: BLE001 - a passport field must never break writing
        log.warning("Flipbook passport: %s", e)
        return default
    return default if value is None else value


def collect(camera: str = "", frame_range: tuple = (), resolution: tuple = (), display_view: tuple = (),
            audio: str = "") -> dict:
    """{key: text} in a stable order. Empty values are left out."""
    from .. import __version__

    passport = {
        "hip": _safe(hou.hipFile.path),
        "camera": camera,
        "frame_range": f"{frame_range[0]}-{frame_range[1]}" if frame_range else "",
        "resolution": f"{resolution[0]}x{resolution[1]}" if resolution else "",
        "fps": _safe(lambda: f"{hou.fps():g}"),
        "ocio_view": " / ".join(v for v in display_view if v),
        "audio": audio,
        "user": _safe(getpass.getuser),
        "host": _safe(platform.node),
        "date": datetime.datetime.now().isoformat(timespec="seconds"),
        "houdini": _safe(hou.applicationVersionString),
        "dinowrite": __version__,
    }
    return {key: str(value) for key, value in passport.items() if value not in ("", None)}


def summary(passport: dict) -> str:
    """One line for the video comment: hip · camera · range"""
    keys = ("hip", "camera", "frame_range", "ocio_view")
    return " | ".join(f"{key}: {passport[key]}" for key in keys if key in passport)


def oiiotoolArgs(passport: dict) -> list:
    """--attrib for every field (exr/dinowrite:hip ...) plus the standard EXR owner/date/comment"""
    args = []
    for key, value in passport.items():
        args += ["--attrib", f"{PREFIX}:{key}", value]
    if "user" in passport:
        args += ["--attrib", "Artist", passport["user"]]
    if "hip" in passport:
        args += ["--attrib", "ImageDescription", summary(passport)]
    return args


def ffmpegArgs(passport: dict, title: str = "") -> list:
    """-metadata for the video. Custom keys are kept in mov/mp4 with -movflags use_metadata_tags."""
    args = ["-movflags", "use_metadata_tags"]
    standard = {"title": title, "artist": passport.get("user", ""), "comment": summary(passport),
                "date": passport.get("date", ""), "encoder": f"DinoWrite {passport.get('dinowrite', '')}".strip()}
    for key, value in standard.items():
        if value:
            args += ["-metadata", f"{key}={value}"]
    for key, value in passport.items():
        args += ["-metadata", f"{PREFIX}_{key}={value}"]
    return args
