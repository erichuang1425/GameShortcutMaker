# Improvement Plan

A prioritized, code-grounded roadmap for Game Shortcut Maker. Each item lists
the problem, the affected code, a concrete proposal, and a rough effort
estimate (S = under an hour, M = a few hours, L = a day or more). Items are
ordered so the highest value-per-effort work comes first.

The guiding principles, in priority order:

1. **Correctness** — never write the wrong shortcut or crash mid-scan.
2. **Safety** — the app is "safe by default"; keep it that way.
3. **Testability** — the pure logic is the heart of the app; lock it down.
4. **Maintainability** — `app.py` is 1700+ lines and growing.
5. **Polish** — UX and docs.

---

## P0 — Correctness bugs

### 1. Glob metacharacters in shortcut names break duplicate handling (S) — ✅ done

> Implemented: `_duplicate_glob()` now `glob.escape()`s both the output dir and
> base name (`shortcut_manager.py`); regression tests in
> `tests/test_shortcut_manager.py`.

`safe_filename()` strips `<>:"/\|?*` but **not** `[` or `]`
(`shortcut_manager.py:20-23`). Game folders frequently contain brackets, e.g.
`My Game [Final]` or `Game [v1.0]`. Those names flow straight into
`glob.glob()` patterns:

- `find_existing_shortcut()` — `shortcut_manager.py:141,145`
- `cleanup_duplicate_shortcuts()` — `shortcut_manager.py:159-164`

`glob` interprets `[Final]` as a character class, so the pattern silently
fails to match the real files. Result: existing shortcuts for bracketed games
are not detected (spurious "Create" instead of "Skip"), and their numbered
duplicates are never cleaned up.

**Fix:** wrap the base name in `glob.escape()` before building the pattern
(the literal suffix ` (*).lnk` is added after escaping so the `*` still
globs). Add a regression test with a bracketed display name.

### 2. `os.walk` has no `onerror` handler — a single unreadable folder is silent (S) — ◐ partial

> Implemented: a shared `safe_walk()` wrapper now routes every traversal
> (`scanner.py`, `collection.py`) through an `onerror` handler that logs
> unreadable paths instead of swallowing them; tested in `tests/test_scanner.py`.
> **Still open:** surfacing the count to the user in the review UI (needs worker
> → `MainWindow` plumbing).

Every traversal (`scanner.py:33,74,83`, `collection.py:102`) calls `os.walk`
with the default `onerror=None`, which **swallows** `OSError`. A permission
error or a path-too-long folder makes `os.walk` quietly skip that subtree, so
a real game can vanish from the scan with no feedback.

**Fix:** pass an `onerror` callback that records the failing path, surface the
count to the user ("3 folders could not be read"), and log the paths. This is
a safety issue: silent omission is worse than a visible error.

---

## P1 — Test coverage for the pure logic

The classifier and path helpers are well tested (`tests/test_collection.py`,
19 cases). The other pure modules — which directly decide *which executable
becomes a shortcut* — have **zero** tests:

| Module | Public surface | Why it matters |
|--------|----------------|----------------|
| `versioning.py` | `extract_version`, `strip_version_from_title`, `compare_versions` | Drives the replace-on-newer-version decision. A regression here silently overwrites or skips the wrong games. |
| `exe_scoring.py` | `score_exe` | Picks the recommended launcher. |
| `html_scoring.py` | `score_html` | Picks HTML entry points; the `HTML_LAUNCHER_THRESHOLD = 40` coupling in `collection.py:42` is currently asserted only indirectly. |
| `rules.py` | `is_ignored` | The installer/redist filter. |

### 3. Add `tests/test_versioning.py` (S) — ✅ done

Cover the sharp edges that already exist in the code:

- `_VERSION_RE` requires at least one dot, so `"v2"` yields no version but
  `"v2.0"` yields `(2, 0)` (`versioning.py:4`). Pin this behavior.
