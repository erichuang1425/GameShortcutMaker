"""
Tests for shortcut icon selection (icon_extract).

The .exe resource parsing/assembly is pure byte work and is tested directly;
the Windows-only extraction (best_icon / generate_filled_ico) is exercised via
monkeypatch so the resolve_shortcut_icon decision tree is covered cross-platform.
"""
import os
import struct

import icon_extract
from icon_extract import (
    parse_group_max_frame, best_group, assemble_ico, resolve_shortcut_icon,
    ICON_FILL_MIN,
)


def _group(widths, ids=None):
    """Build a GRPICONDIR blob with one entry per width (0/byte-overflow -> 256)."""
    blob = struct.pack("<HHH", 0, 1, len(widths))
    for i, w in enumerate(widths):
        wb = 0 if w >= 256 else w
        n_id = ids[i] if ids else (i + 1)
        # bWidth bHeight bColorCount bReserved wPlanes wBitCount dwBytesInRes nID
        blob += struct.pack("<BBBBHHIH", wb, wb, 0, 0, 1, 32, 1000, n_id)
    return blob


# --------------------------------------------------------------------------
# parse_group_max_frame
# --------------------------------------------------------------------------

def test_parse_group_max_frame_picks_largest():
    assert parse_group_max_frame(_group([16, 32, 48])) == 48


def test_parse_group_max_frame_zero_byte_means_256():
    # The width byte can't hold 256, so 0 encodes it.
    assert parse_group_max_frame(_group([16, 256])) == 256


def test_parse_group_max_frame_malformed_returns_zero():
    assert parse_group_max_frame(b"") == 0
    assert parse_group_max_frame(b"\x00\x00") == 0  # shorter than the 6-byte header


# --------------------------------------------------------------------------
# best_group: index of the largest-frame group, ties -> lower index
# --------------------------------------------------------------------------

def test_best_group_picks_largest_frame_index():
    # Mirrors the real Balatro case: tiny default group, big icon in a later one.
    blobs = [_group([16, 32]), _group([16, 32, 48, 64, 128, 256])]
    assert best_group(blobs) == (1, 256)


def test_best_group_tie_prefers_lower_index():
    # Two equally large groups -> keep the authentic default (index 0).
    blobs = [_group([256]), _group([256])]
    assert best_group(blobs) == (0, 256)


def test_best_group_empty_returns_zero():
    assert best_group([]) == (0, 0)


# --------------------------------------------------------------------------
# assemble_ico: multi-frame .ico byte layout
# --------------------------------------------------------------------------

def test_assemble_ico_layout_and_offsets():
    data = assemble_ico([(256, b"AAAA"), (32, b"BB")])

    reserved, type_, count = struct.unpack("<HHH", data[:6])
    assert (reserved, type_, count) == (0, 1, 2)

    w0, h0, _, _, planes, bits, size0, off0 = struct.unpack("<BBBBHHII", data[6:22])
    assert w0 == 0 and h0 == 0          # 256 stored as 0
    assert (planes, bits) == (1, 32)
    assert size0 == 4 and off0 == 6 + 16 * 2  # first payload after dir

    w1, _, _, _, _, _, size1, off1 = struct.unpack("<BBBBHHII", data[22:38])
    assert w1 == 32 and size1 == 2 and off1 == off0 + size0

    assert data[off0:off0 + size0] == b"AAAA"
    assert data[off1:off1 + size1] == b"BB"


def test_assemble_ico_drops_empty_frames():
    data = assemble_ico([(256, b""), (32, b"BB")])
    _r, _t, count = struct.unpack("<HHH", data[:6])
    assert count == 1


# --------------------------------------------------------------------------
# resolve_shortcut_icon decision tree (best_icon / generate monkeypatched)
# --------------------------------------------------------------------------

def test_resolve_big_embedded_icon_uses_that_index(monkeypatch):
    monkeypatch.setattr(icon_extract, "best_icon", lambda p: (2, 256))
    assert resolve_shortcut_icon("X.exe", "/cache") == ("X.exe", 2)


def test_resolve_no_group_icon_falls_back_to_default(monkeypatch):
    monkeypatch.setattr(icon_extract, "best_icon", lambda p: (0, 0))
    assert resolve_shortcut_icon("X.exe", "/cache") == ("X.exe", 0)


def test_resolve_small_icon_without_cache_keeps_index(monkeypatch):
    # A small icon but no cache dir to write a synthesized one -> best we can do
    # is point at the (small) best embedded group.
    monkeypatch.setattr(icon_extract, "best_icon", lambda p: (1, ICON_FILL_MIN - 1))
    assert resolve_shortcut_icon("X.exe", None) == ("X.exe", 1)


def test_resolve_small_icon_generates_upscaled(monkeypatch, tmp_path):
    monkeypatch.setattr(icon_extract, "best_icon", lambda p: (1, 48))
    seen = {}

    def fake_gen(exe, idx, dest):
        seen["args"] = (exe, idx, dest)
        open(dest, "wb").close()
        return True

    monkeypatch.setattr(icon_extract, "generate_filled_ico", fake_gen)

    icon_path, index = resolve_shortcut_icon("D:/g/X.exe", str(tmp_path))
    assert index == 0
    assert icon_path == seen["args"][2]
    assert seen["args"][0] == "D:/g/X.exe" and seen["args"][1] == 1
    assert icon_path.endswith(".ico")
    assert os.path.dirname(icon_path) == str(tmp_path)


def test_resolve_small_icon_generate_failure_keeps_index(monkeypatch, tmp_path):
    monkeypatch.setattr(icon_extract, "best_icon", lambda p: (1, 48))
    monkeypatch.setattr(icon_extract, "generate_filled_ico", lambda *a: False)
    assert resolve_shortcut_icon("X.exe", str(tmp_path)) == ("X.exe", 1)


def test_resolve_at_threshold_uses_embedded(monkeypatch):
    # Exactly ICON_FILL_MIN is "good enough" -> no synthesis.
    monkeypatch.setattr(icon_extract, "best_icon", lambda p: (0, ICON_FILL_MIN))
    assert resolve_shortcut_icon("X.exe", "/cache") == ("X.exe", 0)


def test_resolve_swallows_best_icon_exception(monkeypatch):
    def boom(p):
        raise RuntimeError("resource read failed")

    monkeypatch.setattr(icon_extract, "best_icon", boom)
    assert resolve_shortcut_icon("X.exe", "/cache") == ("X.exe", 0)


# --------------------------------------------------------------------------
# _cache_name: stable, case-insensitive, safe filename
# --------------------------------------------------------------------------

def test_cache_name_is_case_insensitive_and_stable():
    a = icon_extract._cache_name("D:/Games/Foo/Game.exe")
    b = icon_extract._cache_name("d:/games/foo/game.exe")
    assert a == b
    assert a.endswith(".ico")


def test_cache_name_differs_per_target():
    a = icon_extract._cache_name("D:/Games/Foo/Game.exe")
    b = icon_extract._cache_name("D:/Games/Bar/Game.exe")
    assert a != b  # same stem, different path -> different hash
