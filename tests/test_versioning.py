"""
Tests for the pure version parsing/comparison logic that drives the
replace-on-newer-version decision. Cross-platform, no Qt/win32com.
"""
from versioning import extract_version, strip_version_from_title, compare_versions


# --------------------------------------------------------------------------
# extract_version
# --------------------------------------------------------------------------

def test_extract_version_requires_a_dot():
    # The regex needs at least one dot, so a bare "v2" carries no version.
    assert extract_version("Game v2") == ("", ())
    assert extract_version("Game v2.0")[1] == (2, 0)


def test_extract_version_takes_last_match():
    # README example direction: trailing version wins.
    vstr, vt = extract_version("Game 1.2 build 3.4")
    assert vstr == "3.4"
    assert vt == (3, 4)


def test_extract_version_three_parts():
    assert extract_version("Game 0.14.17")[1] == (0, 14, 17)


def test_extract_version_none():
    assert extract_version("Just A Title") == ("", ())


# --------------------------------------------------------------------------
# compare_versions
# --------------------------------------------------------------------------

def test_compare_versions_newer_replaces_older():
    # The README's "v0.14 -> 0.14.17 replaces" case.
    assert compare_versions((0, 14), (0, 14, 17)) == -1
    assert compare_versions((0, 14, 17), (0, 14)) == 1


def test_compare_versions_equal():
    assert compare_versions((1, 0), (1, 0)) == 0
    assert compare_versions((1, 0), (1, 0, 0)) == 0  # zero-padded tail


def test_compare_versions_empty_tuples():
    assert compare_versions((), ()) == 0
    assert compare_versions((1,), ()) == 1
    assert compare_versions((), (1,)) == -1


# --------------------------------------------------------------------------
# strip_version_from_title
# --------------------------------------------------------------------------

def test_strip_version_basic():
    assert strip_version_from_title("My Game v1.2") == "My Game"
    assert strip_version_from_title("Game_1.0.3") == "Game"


def test_strip_version_all_version_falls_back_to_original():
    # Stripping everything would leave nothing -> keep the original.
    assert strip_version_from_title("1.2.3") == "1.2.3"