- "newer version replaces older" ordering: `compare_versions((0,14), (0,14,17))`
  must be `-1` (the README's `v0.14 → 0.14.17` example).
- `strip_version_from_title("Game v1.2 win64")` and the all-version-string
  fallback (`return name.strip()` at `versioning.py:27`).

### 4. Add `tests/test_scoring.py` and `tests/test_rules.py` (M) — ✅ done

- Assert installer-like names lose to the real binary, title matches win,
  and depth penalties order candidates correctly.
- Pin the HTML/collection coupling: `score_html("index.html", …) >= 40`
  while `score_html("readme.html", …) < 40`, so the
  `HTML_LAUNCHER_THRESHOLD` constant can't drift out from under
  `collection.py` unnoticed.
- `is_ignored` should be exercised with both name globs and **path** globs.
  Note the path globs are Windows-style (`*\\tools\\*`,
  `rules.py:26-35`) and `is_ignored` normalizes to backslashes
  (`shortcut_manager.py`/`rules.py:49`) — a cross-platform test documents
  that intentional choice.

### 5. Wire up CI (S) — ✅ done

Add a GitHub Actions workflow running `pytest tests/ -v` on push/PR. The
suite is pure-Python and cross-platform (no Qt/win32com), so it runs on
`ubuntu-latest` in seconds. This is what makes every item above durable.

---

## P2 — Performance

### 6. Eliminate the double filesystem walk (M)

For each top-level folder the tree is walked **twice**:

1. `classify_tree()` → `_build_index()` walks the whole subtree
   (`collection.py:91-115`).
2. Then, per resolved game, `ScanWorker` walks it *again* via
   `scan_game_folder_topmost_exes` / `scan_html_candidates`
   (`scanner.py:24,81`).

On a large library on a spinning disk or a network share this doubles scan
time. `_build_index` already visits every file; it could cache the per-dir
`.exe`/`.html` listings and hand them to the scorer, or the two phases could
share a single walk. Measure first (item depends on real-world library sizes),
then refactor behind the existing function boundaries so tests stay green.

---

## P3 — Maintainability

### 7. Split `app.py` (1726 lines) into a package (M)

It currently holds theming, two `QThread` workers, four dialogs, and the
three-page `MainWindow`. Suggested split:

```
ui/theme.py        build_stylesheet, apply_theme, human_size, human_time
ui/workers.py      ScanWorker, ApplyWorker
ui/dialogs.py      ConflictDialog, DuplicateFolderDialog, LauncherPickerDialog
ui/main_window.py  MainWindow
app.py             run_app() thin entry point
```

Pure scan/apply logic that leaked into the workers (e.g. the decision
recompute in `_build_scan_item`, `app.py:294`) should move toward `models.py`
/ a new `decisions.py` so it can be unit-tested without Qt — this also feeds
item #4.

### 8. Centralize the `win32com` optional-import shim (S)

`shortcut_manager.py:9-17` guards the import and raises a friendly error.
Good. But `ensure_windows_shortcut_support()` is called inside every
write/read helper. Confirm the GUI degrades gracefully (disables Apply, shows
a banner) on non-Windows rather than only erroring at apply time, so the
review workflow is usable everywhere the tests run.

---

## P4 — Features & UX polish

### 9. Make ignore/scoring tokens configurable from the UI (M)

`_BAD_TOKENS`/`_GOOD_TOKENS` (`exe_scoring.py:6-14`) and the HTML doc list
(`html_scoring.py:32`) are hard-coded. The app already persists user
`rules.json` (`storage.py:88-97`); extend that to scoring hints so power users
can teach it about an engine it mis-ranks, without code changes.

### 10. Surface "could not read" and "ignored everything" folders in review (S)

Tie into item #2: EMPTY folders already surface as errors in review
(`collection.py:153-169` keeps them). Add a distinct status for "had
executables but all were ignored" (e.g. an installer-only folder,
`test_ignored_only_exe_is_empty`) vs. truly empty, so the user knows whether
to relax an ignore rule.

### 11. Documentation (S) — ✅ done

> Implemented: added `CHANGELOG.md` (Keep a Changelog format, grounded in the
> git history) and `docs/TUNING.md`, which documents the threshold/depth tuning
> (`DEFAULT_THRESHOLD`, `DEFAULT_MAX_DEPTH`, `collection.py:37-38`) and the
> `HTML_LAUNCHER_THRESHOLD` coupling (pinned by `tests/test_scoring.py`). The
> tuning reference lives in `docs/TUNING.md`, cross-linked from the README's
> collections section.

- Add a `CHANGELOG.md` (the latest commit messages already read like one).
- Document the threshold/depth tuning (`DEFAULT_THRESHOLD`,
  `DEFAULT_MAX_DEPTH`, `collection.py:36-37`) and the
  `HTML_LAUNCHER_THRESHOLD` coupling in the README's collections section.

---

## Suggested sequencing

1. **Quick correctness pass (P0 #1, #2)** — small, high value, ship first.
2. **Lock it down (P1 #3–#5)** — tests + CI before any refactor.
3. **Refactor & perf (P2 #6, P3 #7–#8)** — safe once CI is green.
4. **Features (P4)** — incremental, user-facing.

The **quick-win pass — P0 #1/#2 and P1 #3/#4/#5 — is implemented in this PR**
(44 tests passing, CI added). The remaining open work is the UI half of #2 and
everything from P2 onward.
