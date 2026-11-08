"""Build the real window offscreen with PySide6 (Qt6, as in Houdini 21) to catch Qt API breakage."""
import pytest

QtWidgets = pytest.importorskip("PySide6.QtWidgets")


@pytest.fixture
def qapp():
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

    main_window = QtWidgets.QWidget()
    monkeypatch.setattr(hou, "text", type("text", (), {"expandString": staticmethod(expand)}), raising=False)
    monkeypatch.setattr(hou, "qt", type("qt", (), {"mainWindow": staticmethod(lambda: main_window)}), raising=False)
    yield main_window
    main_window.deleteLater()


def test_main_window_builds_with_qt6(houdini):
    import DinoWrite

    window = DinoWrite.show({})
    assert window.isVisible()
    assert window.parent() is houdini
    assert window.filename.text() == "flipbook"
    assert window.ramusage.text().startswith("RAM Usage:")

    # second call focuses existing window instead of opening a duplicate
    DinoWrite.show({})
    visible = [w for w in houdini.children() if isinstance(w, QtWidgets.QWidget) and w.isVisible()]
    assert visible == [window]
    window.close()


def test_main_window_survives_bad_field_values(houdini):
    import DinoWrite

    window = DinoWrite.show({})
    window.resx.setText("")
    window.updateResolutions()
    window.framestart.setText("$BAD")
    window.updateRamUsage()
    assert window.ramusage.text() == "RAM Usage: -"
    window.close()


def test_legacy_shelf_import_still_works(houdini):
    from DinoWrite import ui

    window = ui.DinoWriter({})
    assert window.isVisible()
    window.close()
