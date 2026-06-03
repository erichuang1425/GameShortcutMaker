"""
Recursive "collection of games" detection.

A folder under the game root is usually a single game, but it may instead be a
*collection*: a folder whose subfolders are each games (or that holds many
games one level down). When that happens we want to mirror the source structure
in the output dir (a collection becomes an output subfolder of shortcuts) rather
than collapsing it into one ambiguous shortcut.

This module is intentionally pure and side-effect-free (it only reads the
filesystem and the injected ignore-rules), so the classification logic can be
unit-tested cross-platform without Qt or win32com.

Classification of a folder:
  * GAME       - has a launcher directly inside it (a non-ignored .exe, a .swf
                 Flash file, or an HTML entry point such as index.html), OR has
                 1..N-1 launcher-bearing descendants (a single game whose
                 launcher lives a level or two down).
  * COLLECTION - has at least `threshold_n` immediate subfolders that are
                 themselves games/collections (and they are not all the same
                 game under arch/version variant folders), OR holds at least one
                 nested collection. A folder that wraps already-detected
                 collections is itself a collection even when it has fewer than
                 `threshold_n` immediate children, so the nested grouping is
                 mirrored into output subfolders instead of being collapsed into
                 a single shortcut (which would lose every game beneath it).
  * EMPTY      - no usable launcher (non-ignored executable, .swf, or qualifying
                 HTML entry point) anywhere in its subtree.

Performance: a single os.walk per top-level folder feeds BOTH the
classification and the per-game executable list (see `scan_targets`). The walk
is pruned below the first non-ignored .exe in a branch — that is the topmost
launcher level a game cares about, and `classify()` returns GAME there without
inspecting descendants — so an exe game's deep asset tree is never walked. This
replaces the old two-pass approach (classify-walk + a second per-game walk),
which traversed every game folder twice.

The walk is deliberately NOT pruned at an HTML launcher: because the scan
prefers a real .exe over an HTML entry point, it must keep descending to find a
buried .exe. So a launcher-less / HTML-only folder is still walked in full (the
same total work the old per-folder scan did for it) to prove no .exe exists.
"""
from __future__ import annotations

import os
import re
from dataclasses import dataclass, field
from enum import Enum

from rules import is_ignored
from versioning import strip_version_from_title
from html_scoring import score_html
from scanner import safe_walk, _rel_depth, list_game_folders
from shortcut_manager import safe_path_segment

DEFAULT_THRESHOLD = 3
DEFAULT_MAX_DEPTH = 6

# An HTML file counts as a launcher when it scores at least this much (mirrors
# the HTML fallback threshold in the scan worker, so index.html qualifies but
# readme.html does not). Keeps collections of HTML-only games detectable.
HTML_LAUNCHER_THRESHOLD = 40

# Tokens that distinguish architecture variants of the *same* game.
_ARCH_TOKENS = [
    "x86_64", "amd64", "x86", "x64", "win64", "win32",
    "64bit", "32bit", "64 bit", "32 bit", "(64)", "(32)",
]


class FolderKind(str, Enum):
    GAME = "game"
    COLLECTION = "collection"
    EMPTY = "empty"


@dataclass
class FolderNode:
    path: str
    name: str
    kind: FolderKind
    children: list["FolderNode"] = field(default_factory=list)


@dataclass
class GameTarget:
    """One resolved scan target.

    For a plain game `is_collection` is False and `best_depth/non_ignored_exes/
    all_exes` describe the topmost .exe level (same contract as
    scanner.scan_game_folder_topmost_exes). For a collection root `is_collection`
    is True and `members` holds the flattened game/empty descendants (each its
    own GameTarget with a mirrored `rel_output_subdir`); the root's own exe
    fields then describe the shallowest sub-exes, used only if the user collapses
    the collection back into a single game.
    """
    path: str
    rel_output_subdir: str = ""
    collection_name: str = ""
    best_depth: int = -1
    non_ignored_exes: list[str] = field(default_factory=list)
    all_exes: list[str] = field(default_factory=list)
    is_collection: bool = False
    members: list["GameTarget"] = field(default_factory=list)


def _variant_title(name: str) -> str:
    """Folder name reduced to a comparable game title (version + arch stripped)."""
    base = strip_version_from_title(name).lower()
    for tok in _ARCH_TOKENS:
        base = base.replace(tok, " ")
    return re.sub(r"\s+", " ", base).strip()


def _has_direct_html_launcher(dirpath: str, filenames: list[str]) -> bool:
    title = strip_version_from_title(os.path.basename(dirpath) or dirpath)
    for fn in filenames:
        lf = fn.lower()
        if lf.endswith(".html") or lf.endswith(".htm"):
            score, _ = score_html(os.path.join(dirpath, fn), title, 0)
            if score >= HTML_LAUNCHER_THRESHOLD:
                return True
    return False


