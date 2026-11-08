"""DinoWrite - write Houdini flipbooks to disk easily.

Shelf tool:
    import DinoWrite
    DinoWrite.show(kwargs)

While developing, pick up code changes without restarting Houdini:
    DinoWrite.show(kwargs, reload=True)
"""
import importlib
import sys

__version__ = "1.2.5"

# Dependency order: modules are reloaded top to bottom
_SUBMODULES = (
    "core.log",
    "core.helpers",
    "core.process",
    "core.ffmpeg",
    "core.viewport",
    "core.ocio",
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
    for name in _SUBMODULES:
        module = sys.modules.get(f"{__name__}.{name}")
        if module is not None:
            importlib.reload(module)


def show(kwargs=None, reload=False):
    """Open DinoWrite window (or focus the already opened one)."""
    if reload:
        reload_modules()
    from .main import DinoWriter

    return DinoWriter(kwargs or {})
