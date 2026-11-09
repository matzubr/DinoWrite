"""Build the real window offscreen with PySide6 (Qt6, as in Houdini 21) to catch Qt API breakage."""
import pytest

QtWidgets = pytest.importorskip("PySide6.QtWidgets")


def test_main_window_builds_with_qt6(houdini):
    import DinoWrite

    window = DinoWrite.show({})
    assert window.isVisible()
    assert window.parent() is houdini
    assert window.filename.text() == "flipbook"
    assert window.ramusage.text().startswith("Memory: RAM ")

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
    assert window.ramusage.text().startswith("Memory: RAM - · Disk -")
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

    window = DinoWrite.show({})
    monkeypatch.setattr(window.hou_viewport, "getPaneTab", lambda: SimpleNamespace(qtScreenGeometry=lambda: 1 / 0))
    window.resx.setText("20000")
    window.resy.setText("10000")
    window.convertvideo.setChecked(True)
    window.updateStatus()
    text = window.statusline.text() + " " + window.videoline.text()
    assert "20000×10000 in separate viewer" in text
    assert "Video: sRGB (like MPlay)" in text
    assert "MPlay" in window.videoline.toolTip()

    window.resx.setText("640")
    window.resy.setText("480")
    window.convertvideo.setChecked(False)
    window.updateStatus()
    assert window.statusline.text() == "Record: 640×480 in viewport"
    assert window.videoline.text() == "Video: off · EXR: ACEScg, DWAA"
    window.settings["advanced"]["exr_acescg"] = False
    window.updateStatus()
    assert window.videoline.text() == "Video: off · EXR: DWAA"
    window.close()


def test_window_has_smooth_transparent_corners(houdini):
    import DinoWrite

    window = DinoWrite.show({})
    image = window.grab().toImage()
    assert image.pixelColor(0, 0).alpha() == 0, "corner must be transparent"
    assert image.pixelColor(image.width() // 2, image.height() - 2).alpha() == 255
    # antialiased edge: some partially transparent pixels along the corner arc
    arc = [image.pixelColor(x, 2).alpha() for x in range(0, 15)]
    assert any(0 < a < 255 for a in arc)
    window.close()


def test_long_video_status_does_not_widen_window(houdini, hou, monkeypatch):
    """Long status text is elided: window/layout keep their size, dino doesn't move"""
    from types import SimpleNamespace

    import DinoWrite

    window = DinoWrite.show({})
    monkeypatch.setattr(window.hou_viewport, "getPaneTab", lambda: SimpleNamespace(qtScreenGeometry=lambda: 1 / 0))
    window.convertvideo.setChecked(True)
    window.updateStatus()
    window.layout().activate()
    dino_before = window.seqname.parentWidget().mapTo(window, window.seqname.geometry().topRight())
    width_before = window.videoline.width()

    long_text = "Video: " + "really long status " * 10
    window.videoline.setText(long_text)
    window.layout().activate()

    assert window.width() == window.minimumWidth()
    assert window.videoline.width() == width_before
    assert window.seqname.parentWidget().mapTo(window, window.seqname.geometry().topRight()) == dino_before
    assert window.videoline.toolTip().startswith(long_text.strip())  # full text in tooltip when elided
    for label in (window.statusline, window.videoline):
        assert label.geometry().right() <= window.width()
    window.close()


def test_solaris_greys_out_background_options(houdini, monkeypatch):
    import DinoWrite
    from DinoWrite.core import viewport

    monkeypatch.setattr(viewport.HouViewport, "isLop", lambda self: True)
    window = DinoWrite.show({})
    for checkbox in (window.blackbackground, window.offbackgroundimage):
        assert not checkbox.isEnabled()
    data = window.collectData()
    assert set(window.solaris_kept) == {"blackbg", "bgimage"}
    assert data["blackbg"] == window.solaris_kept["blackbg"]  # the saved OBJ choice isn't overwritten
    window.close()


def test_file_format_shows_colorspace_and_keeps_extension(houdini):
    import DinoWrite

    window = DinoWrite.show({})
    window.convertvideo.setChecked(False)
    texts = [window.fileformat.itemText(i) for i in range(window.fileformat.count())]
    assert all("(" in text for text in texts), texts
    window.fileformat.setCurrentIndex(window.fileformat.findData("png"))
    assert window.fileFormat() == "png" and window.collectData()["fileformat"] == "png"
    assert "Nuke" in window.fileformat.toolTip()
    window.close()