def _has_direct_swf(filenames: list[str]) -> bool:
    """A .swf sitting directly in a folder makes it a (Flash) game launcher.

    Flash games have no .exe, so without this a folder whose only launcher is a
    .swf would classify as EMPTY and a collection of such games would not be
    detected. Any .swf qualifies (unlike HTML, which is score-gated to skip
    readme/manual pages) because a .swf is always game content, never docs.
    """
    return any(fn.lower().endswith(".swf") for fn in filenames)


def _build_index(root: str, rules: dict, max_depth: int = DEFAULT_MAX_DEPTH, progress_cb=None):
    """
    Single os.walk of `root`. Returns (direct, children, subtree_launcher, exes_by_dir):
      direct[dir]           -> True if a launcher (non-ignored .exe, a .swf, or a
                               qualifying HTML entry point) sits directly in dir
      children[dir]         -> list of immediate subdir paths
      subtree_launcher[dir] -> True if a launcher exists anywhere in dir's subtree
      exes_by_dir[dir]      -> full paths of every .exe (ignored or not) in dir

    The walk stops descending below the first non-ignored .exe in a branch: that
    is the topmost launcher level a game cares about, and classify() returns GAME
    there without inspecting descendants. HTML-only and ignored-only directories
    are still descended into, so a deeper .exe (which the picker prefers over
    HTML) is never missed. `progress_cb`, if given, fires once per visited dir.

    `max_depth` bounds how deep classify() looks for *collections*; the walk
    itself is not depth-capped, so a game's topmost .exe is always found
    regardless of nesting (matching the legacy per-folder scan).
    """
    direct: dict[str, bool] = {}
    children: dict[str, list[str]] = {}
    exes_by_dir: dict[str, list[str]] = {}

    for dirpath, dirnames, filenames in safe_walk(root):
        if progress_cb is not None:
            progress_cb(dirpath)

        exes = [os.path.join(dirpath, fn) for fn in filenames if fn.lower().endswith(".exe")]
        if exes:
            exes_by_dir[dirpath] = exes

        has_exe = any(not is_ignored(p, rules) for p in exes)
        direct[dirpath] = (
            has_exe
            or _has_direct_swf(filenames)
            or _has_direct_html_launcher(dirpath, filenames)
        )
        children[dirpath] = [os.path.join(dirpath, d) for d in dirnames]

        if has_exe:
            # Topmost launcher for this branch found; classify() returns GAME here
            # without looking below, so stop descending (skips deep asset trees).
            dirnames[:] = []

    # Propagate "has launcher" up the tree, deepest dirs first (children before parents).
    subtree_launcher: dict[str, bool] = {}
    for dirpath in sorted(direct, key=lambda p: p.count(os.sep), reverse=True):
        has = direct[dirpath] or any(subtree_launcher.get(c, False) for c in children.get(dirpath, []))
        subtree_launcher[dirpath] = has

    return direct, children, subtree_launcher, exes_by_dir


def _classify_from_index(folder, direct, children, subtree_launcher, threshold_n, max_depth) -> FolderNode:
    """Classify `folder` and its descendants from a prebuilt index."""

    def classify(path: str, depth: int) -> FolderNode:
        name = os.path.basename(path) or path
        # A launcher sitting directly here makes this a single game; don't recurse.
        if direct.get(path, False):
            return FolderNode(path, name, FolderKind.GAME)

        if depth >= max_depth:
            kind = FolderKind.GAME if subtree_launcher.get(path, False) else FolderKind.EMPTY
            return FolderNode(path, name, kind)

        child_nodes = [classify(c, depth + 1) for c in children.get(path, [])]
        game_kids = [n for n in child_nodes if n.kind in (FolderKind.GAME, FolderKind.COLLECTION)]

        # Collection if there are enough *distinct* games (not arch/version
        # variants of a single game collapsing together) OR if a child is itself
        # a collection. The latter keeps a folder that merely groups already-
        # detected collections (e.g. Library/{PackA,PackB}, each a collection)
        # from being flattened into one shortcut just because it has fewer than
        # threshold_n immediate children — that would discard every nested game.
        distinct = len({_variant_title(n.name) for n in game_kids})
        enough_distinct_games = len(game_kids) >= threshold_n and distinct >= threshold_n
        has_collection_child = any(n.kind == FolderKind.COLLECTION for n in child_nodes)
        if game_kids and (enough_distinct_games or has_collection_child):
            return FolderNode(path, name, FolderKind.COLLECTION, children=game_kids)

        if subtree_launcher.get(path, False):
            return FolderNode(path, name, FolderKind.GAME)
        return FolderNode(path, name, FolderKind.EMPTY)

    return classify(folder, 0)


def classify_tree(
    folder: str,
    rules: dict,
    threshold_n: int = DEFAULT_THRESHOLD,
    max_depth: int = DEFAULT_MAX_DEPTH,
    progress_cb=None,
) -> FolderNode:
    """Classify `folder` and (for collections) its game-bearing descendants."""
    direct, children, subtree_launcher, _exes = _build_index(folder, rules, max_depth, progress_cb)
    return _classify_from_index(folder, direct, children, subtree_launcher, threshold_n, max_depth)


