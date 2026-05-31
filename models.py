from __future__ import annotations
from dataclasses import dataclass, field
from enum import Enum
from typing import List


class ItemDecision(str, Enum):
    CREATE = "create"
    SKIP = "skip"
    REPLACE = "replace"
    NEEDS_RESOLVE = "needs_resolve"
    ERROR = "error"


@dataclass
class ExeCandidate:
    path: str
    score: int = 0
    size_bytes: int = 0
    mtime: float = 0.0
    reason: str = ""  # short scoring explanation


@dataclass
class ScanItem:
    game_folder: str
    folder_name: str

    base_title: str
    version_str: str
    version_tuple: tuple[int, ...]

    # Output location (relative to the output root), POSIX-style.
    # "" => flat top-level game; "RenPyCollection" or "Outer/Inner" => collection member.
    rel_output_subdir: str = ""
    collection_name: str = ""

    exe_candidates: List[ExeCandidate] = field(default_factory=list)
    html_candidates: List[str] = field(default_factory=list)
    chosen_exe: str = ""
    recommended_exe: str = ""
    target_type: str = "exe"

    # Collection support.
    # `is_collection` marks an unresolved collection-root item: the user confirms
    # (or rejects) the grouping in the picker. `collection_members` holds the
    # prebuilt member ScanItems to splice in when confirmed as a collection.
    # `collection_root` is set on expanded member/launcher items so the whole
    # group can be regrouped or overridden later.
    is_collection: bool = False
    collection_members: list = field(default_factory=list)
    collection_root: str = ""

    existing_shortcut_path: str = ""
    existing_version_str: str = ""
    existing_version_tuple: tuple[int, ...] = tuple()
    existing_target: str = ""

    decision: ItemDecision = ItemDecision.SKIP
    detail: str = ""
    selected: bool = True

    force_replace: bool = False
