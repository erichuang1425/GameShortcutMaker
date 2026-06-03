"""
Cross-platform unit tests for the pure collection-classification logic and the
path/index helpers it relies on. These run without Qt or win32com.
"""
import json
import os

from rules import default_rules
from collection import classify_tree, iter_game_targets, scan_targets, FolderKind
from shortcut_manager import safe_path_segment, safe_subpath
import storage

RULES = default_rules()


def _touch(path: str) -> None:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    open(path, "w").close()


# --------------------------------------------------------------------------
# Classifier
# --------------------------------------------------------------------------

def test_solo_game_exe_at_root(tmp_path):
    g = tmp_path / "SoloGame"
    _touch(str(g / "game.exe"))
    assert classify_tree(str(g), RULES).kind == FolderKind.GAME


def test_solo_game_exe_in_subfolder(tmp_path):
    # Launcher one level down, single game-bearing child -> still one game.
    g = tmp_path / "MyGame"
    _touch(str(g / "bin" / "game.exe"))
    assert classify_tree(str(g), RULES, threshold_n=3).kind == FolderKind.GAME


def test_collection_of_three_games(tmp_path):
    c = tmp_path / "RenPyCollection"
    _touch(str(c / "GameA" / "a.exe"))
    _touch(str(c / "GameB" / "b.exe"))
    _touch(str(c / "GameC" / "c.exe"))
    node = classify_tree(str(c), RULES, threshold_n=3)
    assert node.kind == FolderKind.COLLECTION
    assert len(node.children) == 3


def test_two_children_below_threshold_is_game(tmp_path):
    c = tmp_path / "Pair"
    _touch(str(c / "GameA" / "a.exe"))
    _touch(str(c / "GameB" / "b.exe"))
    assert classify_tree(str(c), RULES, threshold_n=3).kind == FolderKind.GAME


def test_direct_exe_wins_over_subfolders(tmp_path):
    # A game with a launcher at its root plus game-bearing subfolders is one game.
    c = tmp_path / "GameWithMinigames"
    _touch(str(c / "Launcher.exe"))
    _touch(str(c / "MiniA" / "a.exe"))
    _touch(str(c / "MiniB" / "b.exe"))
    _touch(str(c / "MiniC" / "c.exe"))
    assert classify_tree(str(c), RULES, threshold_n=3).kind == FolderKind.GAME


def test_variant_guard_same_title(tmp_path):
    # 32/64-bit variants of ONE game must not look like a collection.
    c = tmp_path / "BigGame"
    _touch(str(c / "BigGame win32" / "game.exe"))
    _touch(str(c / "BigGame win64" / "game.exe"))
    _touch(str(c / "BigGame x86" / "game.exe"))
    assert classify_tree(str(c), RULES, threshold_n=3).kind == FolderKind.GAME


def test_nested_collection(tmp_path):
    root = tmp_path / "Outer"
    for o in range(3):
        for i in range(3):
            _touch(str(root / f"Inner{o}" / f"Game{i}" / "g.exe"))
    node = classify_tree(str(root), RULES, threshold_n=3)
    assert node.kind == FolderKind.COLLECTION
    assert all(ch.kind == FolderKind.COLLECTION for ch in node.children)


def test_wrapper_of_two_subcollections_is_a_collection(tmp_path):
    # A folder grouping two already-detected collections has only 2 immediate
    # children (below threshold 3), but collapsing it into one shortcut would
    # discard six games. It must stay a collection so the nesting is mirrored.
    root = tmp_path / "Library"
    for i in range(3):
        _touch(str(root / "PackA" / f"GameA{i}" / "g.exe"))
    for i in range(3):
        _touch(str(root / "PackB" / f"GameB{i}" / "g.exe"))
    node = classify_tree(str(root), RULES, threshold_n=3)
    assert node.kind == FolderKind.COLLECTION
    assert {ch.name for ch in node.children} == {"PackA", "PackB"}
    assert all(ch.kind == FolderKind.COLLECTION for ch in node.children)


def test_wrapper_of_subcollections_mirrors_nested_subdirs(tmp_path):
    for i in range(3):
        _touch(str(tmp_path / "Library" / "PackA" / f"GameA{i}" / "g.exe"))
    for i in range(3):
        _touch(str(tmp_path / "Library" / "PackB" / f"GameB{i}" / "g.exe"))
    t = _by_name(scan_targets(str(tmp_path), RULES, threshold_n=3))["Library"]
    assert t.is_collection
    rel = {os.path.basename(m.path): m.rel_output_subdir for m in t.members}
    assert rel["GameA0"] == "Library/PackA"
    assert rel["GameB0"] == "Library/PackB"
    # Every member is tagged with the outer collection name.
    assert {m.collection_name for m in t.members} == {"Library"}


