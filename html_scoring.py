from __future__ import annotations
import os
import re
from typing import Tuple

def _norm(s: str) -> str:
    return re.sub(r"\s+", " ", s.strip().lower())

def score_html(html_path: str, base_title: str, rel_depth: int) -> Tuple[int, str]:
    name = os.path.basename(html_path).lower()
    stem = os.path.splitext(name)[0]
    title = _norm(base_title)

    score = 0
    reasons = []

    # Prefer topmost
    score += max(0, 25 - rel_depth * 6)
    reasons.append(f"depth {rel_depth}")

    # index.html is common entry point
    if name in ("index.html", "index.htm"):
        score += 30
        reasons.append("index")

    # Title match
    if title and title in _norm(stem):
        score += 25
        reasons.append("title match")

    # Avoid obvious docs
    bad = ["readme", "changelog", "manual", "license", "credits", "doc", "docs"]
    if any(t in name for t in bad):
        score -= 25
        reasons.append("doc-like")

    return score, ", ".join(reasons[:3])
