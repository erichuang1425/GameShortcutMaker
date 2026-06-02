"""
Tests for shortcut duplicate detection/cleanup, focused on game names that
contain glob metacharacters ('[' / ']'). Before _duplicate_glob escaped them,
these names silently failed to match their own files. Cross-platform.
"""
import os

from shortcut_manager import (
    find_existing_shortcut, cleanup_duplicate_shortcuts, multi_shortcut_names,
    categorize_apply_error, summarize_errors, to_windows_path, short_path,
)


def _touch(path: str) -> None:
    open(path, "w").close()


# --------------------------------------------------------------------------
# multi_shortcut_names: one game -> one or many distinctly named shortcuts
# --------------------------------------------------------------------------

def test_multi_names_single_keeps_title():
    assert multi_shortcut_names("Cool Game", ["C:/g/Cool Game.exe"]) == ["Cool Game"]


def test_multi_names_suffixes_extra_launchers_with_stem():
    names = multi_shortcut_names("Cool Game", ["C:/g/game.exe", "C:/g/editor.exe"])
    assert names == ["Cool Game", "Cool Game - editor"]


def test_multi_names_dedupes_colliding_stems():
    names = multi_shortcut_names("Game", ["C:/g/a/run.exe", "C:/g/b/run.exe", "C:/g/c/run.exe"])
    # first keeps the title; the two "run" stems must not collide
    assert names[0] == "Game"
    assert names[1] == "Game - run"
    assert names[2] == "Game - run (2)"
    assert len(set(n.lower() for n in names)) == 3


def test_multi_names_empty():
    assert multi_shortcut_names("Game", []) == []


def test_find_existing_shortcut_matches_bracketed_duplicate(tmp_path):
    out = str(tmp_path)
    name = "My Game [Final]"  # brackets are a glob character class if unescaped
    _touch(os.path.join(out, "My Game [Final] (1).lnk"))

    path, ttype = find_existing_shortcut(out, name)
    assert os.path.basename(path) == "My Game [Final] (1).lnk"
    assert ttype == "exe"


def test_find_existing_shortcut_matches_bracketed_url(tmp_path):
    out = str(tmp_path)
    name = "Web [Demo]"
    _touch(os.path.join(out, "Web [Demo] (2).url"))

    path, ttype = find_existing_shortcut(out, name)
    assert os.path.basename(path) == "Web [Demo] (2).url"
    assert ttype == "html"


def test_cleanup_removes_bracketed_duplicates_keeps_canonical(tmp_path):
    out = str(tmp_path)
    name = "Game [v1.0]"
    canonical = os.path.join(out, "Game [v1.0].lnk")
    dup = os.path.join(out, "Game [v1.0] (1).lnk")
    _touch(canonical)
    _touch(dup)

    cleanup_duplicate_shortcuts(out, name)

    assert os.path.exists(canonical)   # canonical untouched
    assert not os.path.exists(dup)     # numbered duplicate removed


def test_cleanup_is_noop_for_unrelated_names(tmp_path):
    out = str(tmp_path)
    other = os.path.join(out, "Other Game (1).lnk")
    _touch(other)

    cleanup_duplicate_shortcuts(out, "Game [v1.0]")

    assert os.path.exists(other)


# --------------------------------------------------------------------------
# Apply-error categorization: turns a wall of per-item failures into a summary
# the completion dialog (and exported log) can show. Cross-platform.
# --------------------------------------------------------------------------

def test_categorize_permission_errors():
    assert categorize_apply_error("Game: [WinError 5] Access is denied") == \
        "Permission denied / read-only output folder"
    assert categorize_apply_error("X: [Errno 13] Permission denied: '/o'") == \
        "Permission denied / read-only output folder"


def test_categorize_pywin32_missing():
    cat = categorize_apply_error("Game: No module named 'win32com'")
    assert "pywin32" in cat


