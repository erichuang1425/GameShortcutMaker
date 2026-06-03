"""
Tests for the scan traversal helpers, in particular that unreadable folders are
reported (logged) rather than silently dropped the way default os.walk does.
Cross-platform.
"""
import logging
import os

from scanner import (
    _log_walk_error, safe_walk, scan_swf_candidates, build_topmost_swf_candidates,
)


def test_log_walk_error_emits_warning(caplog):
    with caplog.at_level(logging.WARNING):
        _log_walk_error(OSError("permission denied: /games/locked"))
    messages = [r.getMessage() for r in caplog.records]
    assert any("permission denied: /games/locked" in m for m in messages)


def test_safe_walk_visits_whole_tree(tmp_path):
    (tmp_path / "a" / "b").mkdir(parents=True)
    (tmp_path / "a" / "f.txt").write_text("x")

    visited = {os.path.relpath(d, str(tmp_path)) for d, _, _ in safe_walk(str(tmp_path))}
    assert "." in visited
    assert os.path.join("a", "b") in visited


def test_safe_walk_uses_error_handler(tmp_path):
    # The onerror handler is wired through; os.walk invokes it for a bad top
    # (e.g. a path that is a file, not a directory) instead of raising.
    seen = []
    f = tmp_path / "not_a_dir.txt"
    f.write_text("x")
    list(safe_walk(str(f), onerror=seen.append))
    assert seen and isinstance(seen[0], OSError)


# --------------------------------------------------------------------------
# scan_swf_candidates: Flash games ship a .swf launcher and no .exe; the scan
# treats the .swf as an exe-equivalent launcher so they still get a shortcut.
# --------------------------------------------------------------------------

def test_scan_swf_candidates_finds_swf_recursively(tmp_path):
    (tmp_path / "game.swf").write_text("x")
    (tmp_path / "sub").mkdir()
    (tmp_path / "sub" / "extra.SWF").write_text("x")  # case-insensitive
    (tmp_path / "notes.txt").write_text("x")
    (tmp_path / "readme.html").write_text("x")

    found = {os.path.basename(p) for p in scan_swf_candidates(str(tmp_path))}
    assert found == {"game.swf", "extra.SWF"}


def test_scan_swf_candidates_empty_when_none(tmp_path):
    (tmp_path / "game.exe").write_text("x")
    assert scan_swf_candidates(str(tmp_path)) == []


def test_build_topmost_swf_candidates_prefers_shallowest(tmp_path):
    # Only the shallowest .swf files are offered as launchers; deeper ones are
    # bundled sub-content and must not appear as candidates.
    (tmp_path / "play.swf").write_text("x")
    (tmp_path / "extras").mkdir()
    (tmp_path / "extras" / "bonus.swf").write_text("x")

    cands = build_topmost_swf_candidates(str(tmp_path), "Game")
    assert {os.path.basename(c.path) for c in cands} == {"play.swf"}


def test_build_topmost_swf_candidates_empty_when_none(tmp_path):
    (tmp_path / "game.exe").write_text("x")
    assert build_topmost_swf_candidates(str(tmp_path), "Game") == []
