"""
Tests for the launcher-scoring heuristics (exe + html). These decide which
executable becomes the recommended shortcut, and the HTML threshold is coupled
to the collection classifier, so both are pinned here. Cross-platform.
"""
from exe_scoring import score_exe
from html_scoring import score_html
from collection import HTML_LAUNCHER_THRESHOLD


# --------------------------------------------------------------------------
# score_exe
# --------------------------------------------------------------------------

def test_title_match_beats_generic_name():
    title = "Cool Game"
    matched, _ = score_exe("/g/Cool Game.exe", base_title=title, rel_depth=0)
    other, _ = score_exe("/g/data.exe", base_title=title, rel_depth=0)
    assert matched > other


def test_installer_like_is_penalized():
    game, _ = score_exe("/g/Game.exe", base_title="Game", rel_depth=0)
    setup, _ = score_exe("/g/setup.exe", base_title="Game", rel_depth=0)
    unins, _ = score_exe("/g/unins000.exe", base_title="Game", rel_depth=0)
    assert setup < game
    assert unins < game


def test_depth_penalty_prefers_topmost():
    shallow, _ = score_exe("/g/Game.exe", base_title="Game", rel_depth=0)
    deep, _ = score_exe("/g/sub/Game.exe", base_title="Game", rel_depth=3)
    assert shallow > deep


# --------------------------------------------------------------------------
# score_html — coupled to collection.HTML_LAUNCHER_THRESHOLD
# --------------------------------------------------------------------------

def test_index_html_qualifies_as_launcher():
    score, _ = score_html("/g/index.html", base_title="Game", rel_depth=0)
    assert score >= HTML_LAUNCHER_THRESHOLD


def test_doc_html_does_not_qualify():
    score, _ = score_html("/g/readme.html", base_title="Game", rel_depth=0)
    assert score < HTML_LAUNCHER_THRESHOLD


def test_html_depth_penalty():
    shallow, _ = score_html("/g/index.html", base_title="Game", rel_depth=0)
    deep, _ = score_html("/g/sub/index.html", base_title="Game", rel_depth=3)
    assert shallow > deep
