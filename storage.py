from __future__ import annotations

import json
import os

# ------------------------------------------------------------------
# App-level constants
# ------------------------------------------------------------------

APP_DIR_NAME = "GameShortcutMakerQt"

SETTINGS_FILE = "settings.json"
RULES_FILE = "rules.json"

INDEX_FILE_NAME = ".shortcut_index.json"
RUN_LOG_NAME = ".last_run.json"
BACKUP_DIR_NAME = ".backup_shortcuts"

# ------------------------------------------------------------------
# App config directory
# ------------------------------------------------------------------

def app_config_dir() -> str:
    """
    Returns a writable per-user config directory for the app.
    """
    from PySide6.QtCore import QStandardPaths

    base = QStandardPaths.writableLocation(QStandardPaths.AppConfigLocation)
    path = os.path.join(base, APP_DIR_NAME)
    os.makedirs(path, exist_ok=True)
    return path


# ------------------------------------------------------------------
# Generic JSON helpers
# ------------------------------------------------------------------

def _load_json(path: str, default: dict) -> dict:
    if os.path.exists(path):
        try:
            with open(path, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            pass
    return default.copy()


def _save_json(path: str, data: dict) -> None:
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


# ------------------------------------------------------------------
# Settings (folders + theme)
# ------------------------------------------------------------------

def settings_path() -> str:
    return os.path.join(app_config_dir(), SETTINGS_FILE)


def load_settings() -> dict:
    """
    User-facing preferences.
    Extend here when adding new global settings.
    """
    return _load_json(
        settings_path(),
        {
            "game_root": "",
            "shortcut_output": "",
            "theme": "Midnight Blue",
            "detect_collections": True,
            "collection_threshold": 3,
            "collection_max_depth": 6,
        },
    )


def save_settings(settings: dict) -> None:
    _save_json(settings_path(), settings)


# ------------------------------------------------------------------
# Ignore rules
# ------------------------------------------------------------------

def rules_path() -> str:
    return os.path.join(app_config_dir(), RULES_FILE)


def load_rules(default_rules: dict) -> dict:
    return _load_json(rules_path(), default_rules)


def save_rules(rules: dict) -> None:
    _save_json(rules_path(), rules)


# ------------------------------------------------------------------
# Shortcut index (per output folder)
# ------------------------------------------------------------------

def index_path_for_output(output_dir: str) -> str:
    return os.path.join(output_dir, INDEX_FILE_NAME)


def index_key(output_dir: str, item_out_dir: str, shortcut_filename: str) -> str:
    """
    Stable, collision-free index key: the shortcut path (incl. extension)
    relative to the output root, in POSIX style.

    For a flat top-level game this equals the shortcut filename (e.g.
    "Game Name.lnk"); for a collection member it includes the subfolder
    (e.g. "RenPyCollection/GameB.lnk").
    """
    rel = os.path.relpath(os.path.join(item_out_dir, shortcut_filename), output_dir)
    return rel.replace(os.sep, "/")


def _migrate_index_v1_to_v2(index: dict) -> dict:
    """
    v1 keyed entries by display name ("Game Name"); v2 keys by relative shortcut
    path ("Game Name.lnk"). v1 shortcuts were always flat, so the new key is the
    stored shortcut_name (fallback: "<safe display>.lnk"). Forward-only migration.
    """
    if index.get("index_version") == 2:
        return index

    old = index.get("shortcuts", {})
    migrated: dict = {}
    for display, meta in old.items():
        meta = dict(meta)
        meta.setdefault("display", display)
        key = meta.get("shortcut_name") or f"{display}.lnk"
        migrated[key.replace(os.sep, "/")] = meta

    return {"index_version": 2, "shortcuts": migrated}


def load_shortcut_index(output_dir: str) -> dict:
    """
    v2 structure (keyed by relative shortcut path):
    {
      "index_version": 2,
      "shortcuts": {
        "Game Name.lnk": {
          "shortcut_name": "Game Name.lnk",
          "display": "Game Name",
          "target": "C:\\Games\\Game\\Game.exe",
          "game_folder": "C:\\Games\\Game",
          "version_str": "0.14",
          "version_tuple": [0, 14]
        },
        "RenPyCollection/GameB.lnk": { ... }
      }
    }

    Older v1 indexes (keyed by display name) are migrated in-memory on load.
    """
    raw = _load_json(index_path_for_output(output_dir), {"index_version": 2, "shortcuts": {}})
    return _migrate_index_v1_to_v2(raw)


def save_shortcut_index(output_dir: str, index: dict) -> None:
    index["index_version"] = 2
    _save_json(index_path_for_output(output_dir), index)


# ------------------------------------------------------------------
# Backups
# ------------------------------------------------------------------

def backup_dir(output_dir: str) -> str:
    """
    Directory used to store backed-up shortcuts before replace.
    """
    path = os.path.join(output_dir, BACKUP_DIR_NAME)
    os.makedirs(path, exist_ok=True)
    return path


# ------------------------------------------------------------------
# Run log (Undo support)
# ------------------------------------------------------------------

def run_log_path(output_dir: str) -> str:
    return os.path.join(output_dir, RUN_LOG_NAME)


def load_last_run(output_dir: str) -> dict:
    """
    Structure:
    {
      "timestamp": "...",
      "output_dir": "...",
      "actions": [
        {
          "type": "create" | "replace",
          "display": "Game Name",
          "lnk": "C:\\Shortcuts\\Game Name.lnk",
          "target": "C:\\Games\\Game\\Game.exe",
          "backup_path": "C:\\Shortcuts\\.backup_shortcuts\\Game Name_20260124.lnk"
        }
      ]
    }
    """
    return _load_json(run_log_path(output_dir), {"actions": []})


def save_last_run(output_dir: str, run_log: dict) -> None:
    _save_json(run_log_path(output_dir), run_log)
