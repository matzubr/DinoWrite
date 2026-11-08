"""Backward compatibility for old shelf tools:

    from DinoWrite import ui
    ui.DinoWriter(kwargs)

New code should use `import DinoWrite; DinoWrite.show(kwargs)`.
"""
from .main import DinoWriter  # noqa: F401
