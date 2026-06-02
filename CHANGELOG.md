# Changelog

All notable changes to this project are documented here.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added
- Flatten redundant folders ("Flatten folders…" on the setup page): collapses
  pure single-child nesting in the game root — e.g. `Game/Game/v1.2/<files>` →
  `Game/<files>` — pulling the real content up into the top game folder (kept)
  and removing the empty wrappers. Only levels that hold *exactly* one subfolder
  and nothing else are collapsed, so nothing can be lost. It previews every
  planned move before touching disk, never overwrites, and is undoable (an undo
  log is written to the game root). Every move is within the same folder, hence
  an instant rename rather than a copy (`squash.py`, `storage.load_last_squash`/
  `save_last_squash`, `ui/workers.SquashWorker`, `ui/main_window.py`).
- Diagnosable apply errors: a run that fails many items now shows *why*. The
  completion dialog groups failures by category (e.g. "240 × Permission denied /
  read-only output folder", "5 × pywin32 not available") and the full per-item
  list is exported to a timestamped `apply_errors_*.log`. The log is written to
  a writable location — falling back to the per-user app config dir when the
  output folder itself is read-only, which is the very case that produces the
  errors (`shortcut_manager.categorize_apply_error`/`summarize_errors`,
  `storage.save_apply_error_log`, `ui/workers.py`, `ui/main_window.py`).
- Pre-flight output-folder check: before applying, the app verifies the output
  folder is actually writable and asks for confirmation if not, instead of
  silently failing every item (`storage.is_dir_writable`, `ui/main_window.py`).
- Multiple shortcuts per game: the launcher picker now uses checkboxes, so you
  can tick several executables for one folder and get one shortcut each. Extra
  shortcuts are named after the launcher's file stem (e.g. `Cool Game`,
  `Cool Game - editor`), de-duplicated automatically
  (`shortcut_manager.multi_shortcut_names`, `ui/dialogs.py`, `ui/main_window.py`).
- Confirmation caching: launcher choices are remembered per folder in a
  `.confirmations.json` beside the shortcut index, and reused on the next scan.
  The picker gains batch actions — *auto-create the rest with best/cached picks*,
  *skip the rest*, or *auto-apply cached and ask only for the rest* — so large
  libraries no longer need a click per game (`storage.py`, `ui/main_window.py`).
- Collection confirmation: a folder auto-detected as a collection is now
  confirmable in the picker via a *Treat as a collection* toggle. Leave it on to
  create one shortcut per sub-game (mirrored into subfolders); untick it to
  collapse the folder into a single game and pick launcher(s) from the combined
  executable list (`ui/dialogs.py`, `ui/main_window.py`).
- Recursive "collection of games" detection: a folder whose subfolders are
  themselves games is mirrored into an output subfolder of shortcuts instead of
  being collapsed into one ambiguous shortcut (`collection.py`).
