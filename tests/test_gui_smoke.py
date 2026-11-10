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
    window.setInfoExpanded(True, animate=False)
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


def test_info_details_slide_out_and_are_remembered(houdini):
    import DinoWrite
    from conftest import waitUntil

    window = DinoWrite.show({})
    assert not window.info_expanded and not window.info_details.isVisible(), "closed by default"
    closed_height = window.height()
    window.info_toggle.click()
    assert waitUntil(lambda: window.info_details.isVisible() and window.height() > closed_height + 40)
    assert window.collectData()["infoexpanded"] is True
    window.close()

    window = DinoWrite.show({})
    assert window.info_expanded, "remembered"
    window.setInfoExpanded(False, animate=False)
    window.close()


def test_closed_details_show_warnings_on_the_arrow(houdini):
    import DinoWrite

    window = DinoWrite.show({})
    window.setInfoExpanded(False, animate=False)
    window.setInfoWarning("disk", "The flipbook may not fit on the disk", "#ff0000")
    assert "may not fit" in window.info_toggle.toolTip()
    window.setInfoWarning("disk")
    assert "may not fit" not in window.info_toggle.toolTip()
    window.close()


def test_long_sequence_name_is_shortened_in_the_middle(houdini):
    import DinoWrite

    window = DinoWrite.show({})
    window.filename.setText("a_really_long_shot_name_that_does_not_fit_" * 2)
    window.updateColorfulLabel()
    window.layout().activate()
    shown = window.seqname.text()
    assert "…" in shown, "the name is shortened"
    assert window.seqtail.fullText() == ".$F4.exr" and window.versionbox.label.text() == "v001", \
        "version, frames, extension stay visible"
    assert window.seqname.toolTip().endswith(".exr") and window.sequenceText().endswith(".exr")
    assert not window.sequenceText().endswith("."), "no dot after the extension"
    assert window.seqtail.geometry().right() < window.dino_paint.geometry().left()
    assert window.dino_paint.geometry().right() < window.info_toggle.geometry().left()
    window.close()


def test_menus_preview_what_they_set(houdini, hou, monkeypatch):
    import DinoWrite

    window = DinoWrite.show({})
    monkeypatch.setattr(window.hou_viewport, "cameraResolution", lambda: (3840, 2160))
    monkeypatch.setattr(window.hou_viewport, "viewportSize", lambda: (1712, 963), raising=False)
    monkeypatch.setattr(hou, "hscriptExpression", lambda v: {"$FSTART": 1001, "$FEND": 1240}.get(v, 1), raising=False)
    window.resx.setText("1920")
    window.resy.setText("1080")
    window.res_menu.relabel()
    texts = {a.data(): a.text().strip("‎") for a in window.res_menu.menu.actions() if a.data()}
    assert texts["Camera Resolution"] == "Camera Resolution  (3840×2160)"
    assert texts["Viewport Resolution"] == "Viewport Resolution  (1712×963)"
    assert texts["1/2"] == "1/2  (960×540)" and texts["×3"] == "×3  (5760×3240)"
    assert window.res_menu.menu.items == {"1/2", "2/3", "×2", "×3"}, "one knife dino next to all the scales"

    by_item = {a.data(): a for a in window.res_menu.menu.actions() if a.data()}
    by_item["×2"].trigger()
    assert (window.resx.text(), window.resy.text()) == ("3840", "2160")
    by_item["Viewport Resolution"].trigger()
    assert (window.resx.text(), window.resy.text()) == ("1712", "963")

    window.frame_menu.relabel()
    frames = {a.data(): a.text().strip("‎") for a in window.frame_menu.menu.actions() if a.data()}
    assert frames["Global Frame Range"] == "Global Frame Range  (1001–1240)  ✓", "the fields hold $FSTART $FEND"
    window.close()


def test_resolution_menu_marks_the_current_size_and_keeps_video_sizes_even(houdini, monkeypatch):
    import DinoWrite

    window = DinoWrite.show({})
    monkeypatch.setattr(window.hou_viewport, "cameraResolution", lambda: (2251, 1084))
    window.resx.setText("2048")
    window.resy.setText("1080")
    window.convertvideo.setChecked(False)
    window.res_menu.relabel()
    actions = window.res_menu.menu.actions()
    assert "Scale the current size" in [a.text() for a in actions if not a.isEnabled()], "scales get a title"
    texts = {a.data(): a.text().strip("‎") for a in actions if a.data()}
    assert texts["2/3"] == "2/3  (1366×720)", "scales are even"
    assert texts["2048 1080"] == "2048×1080  ✓" and "✓" not in texts["1/2"], "the size set now is ticked"
    assert texts["Camera Resolution"] == "Camera Resolution  (2251×1084)", "pictures keep the exact size"

    window.convertvideo.setChecked(True)
    window.res_menu.relabel()
    by_item = {a.data(): a for a in window.res_menu.menu.actions() if a.data()}
    assert by_item["Camera Resolution"].text().strip("‎") == "Camera Resolution  (≈2250×1084)"
    assert "even" in by_item["Camera Resolution"].toolTip()
    by_item["Camera Resolution"].trigger()
    assert (window.resx.text(), window.resy.text()) == ("2250", "1084")

    window.resx.setText("2251")
    window.updateStatus()
    assert "odd size cropped" in window.videoline.text()
    assert "odd size" in window.info_toggle.toolTip() or window.info_expanded
    window.close()