def test_html_index_is_a_game(tmp_path):
    g = tmp_path / "WebGame"
    _touch(str(g / "index.html"))  # qualifying HTML launcher, no exe
    assert classify_tree(str(g), RULES).kind == FolderKind.GAME


def test_collection_of_html_only_games(tmp_path):
    c = tmp_path / "WebGames"
    _touch(str(c / "GameA" / "index.html"))
    _touch(str(c / "GameB" / "index.html"))
    _touch(str(c / "GameC" / "index.html"))
    node = classify_tree(str(c), RULES, threshold_n=3)
    assert node.kind == FolderKind.COLLECTION
    assert len(node.children) == 3


def test_html_docs_only_is_empty(tmp_path):
    g = tmp_path / "HelpFolder"
    _touch(str(g / "readme.html"))  # doc-like, scores below the launcher threshold
    assert classify_tree(str(g), RULES).kind == FolderKind.EMPTY


# --------------------------------------------------------------------------
# .swf (Flash) games: a .swf is an exe-equivalent launcher, so a Flash-only
# folder is a GAME and a folder of them is a COLLECTION (it would otherwise be
# misclassified EMPTY and never get a shortcut).
# --------------------------------------------------------------------------

def test_solo_swf_is_a_game(tmp_path):
    g = tmp_path / "FlashGame"
    _touch(str(g / "game.swf"))  # no exe, no html
    assert classify_tree(str(g), RULES).kind == FolderKind.GAME


def test_collection_of_swf_only_games(tmp_path):
    c = tmp_path / "FLASH游戏"
    _touch(str(c / "Crimson" / "crimson.swf"))
    _touch(str(c / "JGirlFight" / "jgirl.swf"))
    _touch(str(c / "SexialBattle" / "sexial.swf"))
    node = classify_tree(str(c), RULES, threshold_n=3)
    assert node.kind == FolderKind.COLLECTION
    assert len(node.children) == 3


def test_swf_collection_emits_member_targets(tmp_path):
    c = tmp_path / "FlashPack"
    for name in ("A", "B", "C"):
        _touch(str(c / name / f"{name}.swf"))
    [target] = scan_targets(str(c.parent), RULES, threshold_n=3)
    assert target.is_collection
    assert {os.path.basename(m.path) for m in target.members} == {"A", "B", "C"}


def test_swf_rescues_folder_whose_only_exe_is_ignored(tmp_path):
    # An installer-only folder is EMPTY, but a .swf beside it is a real launcher.
    g = tmp_path / "FlashWithInstaller"
    _touch(str(g / "unins000.exe"))  # ignored by the default *unins*.exe rule
    _touch(str(g / "play.swf"))
    assert classify_tree(str(g), RULES).kind == FolderKind.GAME


def test_empty_folder(tmp_path):
    g = tmp_path / "DocsOnly"
    _touch(str(g / "readme.txt"))
    assert classify_tree(str(g), RULES).kind == FolderKind.EMPTY


def test_ignored_only_exe_is_empty(tmp_path):
    g = tmp_path / "InstallerOnly"
    _touch(str(g / "unins000.exe"))  # matches the default *unins*.exe ignore rule
    assert classify_tree(str(g), RULES).kind == FolderKind.EMPTY


def test_max_depth_guard(tmp_path):
    deep = tmp_path / "Deep"
    p = deep
    for i in range(8):
        p = p / f"d{i}"
    _touch(str(p / "game.exe"))
    # A single deep chain is one game regardless of depth cap.
    assert classify_tree(str(deep), RULES, threshold_n=3, max_depth=3).kind == FolderKind.GAME


def test_iter_game_targets_mirrors_structure(tmp_path):
    _touch(str(tmp_path / "SoloGame" / "game.exe"))
    _touch(str(tmp_path / "RenPyCollection" / "GameA" / "a.exe"))
    _touch(str(tmp_path / "RenPyCollection" / "GameB" / "b.exe"))
    _touch(str(tmp_path / "RenPyCollection" / "GameC" / "c.exe"))

    by_folder = {os.path.basename(p): (rel, coll) for (p, rel, coll) in
                 iter_game_targets(str(tmp_path), RULES, threshold_n=3)}
    assert by_folder["SoloGame"] == ("", "")
    assert by_folder["GameA"] == ("RenPyCollection", "RenPyCollection")
    assert by_folder["GameB"][0] == "RenPyCollection"
    assert by_folder["GameC"][0] == "RenPyCollection"


