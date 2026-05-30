"""
Tests for the scan traversal helpers, in particular that unreadable folders are
reported (logged) rather than silently dropped the way default os.walk does.
Cross-platform.
"""
import logging
import os

from scanner import _log_walk_error, safe_walk


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
