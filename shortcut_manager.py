from __future__ import annotations
import os
import shutil
import time
import pathlib
import glob


try:
    import win32com.client  # type: ignore
except Exception:
    win32com = None


def ensure_windows_shortcut_support():
    if win32com is None:
        raise RuntimeError("pywin32 is required. Install: python -m pip install pywin32")


def safe_filename(name: str) -> str:
    bad = '<>:"/\\|?*'
    out = "".join("_" if c in bad else c for c in name).strip()
    return out if out else "Game"


# Windows reserved device names (case-insensitive, with or without extension).
_RESERVED_NAMES = {"CON", "PRN", "AUX", "NUL"} | {f"COM{i}" for i in range(1, 10)} | {f"LPT{i}" for i in range(1, 10)}


def safe_path_segment(name: str) -> str:
    """
    Sanitize a single folder name so it is safe as a directory segment on Windows:
    strips invalid characters, trailing dots/spaces, and avoids reserved device names.
    """
    seg = safe_filename(name)
    seg = seg.rstrip(" .")
    if not seg:
        return "Folder"
    if seg.split(".")[0].upper() in _RESERVED_NAMES:
        seg = f"_{seg}"
    return seg


def safe_subpath(rel_posix: str) -> str:
    """
    Sanitize a POSIX-style relative path ("A/B/C") segment-by-segment.
    Returns a POSIX-style path; empty input (a top-level game) returns "".
    """
    parts = [p for p in rel_posix.split("/") if p not in ("", ".")]
    return "/".join(safe_path_segment(p) for p in parts)


def shortcut_path(output_dir: str, display_name: str) -> str:
    return os.path.join(output_dir, f"{safe_filename(display_name)}.lnk")


def create_or_replace_shortcut(lnk_path: str, target_path: str) -> None:
    ensure_windows_shortcut_support()
    shell = win32com.client.Dispatch("WScript.Shell")
    sc = shell.CreateShortcut(lnk_path)
    sc.Targetpath = target_path
    sc.WorkingDirectory = os.path.dirname(target_path)
    sc.IconLocation = target_path
    sc.Save()


def read_shortcut_target(lnk_path: str) -> str:
    ensure_windows_shortcut_support()
    shell = win32com.client.Dispatch("WScript.Shell")
    sc = shell.CreateShortcut(lnk_path)
    try:
        return sc.Targetpath or ""
    except Exception:
        return ""


def backup_shortcut(lnk_path: str, backup_dir: str, name_prefix: str = "") -> str:
    """
    Copy existing shortcut to backup dir. Returns backup path, or "".

    name_prefix lets callers disambiguate same-named shortcuts that live in
    different output subfolders (collections), avoiding backup name collisions.
    """
    if not os.path.exists(lnk_path):
        return ""
    os.makedirs(backup_dir, exist_ok=True)
    ts = time.strftime("%Y%m%d-%H%M%S")
    stem = os.path.splitext(os.path.basename(lnk_path))[0]
    prefix = f"{safe_path_segment(name_prefix)}__" if name_prefix else ""
    dst = os.path.join(backup_dir, f"{prefix}{stem}_{ts}.lnk")
    shutil.copy2(lnk_path, dst)
    return dst

def url_shortcut_path(output_dir: str, display_name: str) -> str:
    return os.path.join(output_dir, f"{safe_filename(display_name)}.url")

def create_url_shortcut(url_path: str, file_target: str) -> None:
    """
    Creates an Internet Shortcut (.url) pointing to a local file (HTML).
    """
    p = pathlib.Path(file_target).resolve()
    # Convert local path to file:/// URL
    file_url = p.as_uri()

    content = "[InternetShortcut]\n" f"URL={file_url}\n"
    with open(url_path, "w", encoding="utf-8") as f:
        f.write(content)

def canonical_paths(output_dir: str, display_name: str) -> tuple[str, str]:
    """
    Returns (canonical_lnk_path, canonical_url_path) for a given display name.
    """
    base = safe_filename(display_name)
    lnk = os.path.join(output_dir, f"{base}.lnk")
    url = os.path.join(output_dir, f"{base}.url")
    return lnk, url


def find_existing_shortcut(output_dir: str, display_name: str) -> tuple[str, str]:
    """
    Treats .lnk and .url as equivalent 'shortcut' for existence checks.

    Returns:
      (path, target_type) where target_type is "exe" or "html"
      If none exists -> ("", "")
    Priority:
      1) canonical .lnk
      2) canonical .url
      3) any numbered duplicates like 'Name (1).lnk' or 'Name (2).url' (rare, but we handle it)
    """
    lnk, url = canonical_paths(output_dir, display_name)

    if os.path.exists(lnk):
        return lnk, "exe"
    if os.path.exists(url):
        return url, "html"

    base = safe_filename(display_name)

    # Fallback: find duplicates (Name (1).lnk etc.)
    dup_lnk = sorted(glob.glob(os.path.join(output_dir, f"{base} (*).lnk")))
    if dup_lnk:
        return dup_lnk[0], "exe"

    dup_url = sorted(glob.glob(os.path.join(output_dir, f"{base} (*).url")))
    if dup_url:
        return dup_url[0], "html"

    return "", ""


def cleanup_duplicate_shortcuts(output_dir: str, display_name: str) -> None:
    """
    Removes numbered duplicates: 'Name (1).lnk', 'Name (2).url', etc.
    Keeps the canonical 'Name.lnk'/'Name.url' untouched.
    """
    base = safe_filename(display_name)

    patterns = [
        os.path.join(output_dir, f"{base} (*).lnk"),
        os.path.join(output_dir, f"{base} (*).url"),
    ]
    for pat in patterns:
        for p in glob.glob(pat):
            try:
                os.remove(p)
            except Exception:
                # ignore permission issues etc.
                pass


def enforce_single_shortcut_type(output_dir: str, display_name: str, target_type: str, dry_run: bool) -> tuple[str, str]:
    """
    Ensures only ONE of {Name.lnk, Name.url} exists by deleting the opposite type.

    target_type: "exe" or "html"
    Returns (canonical_lnk, canonical_url)
    """
    lnk, url = canonical_paths(output_dir, display_name)
    if dry_run:
        return lnk, url

    # If we're writing HTML, remove any EXE shortcut; if writing EXE, remove HTML shortcut.
    try:
        if target_type == "html" and os.path.exists(lnk):
            os.remove(lnk)
        elif target_type == "exe" and os.path.exists(url):
            os.remove(url)
    except Exception:
        pass

    return lnk, url


def read_url_shortcut_target(url_path: str) -> str:
    """
    Reads target from a .url Internet Shortcut, returns URL line content (may be file:///...).
    """
    try:
        with open(url_path, "r", encoding="utf-8", errors="ignore") as f:
            for line in f:
                if line.strip().lower().startswith("url="):
                    return line.split("=", 1)[1].strip()
    except Exception:
        pass
    return ""
