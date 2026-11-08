import os
import time

import DinoWrite


def test_show_reloads_when_files_changed_on_disk(monkeypatch):
    reloaded = []
    monkeypatch.setattr(DinoWrite, "reload_modules", lambda: reloaded.append(True))
    monkeypatch.setattr(DinoWrite, "_loaded_at", time.time() + 3600)
    assert not DinoWrite._filesChangedSinceLoad()

    monkeypatch.setattr(DinoWrite, "_loaded_at", 0)
    assert DinoWrite._filesChangedSinceLoad()


def test_reload_modules_resets_load_time():
    DinoWrite._loaded_at = 0
    DinoWrite.reload_modules()
    assert not DinoWrite._filesChangedSinceLoad()
    assert abs(DinoWrite._loaded_at - time.time()) < 60
    assert os.path.isdir(DinoWrite._PACKAGE_DIR)
