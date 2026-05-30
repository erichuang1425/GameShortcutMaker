"""
Tests for the ignore-rule filter (installers, redists, tools, ...). The path
globs are Windows-style and is_ignored normalizes paths to backslashes, so
these run identically on every platform. Cross-platform.
"""
from rules import default_rules, is_ignored

RULES = default_rules()


def test_name_globs_match_installers():
    assert is_ignored("/games/MyGame/unins000.exe", RULES)
    assert is_ignored("/games/MyGame/setup.exe", RULES)
    assert is_ignored("/games/MyGame/vcredist_x64.exe", RULES)


def test_real_launcher_is_not_ignored():
    assert not is_ignored("/games/MyGame/Game.exe", RULES)
    assert not is_ignored("/games/MyGame/bin/Game.exe", RULES)


def test_path_globs_are_windows_style_and_normalized():
    # Forward-slash input is normalized to backslashes before matching the
    # backslash-style path globs (e.g. "*\\tools\\*", "*\\redist\\*").
    assert is_ignored("C:/Games/MyGame/tools/helper.exe", RULES)
    assert is_ignored("/games/MyGame/redist/vc.exe", RULES)
    assert not is_ignored("/games/MyGame/data/asset.exe", RULES)
