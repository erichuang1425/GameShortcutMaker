from __future__ import annotations
import re

_VERSION_RE = re.compile(r"(?i)(?:\bv)?(\d+(?:\.\d+)+)\b")


def extract_version(name: str) -> tuple[str, tuple[int, ...]]:
    matches = list(_VERSION_RE.finditer(name))
    if not matches:
        return "", tuple()

    vstr = matches[-1].group(1)
    parts = []
    for p in vstr.split("."):
        try:
            parts.append(int(p))
        except ValueError:
            return vstr, tuple()
    return vstr, tuple(parts)


def strip_version_from_title(name: str) -> str:
    cleaned = _VERSION_RE.sub("", name)
    cleaned = cleaned.replace("_", " ").replace("-", " ")
    cleaned = cleaned.strip().strip(" ._-()[]{}")
    cleaned = re.sub(r"\s{2,}", " ", cleaned).strip()
    return cleaned if cleaned else name.strip()


def compare_versions(a: tuple[int, ...], b: tuple[int, ...]) -> int:
    if not a and not b:
        return 0
    if a and not b:
        return 1
    if not a and b:
        return -1

    n = max(len(a), len(b))
    aa = list(a) + [0] * (n - len(a))
    bb = list(b) + [0] * (n - len(b))

    for x, y in zip(aa, bb):
        if x > y:
            return 1
        if x < y:
            return -1
    return 0