def test_progress_cb_is_called(tmp_path):
    # The classifier reports each directory it visits so the UI can animate.
    _touch(str(tmp_path / "SoloGame" / "game.exe"))
    seen = []
    iter_game_targets(str(tmp_path), RULES, threshold_n=3, progress_cb=seen.append)
    assert any(os.path.basename(p) == "SoloGame" for p in seen)


def test_walk_is_pruned_below_direct_launcher(tmp_path):
    # A game whose launcher sits at the top must NOT have its asset tree walked:
    # classify() returns GAME without inspecting descendants, so the walk stops.
    g = tmp_path / "Game"
    _touch(str(g / "launcher.exe"))
    _touch(str(g / "assets" / "deep" / "more" / "huge.dat"))
    seen = []
    node = classify_tree(str(g), RULES, threshold_n=3, progress_cb=seen.append)
    assert node.kind == FolderKind.GAME
    assert not any("assets" in os.path.relpath(p, str(g)).split(os.sep) for p in seen)


def test_collections_disabled_equivalent(tmp_path):
    # With a high threshold nothing is a collection: every top folder is flat.
    _touch(str(tmp_path / "Coll" / "GameA" / "a.exe"))
    _touch(str(tmp_path / "Coll" / "GameB" / "b.exe"))
    _touch(str(tmp_path / "Coll" / "GameC" / "c.exe"))
    targets = iter_game_targets(str(tmp_path), RULES, threshold_n=99)
    assert [os.path.basename(p) for (p, _r, _c) in targets] == ["Coll"]
    assert targets[0][1] == ""


# --------------------------------------------------------------------------
# scan_targets: single-walk classification + topmost-exe extraction
# --------------------------------------------------------------------------

def _by_name(targets):
    return {os.path.basename(t.path): t for t in targets}


def test_scan_targets_topmost_exes_at_root(tmp_path):
    _touch(str(tmp_path / "SoloGame" / "game.exe"))
    _touch(str(tmp_path / "SoloGame" / "play.exe"))  # both non-ignored launchers
    t = _by_name(scan_targets(str(tmp_path), RULES, threshold_n=3))["SoloGame"]
    assert not t.is_collection
    assert t.best_depth == 0
    # sorted by basename, both non-ignored
    assert [os.path.basename(p) for p in t.all_exes] == ["game.exe", "play.exe"]
    assert [os.path.basename(p) for p in t.non_ignored_exes] == ["game.exe", "play.exe"]


def test_scan_targets_splits_ignored_from_nonignored(tmp_path):
    _touch(str(tmp_path / "G" / "game.exe"))
    _touch(str(tmp_path / "G" / "unins000.exe"))  # matches *unins*.exe ignore rule
    t = _by_name(scan_targets(str(tmp_path), RULES, threshold_n=3))["G"]
    assert [os.path.basename(p) for p in t.all_exes] == ["game.exe", "unins000.exe"]
    assert [os.path.basename(p) for p in t.non_ignored_exes] == ["game.exe"]


def test_scan_targets_exe_in_subfolder_reports_depth(tmp_path):
    _touch(str(tmp_path / "MyGame" / "bin" / "game.exe"))
    t = _by_name(scan_targets(str(tmp_path), RULES, threshold_n=3))["MyGame"]
    assert t.best_depth == 1
    assert [os.path.basename(p) for p in t.all_exes] == ["game.exe"]


def test_scan_targets_shallow_uninstaller_does_not_shadow_deeper_launcher(tmp_path):
    # Mirror of scanner.test_topmost_skips_shallower_uninstaller_for_deeper_real_exe
    # through the single-walk path: an Inno-Setup unins000.exe at the folder root
    # must not pin best_depth to 0 and hide the real launcher in Game-Data.
    _touch(str(tmp_path / "Undertale" / "unins000.exe"))           # ignored, depth 0
    _touch(str(tmp_path / "Undertale" / "Game-Data" / "UNDERTALE.exe"))  # real, depth 1
    t = _by_name(scan_targets(str(tmp_path), RULES, threshold_n=3))["Undertale"]
    assert not t.is_collection
    assert t.best_depth == 1
    assert [os.path.basename(p) for p in t.non_ignored_exes] == ["UNDERTALE.exe"]
    assert [os.path.basename(p) for p in t.all_exes] == ["UNDERTALE.exe"]


