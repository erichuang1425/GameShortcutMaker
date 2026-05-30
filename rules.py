from __future__ import annotations
import fnmatch
import os


def default_rules() -> dict:
    return {
        "ignore_exe_name_globs": [
            "*unins*.exe",
            "uninstall*.exe",
            "*setup*.exe",
            "*config*.exe",
            "*launcherhelper*.exe",
            "*crashhandler*.exe",
            "*unitycrashhandler*.exe",
            "*unitycrashhandler64*.exe",
            "*cef*.exe",
            "*vcredist*.exe",
            "*dxsetup*.exe",
            "*dotnet*.exe",
            "*translator*.exe",
            "*server*.exe",
            "*dedicated*.exe",
            "*editor*.exe",
        ],
        "ignore_path_globs": [
            "*\\_redist\\*",
            "*\\redist\\*",
            "*\\directx\\*",
            "*\\vcredist\\*",
            "*\\dotnet\\*",
            "*\\support\\*",
            "*\\tools\\*",
            "*\\crash*\\*",
        ],
    }


def _match_any(value: str, globs: list[str]) -> bool:
    v = value.lower()
    for g in globs:
        if fnmatch.fnmatch(v, g.lower()):
            return True
    return False


def is_ignored(exe_path: str, rules: dict) -> bool:
    exe_name = os.path.basename(exe_path)
    norm = os.path.normpath(exe_path).replace("/", "\\")
    if _match_any(exe_name, rules.get("ignore_exe_name_globs", [])):
        return True
    if _match_any(norm, rules.get("ignore_path_globs", [])):
        return True
    return False
