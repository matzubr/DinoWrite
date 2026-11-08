"""DinoWrite - write Houdini flipbooks to disk easily.

Shelf tool:
    import DinoWrite
    DinoWrite.show(kwargs)

While developing, pick up code changes without restarting Houdini:
    DinoWrite.show(kwargs, reload=True)
"""
import importlib
import sys
import time
from pathlib import Path

__version__ = "1.4.0"

_PACKAGE_DIR = Path(__file__).resolve().parent
_loaded_at = time.time()

# Dependency order: modules are reloaded top to bottom
_SUBMODULES = (
    "core.log",
    "core.helpers",
    "core.process",
    "core.ffmpeg",
    "core.viewport",
    "core.conversion",
    "config",
    "gui.qt",
    "gui.resources",
    "gui.theme",
    "gui.widgets",
    "gui.frameless",
    "gui.settings_dialog",
    "gui.job_window",
    "flipbook",
    "main",
)


def reload_modules():
    """Reload already imported DinoWrite submodules (for development)."""
    global _loaded_at
    for name in _SUBMODULES:
        module = sys.modules.get(f"{__name__}.{name}")
        if module is not None:
            importlib.reload(module)
    _loaded_at = time.time()


def _filesChangedSinceLoad() -> bool:
    """Tool files updated on disk (git pull, copy) while Houdini keeps the old modules imported"""
    newest = max((f.stat().st_mtime for f in _PACKAGE_DIR.rglob("*.py") if ".venv" not in f.parts), default=0)
    return newest > _loaded_at


def show(kwargs=None, reload=False):
    """Open DinoWrite window (or focus the already opened one).

    Code updated on disk is reloaded automatically: Python keeps imported modules, so without this
    an updated tool keeps running the old code until Houdini restarts.
    """
    if reload or _filesChangedSinceLoad():
        reload_modules()
    from .core.log import log
    from .main import DinoWriter

    log.info("DinoWrite %s from %s", __version__, _PACKAGE_DIR.as_posix())
    return DinoWriter(kwargs or {})

