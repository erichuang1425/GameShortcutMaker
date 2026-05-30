"""
Recursive "collection of games" detection.

A folder under the game root is usually a single game, but it may instead be a
*collection*: a folder whose subfolders are each games. When that happens we
want to mirror the source structure in the output dir (a collection becomes an
output subfolder of shortcuts) rather than collapsing it into one ambiguous
shortcut.

This module is intentionally pure and side-effect-free (it only reads the
filesystem and the injected ignore-rules), so the classification logic can be
unit-tested cross-platform without Qt or win32com.

Classification of a folder:
  * GAME       - has a launcher directly inside it (a non-ignored .exe, or an
                 HTML entry point such as index.html), OR has 1..N-1
                 launcher-bearing descendants (a single game whose launcher
                 lives a level or two down).
  * COLLECTION - has at least `threshold_n` immediate subfolders that are
                 themselves games/collections (and they are not all the same
                 game under arch/version variant folders).
  * EMPTY      - no usable launcher (non-ignored executable or qualifying HTML
                 entry point) anywhere in its subtree.
"""
from __future__ import annotations

import os
import re
from dataclasses import dataclass, field
from enum import Enum

from rules import is_ignored
from versioning import strip_version_from_title
from html_scoring import score_html

DEFAULT_THRESHOLD = 3
DEFAULT_MAX_DEPTH = 6

# An HTML file counts as a launcher when it scores at least this much (mirrors
# the HTML fallback threshold in app.py, so index.html qualifies but readme.html
# does not). Keeps collections of HTML-only games detectable.
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


def _variant_title(name: str) -> str:
    """Folder name reduced to a comparable game title (version + arch stripped)."""
    base = strip_version_from_title(name).lower()
    for tok in _ARCH_TOKENS:
        base = base.replace(tok, " ")
    return re.sub(r"\s+", " ", base).strip()


def _has_direct_exe(dirpath: str, filenames: list[str], rules: dict) -> bool:
    return any(
        fn.lower().endswith(".exe") and not is_ignored(os.path.join(dirpath, fn), rules)
        for fn in filenames
    )


def _has_direct_html_launcher(dirpath: str, filenames: list[str]) -> bool:
    title = strip_version_from_title(os.path.basename(dirpath) or dirpath)
    for fn in filenames:
        lf = fn.lower()
        if lf.endswith(".html") or lf.endswith(".htm"):
            score, _ = score_html(os.path.join(dirpath, fn), title, 0)
            if score >= HTML_LAUNCHER_THRESHOLD:
                return True
    return False


def _build_index(root: str, rules: dict):
    """
    Single os.walk of `root`. Returns (direct, children, subtree_launcher):
      direct[dir]           -> True if a launcher (non-ignored .exe or qualifying
                               HTML entry point) sits directly in dir
      children[dir]         -> list of immediate subdir paths
      subtree_launcher[dir] -> True if a launcher exists anywhere in dir's subtree
    """
    direct: dict[str, bool] = {}
    children: dict[str, list[str]] = {}

    for dirpath, dirnames, filenames in os.walk(root):
        direct[dirpath] = (
            _has_direct_exe(dirpath, filenames, rules)
            or _has_direct_html_launcher(dirpath, filenames)
        )
        children[dirpath] = [os.path.join(dirpath, d) for d in dirnames]

    # Propagate "has launcher" up the tree, deepest dirs first (children before parents).
    subtree_launcher: dict[str, bool] = {}
    for dirpath in sorted(direct, key=lambda p: p.count(os.sep), reverse=True):
        has = direct[dirpath] or any(subtree_launcher.get(c, False) for c in children.get(dirpath, []))
        subtree_launcher[dirpath] = has

    return direct, children, subtree_launcher


def classify_tree(
    folder: str,
    rules: dict,
    threshold_n: int = DEFAULT_THRESHOLD,
    max_depth: int = DEFAULT_MAX_DEPTH,
) -> FolderNode:
    """Classify `folder` and (for collections) its game-bearing descendants."""
    direct, children, subtree_launcher = _build_index(folder, rules)

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

        # Collection only if there are enough *distinct* games (not arch/version
        # variants of a single game collapsing together).
        distinct = len({_variant_title(n.name) for n in game_kids})
        if len(game_kids) >= threshold_n and distinct >= threshold_n:
            return FolderNode(path, name, FolderKind.COLLECTION, children=game_kids)

        if subtree_launcher.get(path, False):
            return FolderNode(path, name, FolderKind.GAME)
        return FolderNode(path, name, FolderKind.EMPTY)

    return classify(folder, 0)


def flatten_games(node: FolderNode, rel_prefix: str, collection_name: str, out: list) -> None:
    """
    Walk a classified tree into (game_folder, rel_output_subdir, collection_name)
    tuples. Collection folders themselves produce no shortcut; their game/collection
    children are emitted under the mirrored subpath. GAME and (top-level) EMPTY
    nodes are emitted so empty folders still surface in review as errors.
    """
    if node.kind == FolderKind.COLLECTION:
        from shortcut_manager import safe_path_segment

        seg = safe_path_segment(node.name)
        child_prefix = f"{rel_prefix}/{seg}" if rel_prefix else seg
        coll = collection_name or node.name
        for child in node.children:
            flatten_games(child, child_prefix, coll, out)
    else:
        out.append((node.path, rel_prefix, collection_name))


def iter_game_targets(
    game_root: str,
    rules: dict,
    threshold_n: int = DEFAULT_THRESHOLD,
    max_depth: int = DEFAULT_MAX_DEPTH,
) -> list[tuple[str, str, str]]:
    """
    Classify each immediate subfolder of `game_root` and return a flat list of
    (game_folder, rel_output_subdir, collection_name). rel_output_subdir is
    POSIX-style and "" for top-level games.
    """
    from scanner import list_game_folders

    out: list[tuple[str, str, str]] = []
    for top in list_game_folders(game_root):
        node = classify_tree(top, rules, threshold_n, max_depth)
        flatten_games(node, "", "", out)
    return out