- Flash (`.swf`) games are now detected. A `.swf` is treated as an
  exe-equivalent launcher — the shortcut is a `.lnk` straight to the Flash file
  (opened by the user's default `.swf` handler) — so a Flash-only folder gets a
  shortcut and a folder of Flash games is detected as a collection, instead of
  being reported as launcherless. A real `.exe` is still always preferred when
  both are present; the launcher order is now `.exe` → `.swf` → HTML entry point
  (`scanner.scan_swf_candidates`, `collection._has_direct_swf`, `ui/workers.py`).
  Flash launchers are labelled `SWF` in the review table (`ui/main_window.py`).
- HTML-only games are now detected during collection classification, so a
  folder whose only launcher is an entry point such as `index.html` is treated
  as a game (`collection.py`, `html_scoring.py`). In EXE mode, a folder with no
  `.exe`/`.swf` launcher still falls back to its best-matching HTML entry point
  (`ui/workers.py`).
- A pure-Python test suite (44 tests) covering classification, versioning,
  exe/HTML scoring, ignore rules, scanner traversal, and shortcut
  deduplication, plus a GitHub Actions workflow that runs it on Python 3.9 and
  3.12 (`tests/`, `.github/workflows/tests.yml`, `pytest.ini`).
- `IMPROVEMENTS.md`: a prioritized, code-grounded improvement roadmap.
- `docs/TUNING.md`: documentation of the collection threshold/depth knobs and
  the HTML launcher-score coupling.

### Fixed
- Long `.exe` targets no longer fail apply with the same opaque
  "Property '<unknown>.Targetpath' can not be set." Once forward slashes are
  normalized away (below), the other cause of that message is a target path at or
  beyond Windows' `MAX_PATH` (260 chars) — common for deeply nested doujin/RPG
  games under a long-named root. Such a target is now retried with its Windows
  8.3 short path (same file, short enough to be accepted); if it still fails, the
  error records the actual target and its length and is reported under the
  dedicated "Path too long" category instead of repeating the opaque message, so
  the apply log pinpoints the cause (`shortcut_manager.short_path`,
  `create_or_replace_shortcut`, `categorize_apply_error`).
- Creating `.lnk` shortcuts no longer fails with
  "Property '<unknown>.Targetpath' can not be set." when the game root or output
  folder was entered with forward slashes (e.g. `D:/Games/...`). Those slashes
  flowed straight into each `.exe` target via `os.path.join`, and WScript.Shell
  rejects forward slashes in its path properties — so an entire library failed
  to apply while only the `.url` (HTML) shortcuts succeeded. Paths are now
  normalized to Windows backslashes at the COM boundary
  (`shortcut_manager.to_windows_path`, used by `create_or_replace_shortcut` and
  `read_shortcut_target`). The error is also categorized explicitly now, so a
  recurrence shows as "Invalid shortcut target (Targetpath rejected)" instead of
  the generic "Other error" (`shortcut_manager.categorize_apply_error`).
- A read-only / encrypted output folder no longer fails an apply *after* the
  shortcuts were already created. The final `.shortcut_index.json` and
  `.last_run.json` writes (and the backup-folder creation) used to raise
  `PermissionError` outside the per-item guard, surfacing as "Apply failed"
  despite a successful run. Metadata persistence is now best-effort and reported
  as a non-fatal warning in the completion dialog (`storage.py`, `ui/workers.py`,
  `ui/main_window.py`).
- Scan progress no longer freezes at 0%. Collection detection used to walk the
  whole library before emitting any progress, so the bar sat at "Scanning…" 0%
  through the heaviest I/O. It is now an animated "Detecting collections…" busy
  phase (reporting folders scanned) followed by a determinate "Scanning games…
  i/n" bar (`ui/workers.py`, `ui/main_window.py`).
- Glob metacharacters in game names (commonly `[` / `]`, e.g. `Game [Final]`)
  no longer break duplicate-shortcut detection and cleanup. Both the output
  directory and the base name are passed through `glob.escape()` before building
  the lookup pattern (`shortcut_manager.py`).
- Directory traversal no longer silently drops a whole subtree when a single
  folder is unreadable (permissions, path too long). All `os.walk` calls now go
  through `safe_walk()`, which routes errors to a logging `onerror` handler
  instead of swallowing them (`scanner.py`, `collection.py`).

### Changed
- Split the 1700-line `app.py` into a `ui/` package (`theme`, `workers`,
  `dialogs`, `main_window`); `app.py` is now a thin `run_app()` entry point.
  Behavior is unchanged — the split is mechanical, and a few dead imports
  (`QIcon`, `ExeCandidate`, `shortcut_path`, `url_shortcut_path`) were dropped.
- Stopped tracking `__pycache__` build artifacts and added a `.gitignore`.
- Collection detection is now a single filesystem walk that feeds both
  classification and each game's executable list, eliminating the second
  per-game walk the scan used to do (the source of the post-1.0 slowdown). The
  walk stops descending below a folder's topmost non-ignored `.exe` — where the
  classifier already returns GAME — so a game's deep asset tree is never walked;
  HTML-only/ignored-only folders are still descended so a buried `.exe` is never
  missed. Net effect: scan speed matches (and for exe games beats) the original
  per-folder scan while keeping collection detection (`collection.py`,
  `scanner.py`, `ui/workers.py`).

## [1.0.0]

### Added
- Initial release: scan a game library, score candidate executables (and HTML
  entry points) per folder, and create/replace/skip Windows shortcuts with a
  review step, version-aware replacement, backups, and undo.
