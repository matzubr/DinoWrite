"""Qt compatibility: Houdini 21+ ships PySide6 (Qt6), older versions PySide2 (Qt5).

Import Qt names from here instead of PySide directly:
    from .qt import *
"""
try:
    from PySide6.QtCore import *  # noqa: F401,F403
    from PySide6.QtGui import *  # noqa: F401,F403
    from PySide6.QtWidgets import *  # noqa: F401,F403
except ImportError:
    from PySide2.QtCore import *  # noqa: F401,F403
    from PySide2.QtGui import *  # noqa: F401,F403
    from PySide2.QtWidgets import *  # noqa: F401,F403
