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
    hou.hscriptExpression = _hscript_expression
    hou.getenv = lambda name, default=None: default
    hou.text = types.SimpleNamespace(expandString=lambda s: s)
    hou.__getattr__ = lambda name: MagicMock(name=f"hou.{name}")
    return hou


sys.modules["hou"] = _make_hou()


@pytest.fixture
def hou():
    return sys.modules["hou"]
