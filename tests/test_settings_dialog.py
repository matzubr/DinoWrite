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
    from DinoWrite.core import acescg
    monkeypatch.setattr(acescg, "findOiiotool", lambda custom="": "/hfs/bin/hoiiotool")
    monkeypatch.setattr(acescg, "oiiotoolVersion", lambda tool: (2, 5, 16))

    dlg = SettingsDialog()
    yield dlg
    dlg.deleteLater()


def test_unchanged_dialog_collects_current_settings(dialog):
    from DinoWrite import config

    settings, errors = dialog.collect()
    assert errors == []
    assert settings == config.load()


def test_video_tab_shows_found_ffmpeg_and_encoders(dialog):
    try:
        import PyOpenColorIO
        ocio_version = PyOpenColorIO.__version__
    except ImportError:
        ocio_version = "NOT FOUND, EXR stay as recorded"
    assert dialog.toolsText() == ("ffmpeg: /hfs/bin/hffmpeg\nEncoders: h264_mf, mpeg4\n"
                                  "oiiotool: /hfs/bin/hoiiotool (2.5.16)\n"
                                  f"PyOpenColorIO: {ocio_version}")


def test_acescg_option_is_saved(dialog, tmp_path):
    assert dialog.exr_acescg.isChecked() and dialog.ldr_matte_paint.isChecked()
    dialog.exr_acescg.setChecked(False)
    dialog.ldr_matte_paint.setChecked(False)
    dialog.save()
    stored = json.loads((tmp_path / "user_settings.json").read_text())
    assert stored == {"advanced": {"exr_acescg": False, "ldr_matte_paint": False}}


def test_compression_and_audio_options_are_saved(dialog, tmp_path):
    assert dialog.exr_compression.currentData() == "dwaa" and dialog.video_audio.isChecked()
    dialog.exr_compression.setCurrentIndex(dialog.exr_compression.findData("zip"))
    dialog.video_audio.setChecked(False)
    dialog.save()
    stored = json.loads((tmp_path / "user_settings.json").read_text())
    assert stored == {"advanced": {"exr_compression": "zip", "video_audio": False}}


def test_validation_errors(dialog):
    dialog.fb_name.setText("{name}.{version}.{fileformat}")
    dialog.resolutions.setPlainText("1920 1080\nwide")
    dialog.frame_ranges.setPlainText("Broken range")
    _, errors = dialog.collect()
    assert len(errors) == 3


def test_unknown_template_placeholder_is_rejected(dialog):
    dialog.fb_folder.setText("$HIP/../preview/{shot}")
    _, errors = dialog.collect()
    assert any("unknown placeholder" in e for e in errors)


def test_save_writes_only_changes(dialog, tmp_path):
    dialog.open_after.setCurrentIndex(dialog.open_after.findData("folder"))
    dialog.resolutions.setPlainText("4096   2160\n1920 1080")
    dialog.frame_ranges.setPlainText("Shot = 1001 1100")
    dialog.save()

    stored = json.loads((tmp_path / "user_settings.json").read_text())
    assert stored == {
        "advanced": {"open_after": "folder"},
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


def test_token_chips_insert_at_cursor_and_preview(dialog):
    dialog.fb_name.setText("{name}.$F4.{fileformat}")
    dialog.fb_name.setCursorPosition(len("{name}"))
    dialog.insertToken(dialog.fb_name, ".{version}")
    assert dialog.fb_name.text() == "{name}.{version}.$F4.{fileformat}"
    assert dialog.name_preview.text() == "→ shot_010.v001.1001.exr"
    dialog.fb_name.setText("{shot}.$F4.exr")
    assert "Unknown placeholder" in dialog.name_preview.text()
    dialog.fb_name.setText("{name}.exr")
    assert "frame token" in dialog.name_preview.text()


def test_browse_keeps_name_subfolder(dialog, monkeypatch):
    from DinoWrite.gui import settings_dialog

    asked = []
    monkeypatch.setattr(settings_dialog, "pickFolder", lambda start, parent=None: asked.append(start) or "$JOB/flipbooks/")
    dialog.fb_folder.setText("$HIP/../preview/{name}")
    dialog.browseFolder()
    assert asked == ["$HIP/../preview"] and dialog.fb_folder.text() == "$JOB/flipbooks/{name}"
    dialog.fb_folder.setText("/mnt/previews")
    dialog.browseFolder()
    assert dialog.fb_folder.text() == "$JOB/flipbooks"
    monkeypatch.setattr(settings_dialog, "pickFolder", lambda start, parent=None: "")  # cancelled
    dialog.browseFolder()
    assert dialog.fb_folder.text() == "$JOB/flipbooks"


def test_chosen_folder_gets_variables_back(monkeypatch):
    from DinoWrite.gui import settings_dialog

    roots = {"$HIP": "C:/projects/sh010/houdini", "$JOB": "C:/projects"}
    monkeypatch.setattr(settings_dialog, "expand", lambda path: roots.get(path, path))
    assert settings_dialog.withVariables("C:/projects/sh010/preview") == "$JOB/sh010/preview"
    roots["$JOB"] = "$JOB"  # no $JOB set
    assert settings_dialog.withVariables("C:/projects/sh010/houdini/flipbooks/") == "$HIP/flipbooks"
    assert settings_dialog.withVariables("C:/projects/sh010/preview") == "$HIP/../preview"
    assert settings_dialog.withVariables("D:/elsewhere/very/far") in ("D:/elsewhere/very/far",)


def test_open_folder_opens_root_before_name(monkeypatch, tmp_path):
    from DinoWrite import flipbook
    from DinoWrite.gui import settings_dialog

    opened = []
    monkeypatch.setattr(flipbook, "openPath", lambda path, select=False: opened.append(path))
    monkeypatch.setattr(settings_dialog, "expand", lambda path: path.replace("$HIP", tmp_path.as_posix()))
    (tmp_path / "preview").mkdir()
    settings_dialog.openFolder("$HIP/preview/{name}")
    settings_dialog.openFolder("$HIP/not_yet/{name}")  # doesn't exist yet: the nearest parent
    assert opened == [tmp_path / "preview", tmp_path]
