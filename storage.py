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
BACKUP_DIR_NAME = ".backup_shortcuts"   # legacy: top-level backups dir (pre-consolidation)
CONFIRM_FILE_NAME = ".confirmations.json"
SQUASH_LOG_NAME = ".last_squash.json"

# All per-output bookkeeping (index, undo log, confirmations, backups, error
# logs) lives inside this single folder in the output directory, so the output
# folder is left holding only the user's shortcuts. Earlier versions wrote the
# JSONs and .backup_shortcuts/ straight into the output folder, cluttering it
# alongside the .lnk/.url files; those are migrated in on first access
# (see _migrate_legacy_meta).
META_DIR_NAME = ".game_shortcut_maker"
BACKUPS_SUBDIR = "backups"
ICONS_SUBDIR = "icons"

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


# ------------------------------------------------------------------
# Per-output bookkeeping folder (META_DIR_NAME)
#
# Keeps the index / undo log / confirmations / backups / error logs out of the
# output folder's top level so it shows only the user's shortcuts. All path
# helpers below resolve into this folder; legacy top-level files are migrated in
# transparently on first access.
# ------------------------------------------------------------------

def _meta_path(output_dir: str) -> str:
    """The meta folder's path (no side effects; may not exist yet)."""
    return os.path.join(output_dir, META_DIR_NAME)


def _meta_read_path(output_dir: str, name: str) -> str:
    """Where to READ a bookkeeping file from, without moving anything.

    Prefers the meta folder; falls back to the legacy top-level location if a
    pre-consolidation file is still there. Reads stay side-effect-free — crucial
    for a Dry Run (and a plain scan), which must not create or move anything in
    the output folder. The actual relocation into the meta folder happens lazily
    on the next real write (see meta_dir / _migrate_legacy_meta)."""
    new = os.path.join(_meta_path(output_dir), name)
    if os.path.exists(new):
        return new
    legacy = os.path.join(output_dir, name)
    if os.path.exists(legacy):
        return legacy
    return new  # neither exists -> _load_json returns the default


_LEGACY_META_FILES = (INDEX_FILE_NAME, RUN_LOG_NAME, CONFIRM_FILE_NAME)


def _migrate_legacy_meta(output_dir: str) -> None:
    """Move pre-consolidation bookkeeping into META_DIR_NAME (one-time, best-effort).

    Earlier versions stored .shortcut_index.json / .last_run.json /
    .confirmations.json and the .backup_shortcuts/ folder directly in the output
    directory. Relocate them under META_DIR_NAME so the output folder is left
    holding only the user's shortcuts. Idempotent and cheap once migrated (a
    couple of existence checks). Undo logs written before the move still point at
    the old absolute backup paths; resolve_backup_path falls back by basename."""
    if not output_dir or not os.path.isdir(output_dir):
        return
    legacy_files = [os.path.join(output_dir, n) for n in _LEGACY_META_FILES]
    legacy_backups = os.path.join(output_dir, BACKUP_DIR_NAME)
    if not any(os.path.exists(p) for p in legacy_files) and not os.path.isdir(legacy_backups):
        return  # already migrated / nothing to move — the common case

    meta = _meta_path(output_dir)
    try:
        os.makedirs(meta, exist_ok=True)
    except OSError:
        return  # output folder not writable — leave legacy data where it is

    for name in _LEGACY_META_FILES:
        src = os.path.join(output_dir, name)
        dst = os.path.join(meta, name)
        if os.path.exists(src) and not os.path.exists(dst):
            try:
                os.replace(src, dst)
            except OSError:
                pass

    if os.path.isdir(legacy_backups):
        new_backups = os.path.join(meta, BACKUPS_SUBDIR)
        try:
            os.makedirs(new_backups, exist_ok=True)
            for name in os.listdir(legacy_backups):
                src = os.path.join(legacy_backups, name)
                dst = os.path.join(new_backups, name)
                if not os.path.exists(dst):
                    try:
                        os.replace(src, dst)
                    except OSError:
                        pass
            os.rmdir(legacy_backups)  # succeeds only once emptied
        except OSError:
            pass


def meta_dir(output_dir: str) -> str:
    """Ensure (and migrate into) the meta folder, returning its path.

    Creation is best-effort: the path is returned even if mkdir fails (a
    read-only output folder), so the write that follows fails gracefully into a
    warning rather than aborting an apply."""
    _migrate_legacy_meta(output_dir)
    path = _meta_path(output_dir)
    try:
        os.makedirs(path, exist_ok=True)
    except OSError:
        pass
    return path


def resolve_backup_path(output_dir: str, recorded_path: str) -> str:
    """Locate a backed-up shortcut referenced by an undo log.

    Returns recorded_path if it still exists; otherwise (e.g. the backups were
    migrated into META_DIR_NAME after the log was written) tries the current
    backups folder by basename. Side-effect-free (no folder creation). "" if
    neither is found."""
    if not recorded_path:
        return ""
    if os.path.exists(recorded_path):
        return recorded_path
    cand = os.path.join(_meta_path(output_dir), BACKUPS_SUBDIR, os.path.basename(recorded_path))
    return cand if os.path.exists(cand) else ""