def test_categorize_path_too_long():
    assert categorize_apply_error("G: [WinError 206] The filename or extension is too long") == \
        "Path too long"


def test_categorize_not_found_and_other():
    assert categorize_apply_error("G: [WinError 2] cannot find the path") == \
        "File or path not found"
    assert categorize_apply_error("G: something weird happened") == "Other error"


def test_summarize_errors_counts_by_category():
    details = [
        "A: [WinError 5] Access is denied",
        "B: [WinError 5] Access is denied",
        "C: No module named 'win32com'",
    ]
    summary = summarize_errors(details)
    assert summary["Permission denied / read-only output folder"] == 2
    assert sum(summary.values()) == 3


def test_summarize_errors_empty():
    assert summarize_errors([]) == {}


# --------------------------------------------------------------------------
# to_windows_path: WScript.Shell rejects forward slashes in Targetpath with
# "Property '<unknown>.Targetpath' can not be set.", so paths derived from a
# game root entered as 'D:/Games/...' must be converted to backslashes first.
# Cross-platform (pure string transform; no Windows/COM needed).
# --------------------------------------------------------------------------

def test_to_windows_path_converts_forward_slashes():
    assert to_windows_path("D:/Games/Encrypted/[Game]/Foo/game.exe") == \
        "D:\\Games\\Encrypted\\[Game]\\Foo\\game.exe"


def test_to_windows_path_converts_mixed_separators():
    # os.walk under a forward-slash root yields mixed separators on Windows.
    assert to_windows_path("D:/Games/Foo\\game.exe") == "D:\\Games\\Foo\\game.exe"


def test_to_windows_path_leaves_backslash_paths_unchanged():
    p = "C:\\Games\\Foo\\game.exe"
    assert to_windows_path(p) == p


def test_to_windows_path_handles_empty():
    assert to_windows_path("") == ""


def test_categorize_targetpath_rejected():
    cat = categorize_apply_error(
        "Some Game: Property '<unknown>.Targetpath' can not be set."
    )
    assert cat == "Invalid shortcut target (Targetpath rejected)"
    # And it no longer falls through to the generic bucket.
    assert cat != "Other error"


# --------------------------------------------------------------------------
# short_path / create_or_replace_shortcut fallback. WScript.Shell rejects a
# Targetpath over MAX_PATH with the same opaque message as a forward-slash
# target, so an over-length target is retried with the 8.3 short path and, if
# still failing, reported with the actual path + length. Cross-platform: the
# COM write can't run here, but the helper degrades gracefully and the enriched
# message must still bucket correctly.
# --------------------------------------------------------------------------

def test_short_path_degrades_to_input_without_win32api():
    # On the non-Windows test host win32api is absent, so short_path is a no-op.
    p = "C:\\Games\\Foo\\game.exe"
    assert short_path(p) == p
    assert short_path("") == ""


def test_categorize_overlong_target_is_path_too_long():
    # The enriched message from create_or_replace_shortcut for a target past
    # MAX_PATH carries both the original "Targetpath ... can not be set." text
    # and a "too long" hint; it must route to the dedicated length category.
    long_target = "D:\\Games\\" + ("x" * 300) + "\\game.exe"
    msg = (
        "Property '<unknown>.Targetpath' can not be set. "
        f"[target={long_target!r}, length={len(long_target)}]"
        f" — target path is too long ({len(long_target)} chars, exceeds Windows MAX_PATH 260)"
    )
    assert categorize_apply_error(msg) == "Path too long"


def test_categorize_enriched_targetpath_without_length_hint():
    # A rejection that is NOT length-related keeps the original target bucket
    # even with the diagnostic path/length suffix appended.
    msg = (
        "Property '<unknown>.Targetpath' can not be set. "
        "[target='D:\\\\Games\\\\Foo\\\\game.exe', length=28]"
    )
    assert categorize_apply_error(msg) == "Invalid shortcut target (Targetpath rejected)"