def test_scan_targets_prunes_asset_tree_below_launcher(tmp_path):
    # Topmost .exe sits at the root; the deep asset tree must not contribute exes.
    g = tmp_path / "Game"
    _touch(str(g / "launcher.exe"))
    _touch(str(g / "assets" / "deep" / "tools.exe"))  # deeper, must be ignored by topmost logic
    t = _by_name(scan_targets(str(tmp_path), RULES, threshold_n=3))["Game"]
    assert t.best_depth == 0
    assert [os.path.basename(p) for p in t.all_exes] == ["launcher.exe"]


def test_scan_targets_finds_exe_deeper_than_collection_cap(tmp_path):
    # The walk is not depth-capped (only collection classification is), so a
    # buried launcher is still found as the topmost exe.
    deep = tmp_path / "Deep"
    p = deep
    for i in range(5):
        p = p / f"d{i}"
    _touch(str(p / "game.exe"))
    t = _by_name(scan_targets(str(tmp_path), RULES, threshold_n=3, max_depth=3))["Deep"]
    assert t.best_depth == 5
    assert [os.path.basename(x) for x in t.all_exes] == ["game.exe"]


def test_scan_targets_collection_members_carry_exes(tmp_path):
    c = tmp_path / "RenPyCollection"
    _touch(str(c / "GameA" / "a.exe"))
    _touch(str(c / "GameB" / "b.exe"))
    _touch(str(c / "GameC" / "c.exe"))
    t = _by_name(scan_targets(str(tmp_path), RULES, threshold_n=3))["RenPyCollection"]
    assert t.is_collection
    members = {os.path.basename(m.path): m for m in t.members}
    assert set(members) == {"GameA", "GameB", "GameC"}
    assert members["GameA"].rel_output_subdir == "RenPyCollection"
    assert members["GameA"].best_depth == 0
    assert [os.path.basename(p) for p in members["GameA"].all_exes] == ["a.exe"]


def test_scan_targets_collection_members_are_games_only(tmp_path):
    # A launcher-less subfolder is not a game, so it is not emitted as a
    # collection member (collection children are games only).
    c = tmp_path / "Coll"
    _touch(str(c / "GameA" / "a.exe"))
    _touch(str(c / "GameB" / "b.exe"))
    _touch(str(c / "GameC" / "c.exe"))
    _touch(str(c / "Docs" / "readme.txt"))  # no launcher -> not a member
    t = _by_name(scan_targets(str(tmp_path), RULES, threshold_n=3))["Coll"]
    members = {os.path.basename(m.path) for m in t.members}
    assert members == {"GameA", "GameB", "GameC"}


# --------------------------------------------------------------------------
# Path + index helpers
# --------------------------------------------------------------------------

def test_safe_path_segment():
    assert safe_path_segment("CON").startswith("_")     # reserved device name
    assert safe_path_segment("game.") == "game"          # trailing dot dropped
    assert safe_path_segment("a/b") == "a_b"             # separator sanitized
    assert safe_path_segment("   ") == "Game"            # safe_filename fallback
    assert safe_path_segment("...") == "Folder"          # all-dots -> segment fallback


def test_safe_subpath():
    assert safe_subpath("") == ""
    assert safe_subpath("A/B") == "A/B"
    assert safe_subpath("CON/Game.").split("/") == ["_CON", "Game"]


def test_index_key_flat_and_nested(tmp_path):
    out = str(tmp_path)
    assert storage.index_key(out, out, "GameA.lnk") == "GameA.lnk"
    sub = os.path.join(out, "RenPyCollection")
    assert storage.index_key(out, sub, "GameB.lnk") == "RenPyCollection/GameB.lnk"


def test_index_migration_v1_to_v2(tmp_path):
    out = str(tmp_path)
    with open(os.path.join(out, storage.INDEX_FILE_NAME), "w") as f:
        json.dump({"shortcuts": {"GameA": {"shortcut_name": "GameA.lnk",
                                            "version_str": "1.0", "version_tuple": [1, 0]}}}, f)
    idx = storage.load_shortcut_index(out)
    assert idx["index_version"] == 2
    assert "GameA.lnk" in idx["shortcuts"]
    assert idx["shortcuts"]["GameA.lnk"]["display"] == "GameA"
