"""Settings dialog offscreen (PySide6)"""
import json
from types import SimpleNamespace

import pytest

pytest.importorskip("PySide6.QtWidgets")


@pytest.fixture
def ocio_config(monkeypatch, hou):
    color = SimpleNamespace(
        ocio_activeDisplays=lambda: ("sRGB - Display", "Rec.1886 Rec.709 - Display"),
        ocio_views=lambda display: ("ACES 1.0 - SDR Video", "Un-tone-mapped") if display.startswith("sRGB") else ("Raw",),
        ocio_roles=lambda: ("scene_linear", "rendering"),
        ocio_spaces=lambda: ("ACEScg", "Linear Rec.709 (sRGB)"),
        ocio_configPath=lambda: "/hfs/packages/ocio/config.ocio",
        ocio_defaultDisplay=lambda: "sRGB - Display",
        ocio_defaultView=lambda: "ACES 1.0 - SDR Video",
    )
    monkeypatch.setattr(hou, "Color", color, raising=False)


@pytest.fixture
def dialog(houdini, ocio_config):
    from DinoWrite.gui.settings_dialog import SettingsDialog

    dlg = SettingsDialog()
    yield dlg
    dlg.deleteLater()


def test_unchanged_dialog_collects_current_settings(dialog):
    from DinoWrite import config

    settings, errors = dialog.collect()
    assert errors == []
    assert settings == config.load()


def test_ocio_lists_come_from_houdini_config(dialog):
    displays = [dialog.ocio_display.itemText(i) for i in range(dialog.ocio_display.count())]
    assert displays == ["Like MPlay (config default)", "Like the viewer", "sRGB - Display",
                        "Rec.1886 Rec.709 - Display"]
    assert dialog.ocio_display.currentText() == "Like MPlay (config default)"
    views = [dialog.ocio_view.itemText(i) for i in range(dialog.ocio_view.count())]
    assert views == ["Default view", "ACES 1.0 - SDR Video", "Un-tone-mapped"], "views of the MPlay default display"
    dialog.ocio_display.setCurrentText("Rec.1886 Rec.709 - Display")
    views = [dialog.ocio_view.itemText(i) for i in range(dialog.ocio_view.count())]
    assert views == ["Default view", "Raw"]


def test_viewer_source_is_saved(dialog, tmp_path):
    dialog.ocio_display.setCurrentText("Like the viewer")
    dialog.save()
    stored = json.loads((tmp_path / "user_settings.json").read_text())
    assert stored == {"advanced": {"ocio_source": "viewer"}}


def test_ocio_fields_disabled_for_non_ocio_transform(dialog):
    dialog.color_transform.setCurrentIndex(dialog.color_transform.findData("srgb"))
    assert not dialog.ocio_display.isEnabled()
    dialog.color_transform.setCurrentIndex(dialog.color_transform.findData("ocio"))
    assert dialog.ocio_display.isEnabled()


def test_validation_errors(dialog):
    dialog.fb_name.setText("{name}.{version}.{fileformat}")
    dialog.resolutions.setPlainText("1920 1080\nwide")
    dialog.frame_ranges.setPlainText("Broken range")
    dialog.ffmpeg_cmd.setPlainText("ffmpeg\n-i {input}")
    _, errors = dialog.collect()
    assert len(errors) == 4


def test_save_writes_only_changes(dialog, tmp_path):
    dialog.ocio_display.setCurrentText("sRGB - Display")
    dialog.ocio_view.setCurrentText("Un-tone-mapped")
    dialog.resolutions.setPlainText("4096   2160\n1920 1080")
    dialog.frame_ranges.setPlainText("Shot = 1001 1100")
    dialog.save()

    stored = json.loads((tmp_path / "user_settings.json").read_text())
    assert stored == {
        "advanced": {"ocio_display": "sRGB - Display", "ocio_view": "Un-tone-mapped"},
        "custom_resolution": ["4096 2160", "1920 1080"],
        "custom_framerange": {"Shot": "1001 1100"},
    }


def test_gear_button_reopens_window_with_new_settings(houdini, ocio_config, monkeypatch, tmp_path):
    import DinoWrite
    from DinoWrite import main
    from DinoWrite.gui.qt import QDialog

    window = DinoWrite.show({})
    monkeypatch.setattr(window.hou_viewport, "cameraPixelAspect", lambda: 1.0)
    window.filename.setText("my_shot")

    def fake_exec(dialog):
        dialog.resolutions.setPlainText("777 333")
        dialog.save()
        return QDialog.Accepted

    monkeypatch.setattr(main, "execDialog", fake_exec)
    window.openSettings()

    assert not window.isVisible()
    reopened = [w for w in houdini.children() if isinstance(w, main.DinoWriter) and w.isVisible()]
    assert len(reopened) == 1
    new_window = reopened[0]
    assert new_window.filename.text() == "my_shot", "field values must survive the reopen"
    assert new_window.addresolution == ["777 333"]
    new_window.close()
