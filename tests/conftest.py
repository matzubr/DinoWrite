"""Stubs for Houdini-only modules (hou, pxr, PySide2), so pure helpers can be tested outside Houdini."""
import importlib.util
import sys
import types
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]


class HouError(Exception):
    pass


def _hscript_expression(value):
    # Minimal fake: supports "$F+N" with $F == 1001
    if value.startswith("$F+"):
        return 1001.0 + float(value[3:])
    raise HouError(f"Bad expression: {value}")


def _install_stubs():
    hou = types.ModuleType("hou")
    hou.Error = HouError
    hou.hscriptExpression = _hscript_expression
    hou.getenv = lambda name, default=None: default
    hou.text = types.SimpleNamespace(expandString=lambda s: s)
    sys.modules["hou"] = hou

    pxr = types.ModuleType("pxr")
    pxr.Sdf = pxr.Usd = None
    sys.modules["pxr"] = pxr

    # Star imports pull only names from __all__, so expose dummy classes used in annotations
    qt_names = {"QtWidgets": ["QWidget"], "QtGui": ["QIcon"], "QtCore": ["Qt"]}
    sys.modules["PySide2"] = types.ModuleType("PySide2")
    for name, classes in qt_names.items():
        module = types.ModuleType(f"PySide2.{name}")
        for cls in classes:
            setattr(module, cls, type(cls, (), {}))
        module.__all__ = classes
        sys.modules[f"PySide2.{name}"] = module


@pytest.fixture(scope="session")
def utils():
    _install_stubs()
    spec = importlib.util.spec_from_file_location("dinowrite_utils", ROOT / "utils" / "utils.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module
