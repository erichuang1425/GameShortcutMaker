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


# Windows path length limit. WScript.Shell rejects a Targetpath at/above this
# with the same opaque error it gives for forward slashes, so we treat an
# over-length target as a distinct, recoverable case (8.3 short-path fallback).
_MAX_PATH = 260


def ensure_windows_shortcut_support():
    if win32com is None:
        raise RuntimeError("pywin32 is required. Install: python -m pip install pywin32")


def categorize_apply_error(detail: str) -> str:
    """Bucket a raw per-item apply error into a coarse, user-facing category.

    `detail` is the message captured in the apply loop (typically the string of
    the underlying exception). Matching is done on lowercased substrings so it
    works for both Python OSError text and the Windows error phrasing surfaced
    through pywin32 / WScript.Shell.
    """
    low = (detail or "").lower()
    if "pywin32" in low or "win32com" in low or "win32" in low:
        return "pywin32 not available (cannot create .lnk shortcuts)"
    if (
        "permission" in low
        or "access is denied" in low
        or "winerror 5" in low
        or "errno 13" in low
        or "read-only" in low
        or "read only" in low
    ):
        return "Permission denied / read-only output folder"
    if (
        "too long" in low
        or "filename or extension is too long" in low
        or "winerror 206" in low
        or "winerror 3" in low
        or "errno 36" in low
        or "errno 63" in low
    ):
        return "Path too long"
    if (
        "no such file" in low
        or "cannot find" in low
        or "not found" in low
        or "winerror 2" in low
        or "errno 2" in low
    ):
        return "File or path not found"
    # WScript.Shell rejects a Targetpath it dislikes (most often forward slashes
    # in the path) with this phrasing. Bucket it explicitly so a recurrence is
    # diagnosable instead of disappearing into "Other error".
    if "targetpath" in low or "can not be set" in low:
        return "Invalid shortcut target (Targetpath rejected)"
    return "Other error"


def summarize_errors(details) -> dict:
    """Count apply errors by category. Returns {category: count}."""
    out: dict[str, int] = {}
    for d in details or []:
        cat = categorize_apply_error(d)
        out[cat] = out.get(cat, 0) + 1
    return out


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


def _duplicate_glob(output_dir: str, base: str, ext: str) -> str:
    """
    Glob pattern matching numbered duplicates like 'Name (1).lnk'.

    Both the output dir and the base name are passed through glob.escape so
    metacharacters in game names (commonly '[' / ']', e.g. 'Game [Final]') are
    matched literally instead of being parsed as glob character classes — which
    would silently fail to match the real files.
    """
    return os.path.join(glob.escape(output_dir), f"{glob.escape(base)} (*).{ext}")


def multi_shortcut_names(base_title: str, paths: list[str]) -> list[str]:
    """Display names for one game's chosen launcher(s).

    A single launcher keeps the plain game title. When the user picks several
    launchers for one game we need distinct names: the first keeps the title and
    the rest are suffixed with the launcher's file stem ("Cool Game - editor").
    Collisions (same stem, or a suffix that matches the title) get a numeric
    "(2)" tail so every returned name is unique (case-insensitively). Returns one
    name per input path, in order.
    """
    if not paths:
        return []
    if len(paths) == 1:
        return [base_title]

    names: list[str] = []
    used: set[str] = set()
    for idx, p in enumerate(paths):
        if idx == 0:
            candidate = base_title
        else:
            stem = os.path.splitext(os.path.basename(p))[0]
            candidate = f"{base_title} - {stem}" if stem else base_title

        unique = candidate
        n = 2
        while unique.lower() in used:
            unique = f"{candidate} ({n})"
            n += 1
        used.add(unique.lower())
        names.append(unique)
    return names


def shortcut_path(output_dir: str, display_name: str) -> str:
    return os.path.join(output_dir, f"{safe_filename(display_name)}.lnk")


def to_windows_path(path: str) -> str:
    """Normalize separators to Windows backslashes for the WScript.Shell COM API.

    WScript.Shell's ``Shortcut.Targetpath`` (and the other path properties)
    reject forward slashes with the opaque error
    "Property '<unknown>.Targetpath' can not be set." A game root entered with
    forward slashes (e.g. 'D:/Games/...') flows straight into each .exe target
    via os.path.join, so every .lnk in the library fails to apply while .url
    (HTML) shortcuts — written as plain text — still succeed.

    The conversion is done explicitly rather than via os.path.normpath, which is
    a no-op for '/' on non-Windows hosts, so the result is deterministic
    wherever the tests run.
    """
    return path.replace("/", "\\") if path else path


