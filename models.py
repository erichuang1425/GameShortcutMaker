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

    exe_candidates: List[ExeCandidate] = field(default_factory=list)
    html_candidates: List[str] = field(default_factory=list)
    chosen_exe: str = ""
    recommended_exe: str = ""
    target_type: str = "exe"

    existing_shortcut_path: str = ""
    existing_version_str: str = ""
    existing_version_tuple: tuple[int, ...] = tuple()
    existing_target: str = ""

    decision: ItemDecision = ItemDecision.SKIP
    detail: str = ""
    selected: bool = True

    force_replace: bool = False
