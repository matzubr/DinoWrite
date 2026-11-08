"""Test setup: DinoWrite is imported as a package with a stubbed `hou` module.

Unknown hou attributes resolve to MagicMock, so GUI code can be constructed offscreen.
"""
import os
import sys
import types
from pathlib import Path
from unittest.mock import MagicMock

import pytest

ROOT = Path(__file__).resolve().parents[1]
assert ROOT.name == "DinoWrite", "tests expect the repo folder to be named DinoWrite (the package name)"
sys.path.insert(0, ROOT.parent.as_posix())

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")


class HouError(Exception):
    pass


def _hscript_expression(value):
    # Minimal fake: supports "$F+N" with $F == 1001
    if value.startswith("$F+"):
        return 1001.0 + float(value[3:])
    raise HouError(f"Bad expression: {value}")


def _make_hou():
    hou = types.ModuleType("hou")
    hou.Error = HouError
    hou.OperationInterrupted = type("OperationInterrupted", (Exception,), {})
    hou.hscriptExpression = _hscript_expression
    hou.getenv = lambda name, default=None: default
    hou.text = types.SimpleNamespace(expandString=lambda s: s)
    hou.__getattr__ = lambda name: MagicMock(name=f"hou.{name}")
    return hou


sys.modules["hou"] = _make_hou()


@pytest.fixture
def hou():
    return sys.modules["hou"]


@pytest.fixture
def qapp():
    QtWidgets = pytest.importorskip("PySide6.QtWidgets")
    return QtWidgets.QApplication.instance() or QtWidgets.QApplication([])


@pytest.fixture
def houdini(hou, tmp_path, monkeypatch, qapp):
    """Fake Houdini session: $HIP/$TEMP in tmp_path, a real QWidget as Houdini main window."""
    hip = tmp_path / "hip"
    (tmp_path / "preview").mkdir()
    hip.mkdir()
    variables = {"$HIP": hip.as_posix(), "$TEMP": (tmp_path / "temp").as_posix(),
                 "$HOUDINI_TEMP_DIR": (tmp_path / "temp").as_posix()}

    def expand(text):
        for key, value in variables.items():
            text = text.replace(key, value)
        return text

    from PySide6 import QtWidgets

    main_window = QtWidgets.QWidget()
    monkeypatch.setenv("DINOWRITE_SETTINGS", (tmp_path / "user_settings.json").as_posix())
    monkeypatch.setattr(hou, "text", type("text", (), {"expandString": staticmethod(expand)}), raising=False)
    monkeypatch.setattr(hou, "qt", type("qt", (), {"mainWindow": staticmethod(lambda: main_window)}), raising=False)
    yield main_window
    main_window.deleteLater()


def waitUntil(condition, timeout: float = 2.0) -> bool:
    """Process Qt events until condition() is true (animations finish asynchronously)"""
    import time

    from PySide6.QtWidgets import QApplication

    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        QApplication.processEvents()
        if condition():
            return True
        time.sleep(0.01)
    return condition()
