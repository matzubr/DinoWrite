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
                                                      ocio_defaultView=lambda: "Un-tone-mapped",
                                                      ocio_views=lambda d: ("Un-tone-mapped",)), raising=False)
    window = DinoWrite.show({})
    monkeypatch.setattr(window.hou_viewport, "getPaneTab",
                        lambda: SimpleNamespace(usingOCIO=lambda: False, qtScreenGeometry=lambda: 1 / 0))
    window.resx.setText("20000")
    window.resy.setText("10000")
    window.convertvideo.setChecked(True)
    window.updateStatus()
    text = window.statusline.text() + " " + window.videoline.text()
    assert "20000×10000 in separate viewer" in text
    assert "Video: OCIO Un-tone-mapped" in text
    assert "sRGB - Display" in window.videoline.toolTip()

    window.resx.setText("640")
    window.resy.setText("480")
    window.convertvideo.setChecked(False)
    window.updateStatus()
    assert window.statusline.text() == "Record: 640×480 in viewport"
    assert window.videoline.text() == "Video: off"
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
    """Long OCIO view name: text is elided, window/layout keep their size, dino doesn't move"""
    from types import SimpleNamespace

    import DinoWrite

    long_view = "ACES 1.0 - SDR Video (Rec.1886 Rec.709 - Display, really long view name)"
    monkeypatch.setattr(hou, "Color", SimpleNamespace(ocio_defaultDisplay=lambda: "Rec.1886 Rec.709 - Display",
                                                      ocio_defaultView=lambda: long_view,
                                                      ocio_views=lambda d: (long_view,)), raising=False)
    window = DinoWrite.show({})
    monkeypatch.setattr(window.hou_viewport, "getPaneTab",
                        lambda: SimpleNamespace(usingOCIO=lambda: False, qtScreenGeometry=lambda: 1 / 0))
    window.convertvideo.setChecked(False)
    window.updateStatus()
    window.layout().activate()
    dino_before = window.seqname.parentWidget().mapTo(window, window.seqname.geometry().topRight())
    width_before = window.videoline.width()

    window.convertvideo.setChecked(True)
    window.updateStatus()
    window.layout().activate()

    assert window.width() == window.minimumWidth()
    assert window.videoline.width() == width_before
    assert window.seqname.parentWidget().mapTo(window, window.seqname.geometry().topRight()) == dino_before
    assert window.videoline.text() == f"Video: OCIO {long_view}"
    assert window.videoline.toolTip().startswith("Video: OCIO")  # full text in tooltip when elided
    for label in (window.statusline, window.videoline):
        assert label.geometry().right() <= window.width()
    window.close()