def _topmost_exes_for(node_path: str, exes_by_dir: dict[str, list[str]], rules: dict):
    """Topmost .exe level under `node_path`, from the prebuilt index.

    Mirrors scanner.scan_game_folder_topmost_exes exactly (same depth/sort/ignore
    semantics) but reads the walk's recorded exe paths instead of walking again.
    Returns (best_depth, non_ignored_at_best, all_at_best); best_depth is -1 when
    no .exe exists under the node.
    """
    prefix = node_path.rstrip(os.sep) + os.sep
    by_depth: dict[int, list[str]] = {}
    non_ignored_by_depth: dict[int, list[str]] = {}

    for d, exes in exes_by_dir.items():
        if d != node_path and not d.startswith(prefix):
            continue
        depth = _rel_depth(node_path, d)
        for full in exes:
            by_depth.setdefault(depth, []).append(full)
            if not is_ignored(full, rules):
                non_ignored_by_depth.setdefault(depth, []).append(full)

    if not by_depth:
        return -1, [], []

    # Same depth rule as scanner.scan_game_folder_topmost_exes: prefer the
    # shallowest depth with a usable (non-ignored) .exe so an uninstaller/setup
    # above the real launcher can't shadow it; fall back to the shallowest
    # ignore-listed depth only when nothing usable exists.
    src = non_ignored_by_depth or by_depth
    best_depth = min(src)
    all_best = sorted(by_depth.get(best_depth, []), key=lambda p: os.path.basename(p).lower())
    non_ignored_best = sorted(non_ignored_by_depth.get(best_depth, []), key=lambda p: os.path.basename(p).lower())
    return best_depth, non_ignored_best, all_best


def _collect_members(
    node: FolderNode,
    rel_prefix: str,
    collection_name: str,
    exes_by_dir: dict,
    rules: dict,
    out: list,
) -> None:
    """Flatten a classified collection tree into member GameTargets.

    Collection folders produce no target of their own; their game/collection
    children are emitted under the mirrored subpath. GAME and EMPTY leaves are
    emitted (empty folders still surface in review as errors).
    """
    if node.kind == FolderKind.COLLECTION:
        seg = safe_path_segment(node.name)
        child_prefix = f"{rel_prefix}/{seg}" if rel_prefix else seg
        coll = collection_name or node.name
        for child in node.children:
            _collect_members(child, child_prefix, coll, exes_by_dir, rules, out)
    else:
        bd, ni, ab = _topmost_exes_for(node.path, exes_by_dir, rules)
        out.append(GameTarget(node.path, rel_prefix, collection_name,
                              best_depth=bd, non_ignored_exes=ni, all_exes=ab))


def scan_targets(
    game_root: str,
    rules: dict,
    threshold_n: int = DEFAULT_THRESHOLD,
    max_depth: int = DEFAULT_MAX_DEPTH,
    progress_cb=None,
) -> list[GameTarget]:
    """Classify each immediate subfolder of `game_root` into a GameTarget.

    A single os.walk per top-level folder powers both classification and the
    per-game executable list. `progress_cb`, if given, fires once per directory
    visited (for live scan progress).
    """
    out: list[GameTarget] = []
    for top in list_game_folders(game_root):
        direct, children, subtree_launcher, exes_by_dir = _build_index(top, rules, max_depth, progress_cb)
        node = _classify_from_index(top, direct, children, subtree_launcher, threshold_n, max_depth)
        bd, ni, ab = _topmost_exes_for(top, exes_by_dir, rules)

        if node.kind == FolderKind.COLLECTION:
            members: list[GameTarget] = []
            _collect_members(node, "", "", exes_by_dir, rules, members)
            out.append(GameTarget(top, "", node.name, best_depth=bd, non_ignored_exes=ni,
                                  all_exes=ab, is_collection=True, members=members))
        else:
            out.append(GameTarget(top, "", "", best_depth=bd, non_ignored_exes=ni, all_exes=ab))
    return out


def iter_game_targets(
    game_root: str,
    rules: dict,
    threshold_n: int = DEFAULT_THRESHOLD,
    max_depth: int = DEFAULT_MAX_DEPTH,
    progress_cb=None,
) -> list[tuple[str, str, str]]:
    """
    Flat list of (game_folder, rel_output_subdir, collection_name) with
    collections expanded into their members. rel_output_subdir is POSIX-style
    and "" for top-level games. Kept as a thin view over `scan_targets` for
    callers/tests that only need the folder->output mapping.
    """
    out: list[tuple[str, str, str]] = []
    for t in scan_targets(game_root, rules, threshold_n, max_depth, progress_cb):
        if t.is_collection:
            out.extend((m.path, m.rel_output_subdir, m.collection_name) for m in t.members)
        else:
            out.append((t.path, t.rel_output_subdir, t.collection_name))
    return out
