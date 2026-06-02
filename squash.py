"""
Squash (flatten) redundant single-child folder nesting inside a game folder.

Downloaded / extracted games often arrive wrapped in redundant directory
levels: ``Game/Game/v1.2/<real files>`` where each wrapper holds *only* the next
folder and nothing else. This module detects such pure single-child chains and
collapses them, pulling the real content up into the top game folder (whose name
is the game's identity and is always kept).

Design (chosen by the user):
  * Acts on the source game files.
  * "Single-child chains only": a level is collapsed only when it contains
    exactly one entry, a subdirectory — so nothing can ever be lost.
  * Manual, preview-first, with an undo record.

Everything moves *within* the game folder (same volume), so each move is an
instant rename rather than a copy — fast by construction, no cross-volume copy
path to worry about. This module is pure/side-effect-free except for the
explicit `execute_squash` / `undo_squash`, so the planning logic is unit-testable
cross-platform without Qt or win32com.
"""
from __future__ import annotations

import os
import shutil
from dataclasses import dataclass, field


@dataclass
class SquashPlan:
    """A planned flatten of one game folder.

    `chain` is the redundant wrapper dirs, top-most first: game_folder's sole
    subdir, then its sole subdir, ... down to and including `content_folder`
    (the deepest folder, which holds the real content). `entries` are the names
    in `content_folder` that will be moved up into `game_folder`.
    """
    game_folder: str
    content_folder: str
    chain: list[str] = field(default_factory=list)
    entries: list[str] = field(default_factory=list)

    @property
    def levels(self) -> int:
        """How many redundant directory levels are collapsed."""
        return len(self.chain)

    @property
    def chain_names(self) -> list[str]:
        """Wrapper basenames, top-most first (used to rebuild on undo)."""
        return [os.path.basename(d) for d in self.chain]


def _sole_subdir(dirpath: str) -> str | None:
    """Return the single child directory of `dirpath`, or None.

    None unless `dirpath` contains exactly one entry and that entry is a real
    subdirectory (not a file and not a symlink/junction — following links could
    escape the tree or loop).
    """
    try:
        entries = os.listdir(dirpath)
    except OSError:
        return None
    if len(entries) != 1:
        return None
    child = os.path.join(dirpath, entries[0])
    if os.path.islink(child) or not os.path.isdir(child):
        return None
    return child


def plan_squash(game_folder: str) -> SquashPlan | None:
    """Plan a flatten for one game folder, or None if nothing to do.

    Descends the single-child chain from `game_folder`; the deepest folder is the
    content folder. Returns None when the top folder is already content-bearing
    (not a sole-subdir wrapper) or the chain bottoms out in an empty folder
    (nothing to move).
    """
    chain: list[str] = []
    current = game_folder
    while True:
        child = _sole_subdir(current)
        if child is None:
            break
        chain.append(child)
        current = child

    if not chain:
        return None  # game_folder holds content directly — already flat

    content = current
    try:
        entries = sorted(os.listdir(content))
    except OSError:
        return None
    if not entries:
        return None  # chain ends in an empty folder — nothing to pull up

    return SquashPlan(game_folder=game_folder, content_folder=content,
                      chain=chain, entries=entries)


def find_squashable(game_root: str) -> list[SquashPlan]:
    """Plan a flatten for every immediate game folder under `game_root`.

    Only folders that actually have redundant nesting yield a plan. Cheap: it
    only lists directories along thin single-child chains, never a deep walk.
    """
    plans: list[SquashPlan] = []
    try:
        names = sorted(os.listdir(game_root), key=str.lower)
    except OSError:
        return plans
    for name in names:
        gf = os.path.join(game_root, name)
        if not os.path.isdir(gf) or os.path.islink(gf):
            continue
        plan = plan_squash(gf)
        if plan is not None:
            plans.append(plan)
    return plans


def _unique_sibling(path: str, suffix: str) -> str:
    """A non-existent path beside `path` (same parent, hence same volume)."""
    ap = os.path.abspath(path)
    parent = os.path.dirname(ap)
    base = os.path.basename(ap) + suffix
    cand = os.path.join(parent, base)
    i = 1
    while os.path.exists(cand):
        cand = os.path.join(parent, f"{base}{i}")
        i += 1
    return cand


class SquashConflict(Exception):
    """Raised when a moved entry would overwrite something in the game folder."""


def execute_squash(plan: SquashPlan, dry_run: bool = False) -> dict:
    """Flatten one game folder per `plan`. Returns an undo record.

    Steps (all same-volume, so instant renames):
      1. Detach the content folder to a temp sibling of the game folder, so the
         wrapper chain can be removed and moved entries can never collide with a
         wrapper's name.
      2. Remove the now-empty wrapper chain.
      3. Move the content's entries up into the game folder. Never overwrites:
         a pre-existing destination raises SquashConflict.
      4. Remove the empty temp folder.

    The undo record carries everything `undo_squash` needs to rebuild the
    original nesting. A dry run mutates nothing and returns a record with
    ``"applied": False``.
    """
    record = {
        "game_folder": plan.game_folder,
        "chain_names": plan.chain_names,
        "entries": list(plan.entries),
        "levels": plan.levels,
        "applied": False,
    }
    if dry_run or not plan.entries:
        return record

    top = plan.game_folder
    content = plan.content_folder
    first_wrapper = plan.chain[0]

    tmp = _unique_sibling(top, ".__squash_tmp__")
    os.rename(content, tmp)  # same volume -> instant; detaches real content

    # The wrapper chain is now empty. When the chain was a single level the
    # content *was* that wrapper (already moved to tmp), so there is nothing left
    # to remove; otherwise remove the chain from its top wrapper down.
    if plan.levels > 1:
        shutil.rmtree(first_wrapper)

    try:
        for name in plan.entries:
            src = os.path.join(tmp, name)
            dst = os.path.join(top, name)
            if os.path.exists(dst):
                raise SquashConflict(dst)
            shutil.move(src, dst)
    finally:
        # Best-effort: drop the temp dir if (and only if) it is now empty. If a
        # conflict left items behind, leave it so the user can recover them.
        try:
            os.rmdir(tmp)
        except OSError:
            pass

    record["applied"] = True
    return record


def undo_squash(record: dict) -> bool:
    """Reverse one `execute_squash`, rebuilding the original nesting.

    Recreates ``game_folder/<chain...>`` and moves the recorded entries back into
    the deepest folder. Returns True if it ran (and at least attempted moves),
    False if the record was never applied or is unusable. Never overwrites.
    """
    if not record.get("applied"):
        return False
    top = record.get("game_folder", "")
    chain_names = record.get("chain_names", [])
    entries = record.get("entries", [])
    if not top or not chain_names or not os.path.isdir(top):
        return False

    content = top
    for nm in chain_names:
        content = os.path.join(content, nm)
    os.makedirs(content, exist_ok=True)

    for name in entries:
        src = os.path.join(top, name)
        dst = os.path.join(content, name)
        if os.path.exists(src) and not os.path.exists(dst):
            shutil.move(src, dst)
    return True
