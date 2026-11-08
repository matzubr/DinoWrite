"""Settings: package defaults (settings.json) + per-user overrides.

User overrides live outside the tool folder, so updating DinoWrite doesn't wipe them:
    $DINOWRITE_SETTINGS                                (if set)
    $HOUDINI_USER_PREF_DIR/DinoWrite/settings.json     (default)

Only values that differ from defaults are stored, so new defaults from updates are picked up.
Dicts are merged recursively, everything else (lists, strings, numbers) is replaced as a whole.
"""
import copy
import json
import os
from pathlib import Path

import hou

from .core.log import log

DEFAULTS_FILE = Path(__file__).resolve().parent / "settings.json"
USER_SETTINGS_ENV = "DINOWRITE_SETTINGS"


def userSettingsPath() -> Path:
    custom = os.environ.get(USER_SETTINGS_ENV)
    if custom:
        return Path(custom)
    pref_dir = hou.getenv("HOUDINI_USER_PREF_DIR")
    if pref_dir:
        return Path(pref_dir) / "DinoWrite" / "settings.json"
    return Path.home() / ".dinowrite" / "settings.json"


def lastUsedPath() -> Path:
    """Last used window values, next to the user settings (temp folders get cleaned)"""
    return userSettingsPath().parent / "last_used.json"


def _readJson(path: Path) -> dict:
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except FileNotFoundError:
        return {}
    except json.JSONDecodeError as e:
        log.error("Broken settings file, ignoring it: %s\n%s", path, e)
        return {}


def merge(base: dict, override: dict) -> dict:
    result = copy.deepcopy(base)
    for key, value in override.items():
        if isinstance(value, dict) and isinstance(result.get(key), dict):
            result[key] = merge(result[key], value)
        else:
            result[key] = copy.deepcopy(value)
    return result


def diff(current: dict, base: dict) -> dict:
    """Values of current that differ from base (recursive for dicts)"""
    result = {}
    for key, value in current.items():
        if isinstance(value, dict) and isinstance(base.get(key), dict):
            nested = diff(value, base[key])
            if nested:
                result[key] = nested
        elif key not in base or base[key] != value:
            result[key] = copy.deepcopy(value)
    return result


def defaults() -> dict:
    return _readJson(DEFAULTS_FILE)


def load() -> dict:
    return merge(defaults(), _readJson(userSettingsPath()))


def save(settings: dict) -> Path:
    """Store only overrides; removes user file if settings equal defaults"""
    path = userSettingsPath()
    overrides = diff(settings, defaults())
    if not overrides:
        reset()
        return path
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(overrides, f, ensure_ascii=False, indent=4)
    log.info("Settings saved: %s", path)
    return path


def reset() -> None:
    path = userSettingsPath()
    if path.exists():
        path.unlink()
        log.info("User settings removed, using defaults: %s", path)
