from __future__ import annotations
import logging
import os
from typing import List, Tuple

from rules import is_ignored
from models import ExeCandidate
from exe_scoring import score_exe

logger = logging.getLogger(__name__)


def _log_walk_error(exc: OSError) -> None:
    """os.walk onerror handler: report and continue.

    The default os.walk (onerror=None) silently swallows OSError, so a single
    unreadable folder (permissions, path too long) would drop its whole subtree
    from the scan with no feedback. Logging keeps that visible.
    """
    logger.warning("Skipping unreadable path during scan: %s", exc)


def safe_walk(top: str, onerror=_log_walk_error):
    """os.walk that surfaces unreadable directories instead of dropping them."""
    return os.walk(top, onerror=onerror)


def list_game_folders(game_root: str) -> list[str]:
    out = []
    for name in sorted(os.listdir(game_root), key=str.lower):
        p = os.path.join(game_root, name)
        if os.path.isdir(p):
            out.append(p)
    return out


def _rel_depth(game_folder: str, dirpath: str) -> int:
    rel = os.path.relpath(dirpath, game_folder)
    return 0 if rel == "." else rel.count(os.sep) + 1


def scan_game_folder_topmost_exes(game_folder: str, rules: dict) -> Tuple[int, List[str], List[str]]:
    """
    Returns:
      (best_depth, non_ignored_exes_at_best_depth, all_exes_at_best_depth)
    best_depth is the smallest depth where any exe exists (or -1 if none).
    """
    all_by_depth: dict[int, list[str]] = {}
    non_ignored_by_depth: dict[int, list[str]] = {}

    for dirpath, _, filenames in safe_walk(game_folder):
        depth = _rel_depth(game_folder, dirpath)
        for fn in filenames:
            if fn.lower().endswith(".exe"):
                full = os.path.join(dirpath, fn)
                all_by_depth.setdefault(depth, []).append(full)
                if not is_ignored(full, rules):
                    non_ignored_by_depth.setdefault(depth, []).append(full)

    if not all_by_depth:
        return -1, [], []

    best_depth = min(all_by_depth.keys())
    all_best = sorted(all_by_depth[best_depth], key=lambda p: os.path.basename(p).lower())
    non_ignored_best = sorted(non_ignored_by_depth.get(best_depth, []), key=lambda p: os.path.basename(p).lower())
    return best_depth, non_ignored_best, all_best


def build_candidates(
    game_folder: str,
    base_title: str,
    best_depth: int,
    exes: List[str],
) -> List[ExeCandidate]:
    out: List[ExeCandidate] = []
    for p in exes:
        try:
            st = os.stat(p)
            size = st.st_size
            mtime = st.st_mtime
        except Exception:
            size = 0
            mtime = 0.0

        sc, reason = score_exe(p, base_title=base_title, rel_depth=best_depth)
        out.append(ExeCandidate(path=p, score=sc, size_bytes=size, mtime=mtime, reason=reason))

    out.sort(key=lambda c: (c.score, c.size_bytes), reverse=True)
    return out

def find_any_exe_exists(game_folder: str) -> bool:
    for dirpath, _, filenames in safe_walk(game_folder):
        for fn in filenames:
            if fn.lower().endswith(".exe"):
                return True
    return False


def scan_html_candidates(game_folder: str) -> list[str]:
    htmls = []
    for dirpath, _, filenames in safe_walk(game_folder):
        for fn in filenames:
            lf = fn.lower()
            if lf.endswith(".html") or lf.endswith(".htm"):
                htmls.append(os.path.join(dirpath, fn))
    return htmls


def scan_swf_candidates(game_folder: str) -> list[str]:
    """Full paths of every .swf (Flash) file under `game_folder`.

    Flash games ship a .swf as their entry point and usually have no .exe. The
    scan treats a .swf as an exe-equivalent launcher (a .lnk straight to the
    Flash file, opened by the user's default .swf handler) when no .exe exists,
    so these games still get a shortcut instead of being reported as launcherless.
    """
    swfs = []
    for dirpath, _, filenames in safe_walk(game_folder):
        for fn in filenames:
            if fn.lower().endswith(".swf"):
                swfs.append(os.path.join(dirpath, fn))
    return swfs


def build_topmost_swf_candidates(game_folder: str, base_title: str) -> List[ExeCandidate]:
    """Exe-equivalent candidates for the shallowest .swf (Flash) files, or [].

    Mirrors the topmost-exe contract: only the .swf files at the smallest depth
    are offered (deeper ones are usually bundled sub-content), each scored and
    returned as an ExeCandidate so a Flash launcher flows through the exact same
    picker / auto-pick / version logic as an .exe. The caller uses this only when
    there is no usable (non-ignored) .exe, so a real launcher always wins.
    """
    swfs = scan_swf_candidates(game_folder)
    if not swfs:
        return []
    swf_depth = min(_rel_depth(game_folder, os.path.dirname(p)) for p in swfs)
    topmost = [p for p in swfs if _rel_depth(game_folder, os.path.dirname(p)) == swf_depth]
    return build_candidates(game_folder, base_title, swf_depth, topmost)


