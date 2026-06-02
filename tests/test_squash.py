"""
Cross-platform tests for the folder-squash (flatten redundant nesting) core.
These do real filesystem moves under tmp_path (same volume) — no Qt/win32com.
"""
import os

from squash import (
    plan_squash, find_squashable, execute_squash, undo_squash, SquashConflict,
)


def _touch(path: str) -> None:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    open(path, "w").close()


def _names(dirpath: str) -> set[str]:
    return set(os.listdir(dirpath))


# --------------------------------------------------------------------------
# Planning
# --------------------------------------------------------------------------

def test_plan_none_when_already_flat(tmp_path):
    g = tmp_path / "Game"
    _touch(str(g / "game.exe"))
    assert plan_squash(str(g)) is None


def test_plan_none_when_sole_child_is_a_file(tmp_path):
    g = tmp_path / "Game"
    _touch(str(g / "only.exe"))  # one entry, but a file -> content, not a wrapper
    assert plan_squash(str(g)) is None


def test_plan_none_when_chain_ends_empty(tmp_path):
    g = tmp_path / "Game"
    (g / "Inner").mkdir(parents=True)  # single subdir, but empty -> nothing to move
    assert plan_squash(str(g)) is None


def test_plan_single_level(tmp_path):
    g = tmp_path / "Game"
    _touch(str(g / "Game" / "game.exe"))
    _touch(str(g / "Game" / "data.txt"))
    plan = plan_squash(str(g))
    assert plan is not None
    assert plan.levels == 1
    assert plan.chain_names == ["Game"]
    assert plan.entries == ["data.txt", "game.exe"]


def test_plan_multi_level_stops_at_content(tmp_path):
    g = tmp_path / "Game"
    _touch(str(g / "A" / "B" / "game.exe"))
    _touch(str(g / "A" / "B" / "readme.txt"))
    plan = plan_squash(str(g))
    assert plan.levels == 2
    assert plan.chain_names == ["A", "B"]
    assert plan.content_folder == str(g / "A" / "B")


# --------------------------------------------------------------------------
# Execution
# --------------------------------------------------------------------------

def test_execute_dry_run_mutates_nothing(tmp_path):
    g = tmp_path / "Game"
    _touch(str(g / "Game" / "game.exe"))
    plan = plan_squash(str(g))
    rec = execute_squash(plan, dry_run=True)
    assert rec["applied"] is False
    assert _names(str(g)) == {"Game"}  # untouched


def test_execute_single_level_flattens(tmp_path):
    g = tmp_path / "Game"
    _touch(str(g / "Game" / "game.exe"))
    _touch(str(g / "Game" / "data" / "x.dat"))
    execute_squash(plan_squash(str(g)))
    assert _names(str(g)) == {"game.exe", "data"}
    assert (g / "data" / "x.dat").exists()


def test_execute_multi_level_flattens(tmp_path):
    g = tmp_path / "Game"
    _touch(str(g / "A" / "B" / "game.exe"))
    _touch(str(g / "A" / "B" / "readme.txt"))
    execute_squash(plan_squash(str(g)))
    assert _names(str(g)) == {"game.exe", "readme.txt"}
    assert not (g / "A").exists()


def test_execute_handles_entry_named_like_wrapper(tmp_path):
    # The classic Game/Game/Game pitfall: a moved entry shares the wrapper name.
    g = tmp_path / "Game"
    _touch(str(g / "Game" / "game.exe"))
    (g / "Game" / "Game").mkdir()           # inner dir named exactly "Game"
    _touch(str(g / "Game" / "Game" / "asset.dat"))
    execute_squash(plan_squash(str(g)))
    assert _names(str(g)) == {"game.exe", "Game"}
    assert (g / "Game" / "asset.dat").exists()  # inner Game preserved, not clobbered


def test_execute_never_overwrites(tmp_path):
    # If the destination already holds a colliding name, abort rather than clobber.
    g = tmp_path / "Game"
    _touch(str(g / "Game" / "keep.txt"))
    plan = plan_squash(str(g))
    # Sneak a colliding file into the top folder after planning.
    plan.entries = ["keep.txt"]
    os.rename(str(g / "Game"), str(g / "Game2"))   # detach
    plan.content_folder = str(g / "Game2")
    plan.chain = [str(g / "Game2")]
    _touch(str(g / "keep.txt"))                    # pre-existing collision at top
    try:
        execute_squash(plan)
        assert False, "expected SquashConflict"
    except SquashConflict:
        pass
    assert (g / "keep.txt").exists()  # original untouched


# --------------------------------------------------------------------------
# Undo round-trip
# --------------------------------------------------------------------------

def test_undo_restores_multi_level(tmp_path):
    g = tmp_path / "Game"
    _touch(str(g / "A" / "B" / "game.exe"))
    _touch(str(g / "A" / "B" / "readme.txt"))
    rec = execute_squash(plan_squash(str(g)))
    assert _names(str(g)) == {"game.exe", "readme.txt"}

    assert undo_squash(rec) is True
    assert _names(str(g)) == {"A"}
    assert (g / "A" / "B" / "game.exe").exists()
    assert (g / "A" / "B" / "readme.txt").exists()


def test_undo_noop_for_dry_run_record(tmp_path):
    g = tmp_path / "Game"
    _touch(str(g / "Game" / "game.exe"))
    rec = execute_squash(plan_squash(str(g)), dry_run=True)
    assert undo_squash(rec) is False


# --------------------------------------------------------------------------
# find_squashable
# --------------------------------------------------------------------------

def test_find_squashable_only_nested(tmp_path):
    _touch(str(tmp_path / "Flat" / "game.exe"))            # already flat -> no plan
    _touch(str(tmp_path / "Nested" / "Nested" / "g.exe"))  # redundant -> plan
    _touch(str(tmp_path / "loose.txt"))                    # not a dir -> ignored
    plans = find_squashable(str(tmp_path))
    assert [os.path.basename(p.game_folder) for p in plans] == ["Nested"]
