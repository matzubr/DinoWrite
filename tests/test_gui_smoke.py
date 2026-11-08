"""Build the real window offscreen with PySide6 (Qt6, as in Houdini 21) to catch Qt API breakage."""
import pytest

QtWidgets = pytest.importorskip("PySide6.QtWidgets")


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


def test_invalid_name_blocks_write(houdini):
    import DinoWrite

    window = DinoWrite.show({})
    window.filename.setText("my shot")
    assert not window.writebutton.isEnabled()
    assert "space" in window.statusline.text()
    window.filename.setText("my_shot")
    assert window.writebutton.isEnabled()
    window.close()


def test_status_line_shows_record_and_video(houdini, hou, monkeypatch):
    from types import SimpleNamespace

    import DinoWrite

    monkeypatch.setattr(hou, "Color", SimpleNamespace(ocio_defaultDisplay=lambda: "sRGB - Display",
                                                      ocio_defaultView=lambda: "Un-tone-mapped"), raising=False)
    window = DinoWrite.show({})
    monkeypatch.setattr(window.hou_viewport, "getPaneTab",
                        lambda: SimpleNamespace(usingOCIO=lambda: False, qtScreenGeometry=lambda: 1 / 0))
    window.resx.setText("20000")
    window.resy.setText("10000")
    window.convertvideo.setChecked(True)
    window.updateStatus()
    text = window.statusline.text()
    assert "20000&times;10000 in separate viewer" in text
    assert "Video: OCIO Un-tone-mapped" in text
    assert "sRGB - Display" in window.statusline.toolTip()

    window.resx.setText("640")
    window.resy.setText("480")
    window.convertvideo.setChecked(False)
    window.updateStatus()
    assert window.statusline.text() == "Record: 640&times;480 in viewport"
    window.close()