def save_apply_error_log(output_dir: str, text: str) -> str:
    """Write an apply error report and return its path ("" if nowhere worked).

    Prefers the output folder, but falls back to the per-user app config dir
    when the output folder is read-only — which is exactly the case that
    produces a wall of apply errors, so the log must not depend on the same
    folder being writable."""
    name = f"apply_errors_{time.strftime('%Y%m%d-%H%M%S')}.log"
    if output_dir and is_dir_writable(output_dir):
        path = os.path.join(meta_dir(output_dir), name)
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
    return os.path.join(_meta_path(output_dir), INDEX_FILE_NAME)


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
    raw = _load_json(_meta_read_path(output_dir, INDEX_FILE_NAME), {"index_version": 2, "shortcuts": {}})
    return _migrate_index_v1_to_v2(raw)


def save_shortcut_index(output_dir: str, index: dict) -> bool:
    """Persist the index. Returns False if the output folder is not writable
    (the shortcuts themselves may still have been created successfully)."""
    index["index_version"] = 2
    meta_dir(output_dir)  # ensure the bookkeeping folder exists (and migrate)
    return _save_json_safe(index_path_for_output(output_dir), index)


# ------------------------------------------------------------------
# Confirmation cache (per output folder)
#
# Remembers the launcher choice the user made for a game/collection folder so
# repeat scans can reuse it (and the "skip cached confirmations" batch action
# can apply them without prompting). Keyed by the absolute source folder path.
# ------------------------------------------------------------------

def confirmations_path(output_dir: str) -> str:
    return os.path.join(_meta_path(output_dir), CONFIRM_FILE_NAME)


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
    raw = _load_json(_meta_read_path(output_dir, CONFIRM_FILE_NAME), {"version": 1, "choices": {}})
    if "choices" not in raw or not isinstance(raw.get("choices"), dict):
        raw = {"version": 1, "choices": {}}
    return raw


def save_confirmations(output_dir: str, data: dict) -> bool:
    data.setdefault("version", 1)
    meta_dir(output_dir)  # ensure the bookkeeping folder exists (and migrate)
    return _save_json_safe(confirmations_path(output_dir), data)


# ------------------------------------------------------------------
# Backups
# ------------------------------------------------------------------

def backup_dir(output_dir: str) -> str:
    """
    Directory used to store backed-up shortcuts before replace. Lives inside the
    meta folder (META_DIR_NAME/backups) so it no longer clutters the output root.

    Creation is best-effort: if the output folder is not writable we still
    return the intended path (backup_shortcut retries the mkdir lazily and is
    guarded per-item), so an unwritable folder never aborts the whole apply.
    """
    path = os.path.join(meta_dir(output_dir), BACKUPS_SUBDIR)
    try:
        os.makedirs(path, exist_ok=True)
    except OSError:
        pass
    return path


def icon_cache_dir(output_dir: str) -> str:
    """
    Directory for synthesized (upscaled) shortcut icons. Lives inside the meta
    folder (META_DIR_NAME/icons) so generated .ico files never clutter the
    output root. Best-effort creation, like backup_dir.
    """
    path = os.path.join(meta_dir(output_dir), ICONS_SUBDIR)
    try:
        os.makedirs(path, exist_ok=True)
    except OSError:
        pass
    return path


# ------------------------------------------------------------------
# Run log (Undo support)
# ------------------------------------------------------------------

def run_log_path(output_dir: str) -> str:
    return os.path.join(_meta_path(output_dir), RUN_LOG_NAME)


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
    return _load_json(_meta_read_path(output_dir, RUN_LOG_NAME), {"actions": []})


def save_last_run(output_dir: str, run_log: dict) -> bool:
    """Persist the undo log. Returns False if the output folder is not writable."""
    meta_dir(output_dir)  # ensure the bookkeeping folder exists (and migrate)
    return _save_json_safe(run_log_path(output_dir), run_log)


# ------------------------------------------------------------------
# Squash (flatten) undo log — stored in the game root, since that is the
# folder the flatten mutates (unlike shortcut runs, which touch the output dir).
# ------------------------------------------------------------------

def squash_log_path(game_root: str) -> str:
    return os.path.join(game_root, SQUASH_LOG_NAME)


def load_last_squash(game_root: str) -> dict:
    """
    Structure:
    {
      "timestamp": "...",
      "game_root": "...",
      "records": [ <execute_squash record>, ... ]
    }
    """
    return _load_json(squash_log_path(game_root), {"records": []})


def save_last_squash(game_root: str, data: dict) -> bool:
    """Persist the flatten undo log. Returns False if the game root isn't writable."""
    return _save_json_safe(squash_log_path(game_root), data)
