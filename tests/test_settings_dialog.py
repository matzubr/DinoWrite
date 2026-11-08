"""Settings dialog offscreen (PySide6)"""
import json

import pytest

pytest.importorskip("PySide6.QtWidgets")


@pytest.fixture
def dialog(houdini, monkeypatch):
    from DinoWrite.core import ffmpeg
    from DinoWrite.gui.settings_dialog import SettingsDialog

    monkeypatch.setattr(ffmpeg, "findFFmpeg", lambda custom="": "/hfs/bin/hffmpeg")
    monkeypatch.setattr(ffmpeg, "availableEncoders", lambda binary: {"h264_mf", "mpeg4"})

    dlg = SettingsDialog()
    yield dlg
    dlg.deleteLater()


def test_unchanged_dialog_collects_current_settings(dialog):
    from DinoWrite import config

    settings, errors = dialog.collect()
    assert errors == []
    assert settings == config.load()


def test_video_tab_shows_found_ffmpeg_and_encoders(dialog):
    assert dialog.tools_status.text() == "ffmpeg: /hfs/bin/hffmpeg\nencoders (auto order): h264_mf, mpeg4"


def test_validation_errors(dialog):
    dialog.fb_name.setText("{name}.{version}.{fileformat}")
    dialog.resolutions.setPlainText("1920 1080\nwide")
    dialog.frame_ranges.setPlainText("Broken range")
    dialog.ffmpeg_cmd.setPlainText("ffmpeg\n-i {input}")
    _, errors = dialog.collect()
    assert len(errors) == 4


def test_unknown_template_placeholder_is_rejected(dialog):
    dialog.fb_folder.setText("$HIP/../preview/{shot}")
    _, errors = dialog.collect()
    assert any("unknown placeholder" in e for e in errors)


def test_save_writes_only_changes(dialog, tmp_path):
    dialog.video_codec.setCurrentText("mpeg4")
    dialog.resolutions.setPlainText("4096   2160\n1920 1080")
    dialog.frame_ranges.setPlainText("Shot = 1001 1100")
    dialog.save()

    stored = json.loads((tmp_path / "user_settings.json").read_text())
    assert stored == {
        "advanced": {"video_codec": "mpeg4"},
        "custom_resolution": ["4096 2160", "1920 1080"],
        "custom_framerange": {"Shot": "1001 1100"},
    }


def test_gear_button_reopens_window_with_new_settings(houdini, monkeypatch, tmp_path):
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
