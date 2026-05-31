"""
Tests for the per-output-folder confirmation cache and the resilient metadata
writes (a read-only / unwritable output folder must never abort an apply).
Cross-platform; runs without Qt.
"""
import os

import storage


def test_load_confirmations_default_when_missing(tmp_path):
    data = storage.load_confirmations(str(tmp_path))
    assert data == {"version": 1, "choices": {}}


def test_confirmations_round_trip(tmp_path):
    out = str(tmp_path)
    data = {
        "version": 1,
        "choices": {
            os.path.join(out, "SomeGame"): {
                "treat_as_collection": False,
                "launchers": [{"type": "exe", "path": os.path.join(out, "SomeGame", "Game.exe")}],
            }
        },
    }
    assert storage.save_confirmations(out, data) is True
    again = storage.load_confirmations(out)
    assert again["choices"][os.path.join(out, "SomeGame")]["launchers"][0]["type"] == "exe"


def test_load_confirmations_repairs_garbage(tmp_path):
    out = str(tmp_path)
    with open(storage.confirmations_path(out), "w") as f:
        f.write("not json {{{")
    data = storage.load_confirmations(out)
    assert data == {"version": 1, "choices": {}}


def test_save_shortcut_index_returns_false_when_unwritable(tmp_path):
    # Point the "output dir" at a regular file: writing a child path under it
    # raises NotADirectoryError (an OSError), which must be swallowed -> False.
    bogus_dir = tmp_path / "this_is_a_file"
    bogus_dir.write_text("x")
    ok = storage.save_shortcut_index(str(bogus_dir), {"shortcuts": {}})
    assert ok is False


def test_save_last_run_returns_false_when_unwritable(tmp_path):
    bogus_dir = tmp_path / "afile"
    bogus_dir.write_text("x")
    assert storage.save_last_run(str(bogus_dir), {"actions": []}) is False


def test_save_index_succeeds_normally(tmp_path):
    assert storage.save_shortcut_index(str(tmp_path), {"shortcuts": {}}) is True
    assert os.path.exists(storage.index_path_for_output(str(tmp_path)))