def short_path(path: str) -> str:
    """Return the Windows 8.3 short path for an existing file, else `path`.

    WScript.Shell rejects a Targetpath that exceeds MAX_PATH (260) with the same
    opaque "Property '<unknown>.Targetpath' can not be set." it gives for forward
    slashes. The 8.3 short path points at the same file with a much shorter
    string, so it is our fallback when a long target is rejected.

    Best-effort and side-effect free: returns the input unchanged when pywin32 /
    win32api is unavailable (e.g. on the non-Windows test host), when the file
    does not exist, or when the volume has 8.3 name generation disabled — callers
    must compare against the input and only use a genuinely shorter result.
    """
    if not path:
        return path
    try:
        import win32api  # type: ignore
        return win32api.GetShortPathName(path)
    except Exception:
        return path


def create_or_replace_shortcut(lnk_path: str, target_path: str) -> None:
    ensure_windows_shortcut_support()
    # WScript.Shell only accepts backslash separators; normalize so a game root
    # entered with forward slashes does not fail every .lnk in the library.
    lnk_path = to_windows_path(lnk_path)
    target_path = to_windows_path(target_path)
    shell = win32com.client.Dispatch("WScript.Shell")

    def _write(target: str) -> None:
        # A fresh shortcut object per attempt: a half-configured one left over
        # from a rejected assignment must not leak into the retry.
        sc = shell.CreateShortcut(lnk_path)
        sc.Targetpath = target
        sc.WorkingDirectory = os.path.dirname(target)
        sc.IconLocation = target
        sc.Save()

    try:
        _write(target_path)
        return
    except Exception as err:
        # The Targetpath was rejected. The usual remaining cause (forward slashes
        # are already normalized away) is a path over MAX_PATH; retry with the 8.3
        # short path, which is the same file but short enough to be accepted.
        short = short_path(target_path)
        if short and short != target_path:
            try:
                _write(short)
                return
            except Exception:
                pass
        # Still failing: re-raise with the actual target and its length so the
        # apply log pinpoints the cause instead of repeating the opaque message.
        # Wording an over-length target as "too long" routes it to the dedicated
        # category in categorize_apply_error; anything else stays a Targetpath
        # rejection.
        n = len(target_path)
        hint = f" — target path is too long ({n} chars, exceeds Windows MAX_PATH {_MAX_PATH})" if n >= _MAX_PATH else ""
        raise RuntimeError(f"{err} [target={target_path!r}, length={n}]{hint}") from err


def read_shortcut_target(lnk_path: str) -> str:
    ensure_windows_shortcut_support()
    lnk_path = to_windows_path(lnk_path)
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
    dup_lnk = sorted(glob.glob(_duplicate_glob(output_dir, base, "lnk")))
    if dup_lnk:
        return dup_lnk[0], "exe"

    dup_url = sorted(glob.glob(_duplicate_glob(output_dir, base, "url")))
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
        _duplicate_glob(output_dir, base, "lnk"),
        _duplicate_glob(output_dir, base, "url"),
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


def normalize_target_for_compare(p: str) -> str:
    """Normalize a launcher path so two spellings of the same target compare equal.

    Windows paths are case-insensitive and may arrive with either separator (a
    game root entered as 'D:/Games' yields forward slashes; a target read back
    from a .lnk comes back with backslashes). Lower-casing and unifying the
    separator lets us tell whether a recorded shortcut still points at the file
    we would target now.
    """
    if not p:
        return ""
    return p.replace("\\", "/").rstrip("/").lower()


def target_moved(existing_target: str, new_target: str) -> bool:
    """True when a recorded shortcut target no longer matches the launcher we'd
    create now — i.e. the underlying files were relocated (typically by Flatten),
    so the existing shortcut points at a stale path and should be refreshed.

    Conservative by design:
      * Returns False when either target is unknown (no recorded target to
        compare), so a missing/partial index never forces a needless replace.
      * Returns False for URL-form recorded targets ('file://…', 'http://…'),
        which a .url read-back can yield and which aren't directly comparable to
        a plain filesystem path.
    """
    if not existing_target or not new_target:
        return False
    if existing_target.lower().startswith(("file:", "http:", "https:")):
        return False
    return normalize_target_for_compare(existing_target) != normalize_target_for_compare(new_target)