def test_convert_to_video_offers_video_formats(houdini):
    import DinoWrite

    window = DinoWrite.show({})
    window.convertvideo.setChecked(False)
    window.fileformat.setCurrentIndex(window.fileformat.findData("png"))
    window.convertvideo.setChecked(True)
    assert window.fileformat.isEnabled()
    assert [window.fileformat.itemData(i) for i in range(window.fileformat.count())] == ["mov", "mp4"]
    window.fileformat.setCurrentIndex(window.fileformat.findData("mp4"))
    data = window.collectData()
    assert (data["fileformat"], data["videoext"], data["picformat"]) == ("exr", "mp4", "png"), "video records EXR"
    assert "sRGB" in window.fileformat.currentText()
    window.convertvideo.setChecked(False)
    assert window.fileFormat() == "png", "the picture choice comes back"
    window.saveState()  # as on WRITE
    window.close()

    window = DinoWrite.show({})
    window.convertvideo.setChecked(True)
    assert window.fileformat.currentData() == "mp4", "remembered"
    window.close()


def test_version_steps_and_warns_about_overwriting(houdini, hou, monkeypatch, tmp_path):
    import DinoWrite

    window = DinoWrite.show({})
    window.paths["fb_folder"] = (tmp_path / "{name}").as_posix()
    monkeypatch.setattr(hou, "text", type("T", (), {"expandString": staticmethod(lambda s: s)}), raising=False)
    for version in ("v001", "v002"):
        (tmp_path / "shot" / version).mkdir(parents=True)
    (tmp_path / "shot" / "v002" / "shot.v002.1001.exr").write_text("x")
    window.filename.setText("shot")
    window.updateStatus()
    assert window.versionbox.label.text() == "v003" and not window.versionbox.plus.isEnabled()
    window.versionbox.minus.click()
    assert window.versionbox.label.text() == "v002" and window.collectData()["version"] == "v002"
    assert "v002 exists (1 file): will be overwritten" in window.statusline.text()
    assert "v002" in window.sequenceText()
    window.versionbox.plus.click()
    assert window.collectData()["version"] == "", "back at the next free one: automatic"
    window.versionbox.minus.click()
    window.filename.setText("other")
    assert window.collectData()["version"] == "", "another name starts automatic"
    window.close()


def test_sequence_hover_shows_the_full_path(houdini, hou, monkeypatch, tmp_path):
    import DinoWrite

    monkeypatch.setattr(hou, "text", type("T", (), {"expandString": staticmethod(
        lambda s: s.replace("$HIP", tmp_path.as_posix()))}), raising=False)
    window = DinoWrite.show({})
    window.paths["fb_folder"] = "$HIP/preview/{name}"
    window.filename.setText("shot")
    window.updateColorfulLabel()
    assert window.seqname.toolTip() == (tmp_path / "preview/shot/v001/shot.v001.$F4.exr").resolve().as_posix()
    window.close()


def test_video_on_shows_the_video_and_its_frames_in_grey(houdini, hou, monkeypatch, tmp_path):
    import DinoWrite

    monkeypatch.setattr(hou, "text", type("T", (), {"expandString": staticmethod(
        lambda s: s.replace("$HIP", tmp_path.as_posix()))}), raising=False)
    window = DinoWrite.show({})
    window.paths["fb_folder"] = "$HIP/preview/{name}"
    window.filename.setText("shot")
    window.convertvideo.setChecked(True)
    window.fileformat.setCurrentIndex(window.fileformat.findData("mp4"))
    assert window.sequenceText() == "Video: shot.v001.mp4"
    assert window.seqname.toolTip().endswith((tmp_path / "preview/shot/v001/shot.v001.mp4").resolve().as_posix())
    assert not window.framesline.isHidden() and window.framesline.text().startswith("Frames: shot.v001.$F4.exr")
    window.convertvideo.setChecked(False)
    assert window.sequenceText().startswith("Sequence: shot.v001.$F4.") and window.framesline.isHidden()
    window.close()


def test_window_width_drags_from_the_edge_and_is_remembered(houdini):
    import DinoWrite
    from DinoWrite import main
    from DinoWrite.gui.qt import QPoint, QPointF, Qt
    from PySide6.QtTest import QTest

    window = DinoWrite.show({})
    assert window.width() == main.WINDOW_WIDTH
    right = QPoint(window.width() - 3, window.height() // 2)
    QTest.mousePress(window, Qt.LeftButton, Qt.NoModifier, right)
    from PySide6.QtGui import QMouseEvent
    from PySide6.QtCore import QEvent
    target = window.mapToGlobal(right) + QPoint(120, 0)
    move = QMouseEvent(QEvent.MouseMove, QPointF(right + QPoint(120, 0)), QPointF(target),
                       Qt.LeftButton, Qt.LeftButton, Qt.NoModifier)
    window.mouseMoveEvent(move)
    QTest.mouseRelease(window, Qt.LeftButton, Qt.NoModifier, right + QPoint(120, 0))
    assert window.width() == main.WINDOW_WIDTH + 120
    window.close()

    reopened = DinoWrite.show({})
    assert reopened.width() == main.WINDOW_WIDTH + 120
    reopened.setWidthClamped(10)
    assert reopened.width() == main.WINDOW_WIDTH, "never narrower than the default"
    reopened.close()


def test_version_is_picked_inside_the_output_name(houdini):
    import DinoWrite

    window = DinoWrite.show({})
    window.filename.setText("shot")
    window.updateColorfulLabel()
    assert window.seqname.fullText() == "Sequence: shot."
    assert window.versionbox.label.text() == "v001" and window.seqtail.fullText().startswith(".$F4.")
    assert window.filename.parentWidget() is not window.versionbox.parentWidget(), "not next to the name field"
    window.paths["fb_name"] = "{name}_{version}.$F4.{fileformat}"  # version inside a part: stepper at the end
    window.updateColorfulLabel()
    assert window.seqtail.fullText() == "" and not window.seqname.fullText().endswith(".")
    window.close()
