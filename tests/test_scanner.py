"""
Tests for the scan traversal helpers, in particular that unreadable folders are
reported (logged) rather than silently dropped the way default os.walk does.
Cross-platform.
"""
import logging
import os

from scanner import (
    _log_walk_error, safe_walk, scan_swf_candidates, build_topmost_swf_candidates,
    scan_game_folder_topmost_exes,
)
from rules import default_rules


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


# --------------------------------------------------------------------------
# scan_game_folder_topmost_exes: which depth becomes the candidate level. The
# topmost-depth rule must skip *ignore-listed* exes when picking that level, or
# an uninstaller/setup at the folder root would shadow the real launcher one
# level down (the Undertale / Inno-Setup case).
# --------------------------------------------------------------------------

def test_topmost_skips_shallower_uninstaller_for_deeper_real_exe(tmp_path):
    # D:\Games\Undertale\unins000.exe (ignored, depth 0)
    # D:\Games\Undertale\Game-Data\UNDERTALE.exe (real launcher, depth 1)
    (tmp_path / "unins000.exe").write_text("x")
    (tmp_path / "Game-Data").mkdir()
    (tmp_path / "Game-Data" / "UNDERTALE.exe").write_text("x")

    best_depth, non_ignored, all_best = scan_game_folder_topmost_exes(
        str(tmp_path), default_rules()
    )
    # The uninstaller must NOT pin best_depth to 0; the real launcher wins.
    assert best_depth == 1
    assert [os.path.basename(p) for p in non_ignored] == ["UNDERTALE.exe"]
    assert [os.path.basename(p) for p in all_best] == ["UNDERTALE.exe"]


def test_topmost_prefers_shallowest_usable_exe(tmp_path):
    # A usable .exe at the root still wins over a deeper one (topmost rule
    # unchanged when the shallowest level already has a real launcher).
    (tmp_path / "launcher.exe").write_text("x")
    (tmp_path / "bin").mkdir()
    (tmp_path / "bin" / "engine.exe").write_text("x")

    best_depth, non_ignored, _ = scan_game_folder_topmost_exes(
        str(tmp_path), default_rules()
    )
    assert best_depth == 0
    assert [os.path.basename(p) for p in non_ignored] == ["launcher.exe"]


def test_topmost_falls_back_to_ignored_when_no_usable_exe(tmp_path):
    # Only ignore-listed exes exist: surface them (as a last resort) at their
    # own shallowest depth so the folder is still actionable in the picker.
    (tmp_path / "unins000.exe").write_text("x")
    (tmp_path / "redist").mkdir()
    (tmp_path / "redist" / "vcredist_x64.exe").write_text("x")

    best_depth, non_ignored, all_best = scan_game_folder_topmost_exes(
        str(tmp_path), default_rules()
    )
    assert best_depth == 0
    assert non_ignored == []
    assert [os.path.basename(p) for p in all_best] == ["unins000.exe"]
