# Changelog

All notable changes to this project are documented here.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added
- Recursive "collection of games" detection: a folder whose subfolders are
  themselves games is mirrored into an output subfolder of shortcuts instead of
  being collapsed into one ambiguous shortcut (`collection.py`).
- HTML-only games are now detected during collection classification, so a
  folder whose only launcher is an entry point such as `index.html` is treated
  as a game (`collection.py`, `html_scoring.py`).
- A pure-Python test suite (44 tests) covering classification, versioning,
  exe/HTML scoring, ignore rules, scanner traversal, and shortcut
  deduplication, plus a GitHub Actions workflow that runs it on Python 3.9 and
  3.12 (`tests/`, `.github/workflows/tests.yml`, `pytest.ini`).
- `IMPROVEMENTS.md`: a prioritized, code-grounded improvement roadmap.
- `docs/TUNING.md`: documentation of the collection threshold/depth knobs and
  the HTML launcher-score coupling.

### Fixed
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

## [1.0.0]

### Added
- Initial release: scan a game library, score candidate executables (and HTML
  entry points) per folder, and create/replace/skip Windows shortcuts with a
  review step, version-aware replacement, backups, and undo.
