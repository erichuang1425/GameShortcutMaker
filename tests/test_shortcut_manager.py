"""
Tests for shortcut duplicate detection/cleanup, focused on game names that
contain glob metacharacters ('[' / ']'). Before _duplicate_glob escaped them,
these names silently failed to match their own files. Cross-platform.
"""
import os

from shortcut_manager import find_existing_shortcut, cleanup_duplicate_shortcuts


def _touch(path: str) -> None:
    open(path, "w").close()


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
