import json

import pytest

from DinoWrite import config


@pytest.fixture
def user_file(tmp_path, monkeypatch):
    path = tmp_path / "prefs" / "settings.json"
    monkeypatch.setenv(config.USER_SETTINGS_ENV, path.as_posix())
    return path


def test_defaults_are_used_without_user_file(user_file):
    assert config.load() == config.defaults()


def test_save_stores_only_overrides(user_file):
    settings = config.load()
    settings["advanced"]["delete_incomplete_fb"] = not settings["advanced"]["delete_incomplete_fb"]
    settings["custom_resolution"] = ["100 100"]
    config.save(settings)

    stored = json.loads(user_file.read_text())
    assert stored == {
        "advanced": {"delete_incomplete_fb": settings["advanced"]["delete_incomplete_fb"]},
        "custom_resolution": ["100 100"],
    }
    assert config.load() == settings


def test_new_defaults_are_picked_up_with_old_user_file(user_file, monkeypatch):
    user_file.parent.mkdir(parents=True)
    user_file.write_text(json.dumps({"paths": {"fb_video_ext": "mp4"}}))
    loaded = config.load()
    assert loaded["paths"]["fb_video_ext"] == "mp4"
    assert loaded["paths"]["fb_name"] == config.defaults()["paths"]["fb_name"]


def test_saving_defaults_removes_user_file(user_file):
    user_file.parent.mkdir(parents=True)
    user_file.write_text(json.dumps({"paths": {"fb_video_ext": "mp4"}}))
    config.save(config.defaults())
    assert not user_file.exists()


def test_broken_user_file_falls_back_to_defaults(user_file):
    user_file.parent.mkdir(parents=True)
    user_file.write_text("{not json")
    assert config.load() == config.defaults()


def test_user_settings_path_in_houdini_prefs(monkeypatch, hou, tmp_path):
    monkeypatch.delenv(config.USER_SETTINGS_ENV, raising=False)
    monkeypatch.setattr(hou, "getenv", lambda name, default=None: tmp_path.as_posix() if name == "HOUDINI_USER_PREF_DIR" else default)
    assert config.userSettingsPath() == tmp_path / "DinoWrite" / "settings.json"
