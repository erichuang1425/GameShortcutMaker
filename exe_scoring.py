from __future__ import annotations
import os
import re
from typing import Tuple

_BAD_TOKENS = [
    "unins", "uninstall", "setup", "install", "config", "helper", "crash",
    "handler", "vcredist", "dxsetup", "dotnet", "cef", "server", "dedicated",
    "editor", "tool", "patch"
]

_GOOD_TOKENS = [
    "launcher", "game", "client", "win64", "x64", "shipping"
]


def _norm(s: str) -> str:
    return re.sub(r"\s+", " ", s.strip().lower())


def score_exe(
    exe_path: str,
    base_title: str,
    rel_depth: int,
) -> Tuple[int, str]:
    """
    Returns (score, short_reason).
    Higher score = more likely to be the right launcher.
    """
    name = os.path.basename(exe_path).lower()
    title = _norm(base_title)

    score = 0
    reasons = []

    # Depth: topmost wins
    score += max(0, 30 - rel_depth * 6)
    reasons.append(f"depth {rel_depth}")

    # Title match
    if title and title in _norm(os.path.splitext(name)[0]):
        score += 25
        reasons.append("title match")

    # Good/bad tokens
    for t in _GOOD_TOKENS:
        if t in name:
            score += 6
    for t in _BAD_TOKENS:
        if t in name:
            score -= 12

    # Penalize obvious installer patterns
    if name.endswith("setup.exe") or name.startswith("setup"):
        score -= 30
        reasons.append("installer-like")

    # Prefer larger binaries (soft signal)
    try:
        size = os.path.getsize(exe_path)
        if size > 200 * 1024 * 1024:
            score += 10
        elif size > 50 * 1024 * 1024:
            score += 6
        elif size < 5 * 1024 * 1024:
            score -= 6
    except Exception:
        pass

    return score, ", ".join(reasons[:3])
