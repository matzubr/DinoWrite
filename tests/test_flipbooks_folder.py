"""Flipbooks folder is asked about on WRITE, not when the window opens"""
import shutil
from types import SimpleNamespace

import pytest
from conftest import waitUntil

pytest.importorskip("PySide6.QtWidgets")


@pytest.fixture
def no_preview_folder(houdini, tmp_path):
    shutil.rmtree(tmp_path / "preview")
    return tmp_path / "preview"


@pytest.fixture
def ui_calls(hou, monkeypatch):
    calls = SimpleNamespace(messages=[], answer=0, started=[], viewer=object())

    def display_message(text, **kwargs):
        calls.messages.append(text)
        return calls.answer

    monkeypatch.setattr(hou, "ui", SimpleNamespace(displayMessage=display_message,
                                                   paneTabOfType=lambda *a, **k: calls.viewer), raising=False)
    monkeypatch.setattr(hou, "hipFile", SimpleNamespace(saveAndBackup=lambda: None), raising=False)
    return calls


@pytest.fixture
def window(no_preview_folder, ui_calls, monkeypatch):
    import DinoWrite
    from DinoWrite import flipbook
    from DinoWrite.core import viewport

    fake_viewer = SimpleNamespace(cameraName=lambda: "cam", cameraPixelAspect=lambda: 1.0,
                                  getPaneTab=lambda: None)
    monkeypatch.setattr(viewport.HouViewport, "__init__", lambda self, kwargs: self.__dict__.update(fake_viewer.__dict__))
    monkeypatch.setattr(flipbook, "start", lambda data, kwargs: ui_calls.started.append(data["name"]))
    win = DinoWrite.show({})
    yield win
    win.close()


def test_opening_window_does_not_ask_about_folder(window, ui_calls, no_preview_folder):
    assert window.isVisible()
    assert ui_calls.messages == []
    assert not no_preview_folder.exists()


def test_write_cancel_keeps_window_and_writes_nothing(window, ui_calls, no_preview_folder):
    ui_calls.answer = 1
    window.main()
    assert len(ui_calls.messages) == 1
    assert no_preview_folder.as_posix() in ui_calls.messages[0]
    assert window.isVisible()
    assert ui_calls.started == []
    assert not no_preview_folder.exists()


def test_write_create_makes_folder_and_starts(window, ui_calls, no_preview_folder):
    ui_calls.answer = 0
    window.main()
    assert no_preview_folder.is_dir()
    assert ui_calls.started == [], "WRITE press animation plays first"
    window.main()  # a second click while fading out is ignored
    assert waitUntil(lambda: ui_calls.started == ["flipbook"])


def test_existing_folder_is_not_asked(window, ui_calls, no_preview_folder):
    no_preview_folder.mkdir()
    window.main()
    assert ui_calls.messages == []
    assert waitUntil(lambda: ui_calls.started == ["flipbook"])


def test_no_scene_viewer_shows_message_instead_of_traceback(no_preview_folder, ui_calls, monkeypatch):
    import DinoWrite
    from DinoWrite import main

    ui_calls.viewer = None
    messages = []
    monkeypatch.setattr(main, "hmsg", lambda text, **kwargs: messages.append(text))
    window = DinoWrite.show({})
    assert not window.isVisible() and messages == ["No Scene Viewer to record a flipbook from"]


def test_bad_resolution_is_reported_before_closing(window, ui_calls, monkeypatch):
    from DinoWrite import main

    messages = []
    monkeypatch.setattr(main, "hmsg", lambda text, **kwargs: messages.append(text))
    window.resx.setText("-")
    window.main()
    assert window.isVisible() and ui_calls.started == [] and "Resolution" in messages[0]


def test_broken_last_used_file_is_ignored(window, tmp_path):
    broken = tmp_path / "data.json"
    broken.write_text('{"name": "sho')
    assert window.load_json(broken) == {}
