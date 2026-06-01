from __future__ import annotations

import json
import os
import tempfile
import time

# ------------------------------------------------------------------
# App-level constants
# ------------------------------------------------------------------

APP_DIR_NAME = "GameShortcutMakerQt"

SETTINGS_FILE = "settings.json"
RULES_FILE = "rules.json"

INDEX_FILE_NAME = ".shortcut_index.json"
RUN_LOG_NAME = ".last_run.json"
BACKUP_DIR_NAME = ".backup_shortcuts"
CONFIRM_FILE_NAME = ".confirmations.json"

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


def _save_json_safe(path: str, data: dict) -> bool:
    """Best-effort JSON write. Returns True on success, False if the target is
    not writable (e.g. a read-only or encrypted output folder). Bookkeeping
    files use this so a persistence failure never aborts shortcut creation."""
    try:
        _save_json(path, data)
        return True
    except OSError:
        return False


def is_dir_writable(path: str) -> bool:
    """True if a file can actually be created in `path`.

    Used for a pre-flight check before an apply: a read-only / encrypted output
    folder is the usual reason a whole run fails to create any shortcuts. Tests
    by creating and removing a temp file (a permission *check* via os.access is
    unreliable on Windows and network shares)."""
    try:
        fd, tmp = tempfile.mkstemp(dir=path, suffix=".gsm_wtest")
        os.close(fd)
        os.unlink(tmp)
        return True
    except OSError:
        return False


def _write_text_safe(path: str, text: str) -> bool:
    try:
        with open(path, "w", encoding="utf-8") as f:
            f.write(text)
        return True
    except OSError:
        return False


def save_apply_error_log(output_dir: str, text: str) -> str:
    """Write an apply error report and return its path ("" if nowhere worked).

    Prefers the output folder, but falls back to the per-user app config dir
    when the output folder is read-only — which is exactly the case that
    produces a wall of apply errors, so the log must not depend on the same
    folder being writable."""
    name = f"apply_errors_{time.strftime('%Y%m%d-%H%M%S')}.log"
    if output_dir and is_dir_writable(output_dir):
        path = os.path.join(output_dir, name)
        if _write_text_safe(path, text):
            return path
    try:
        path = os.path.join(app_config_dir(), name)
        if _write_text_safe(path, text):
            return path
    except Exception:
        pass
    return ""


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


def item_output_dir(output_dir: str, rel_subdir: str) -> str:
    """Output folder for a (possibly collection-nested) item.

    `rel_subdir` is the POSIX-style mirrored subpath ("" = top level). Single
    source of truth for the source-folder -> output-folder mapping, shared by
    the scan worker, the apply worker, and the post-pick existence re-check.
    """
    if not rel_subdir:
        return output_dir
    return os.path.join(output_dir, *rel_subdir.split("/"))


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


def save_shortcut_index(output_dir: str, index: dict) -> bool:
    """Persist the index. Returns False if the output folder is not writable
    (the shortcuts themselves may still have been created successfully)."""
    index["index_version"] = 2
    return _save_json_safe(index_path_for_output(output_dir), index)


# ------------------------------------------------------------------
# Confirmation cache (per output folder)
#
# Remembers the launcher choice the user made for a game/collection folder so
# repeat scans can reuse it (and the "skip cached confirmations" batch action
# can apply them without prompting). Keyed by the absolute source folder path.
# ------------------------------------------------------------------

def confirmations_path(output_dir: str) -> str:
    return os.path.join(output_dir, CONFIRM_FILE_NAME)


def load_confirmations(output_dir: str) -> dict:
    """
    Structure:
    {
      "version": 1,
      "choices": {
        "C:\\Games\\SomeGame": {
          "treat_as_collection": false,
          "launchers": [{"type": "exe", "path": "C:\\Games\\SomeGame\\Game.exe"}]
        }
      }
    }
    """
    raw = _load_json(confirmations_path(output_dir), {"version": 1, "choices": {}})
    if "choices" not in raw or not isinstance(raw.get("choices"), dict):
        raw = {"version": 1, "choices": {}}
    return raw


def save_confirmations(output_dir: str, data: dict) -> bool:
    data.setdefault("version", 1)
    return _save_json_safe(confirmations_path(output_dir), data)


# ------------------------------------------------------------------
# Backups
# ------------------------------------------------------------------

def backup_dir(output_dir: str) -> str:
    """
    Directory used to store backed-up shortcuts before replace.

    Creation is best-effort: if the output folder is not writable we still
    return the intended path (backup_shortcut retries the mkdir lazily and is
    guarded per-item), so an unwritable folder never aborts the whole apply.
    """
    path = os.path.join(output_dir, BACKUP_DIR_NAME)
    try:
        os.makedirs(path, exist_ok=True)
    except OSError:
        pass
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


def save_last_run(output_dir: str, run_log: dict) -> bool:
    """Persist the undo log. Returns False if the output folder is not writable."""
    return _save_json_safe(run_log_path(output_dir), run_log)
