"""
Tests for the per-output-folder confirmation cache and the resilient metadata
writes (a read-only / unwritable output folder must never abort an apply).
Cross-platform; runs without Qt.
"""
import json
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
    storage.meta_dir(out)  # the bookkeeping folder now holds the JSON
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


def test_is_dir_writable_true_for_real_dir(tmp_path):
    assert storage.is_dir_writable(str(tmp_path)) is True


def test_is_dir_writable_false_for_nondir(tmp_path):
    afile = tmp_path / "afile"
    afile.write_text("x")
    # Creating a temp file *inside* a regular file is an OSError -> not writable.
    assert storage.is_dir_writable(str(afile)) is False
    # A path that doesn't exist at all is also not writable.
    assert storage.is_dir_writable(str(tmp_path / "missing")) is False


def test_save_apply_error_log_writes_to_output_when_writable(tmp_path):
    out = str(tmp_path)
    path = storage.save_apply_error_log(out, "boom\n")
    # Logs live inside the per-output bookkeeping folder, not the output root.
    assert path and os.path.dirname(path) == storage.meta_dir(out)
    assert os.path.basename(path).startswith("apply_errors_")
    with open(path, encoding="utf-8") as fh:
        assert fh.read() == "boom\n"


def test_save_apply_error_log_falls_back_when_output_unwritable(tmp_path, monkeypatch):
    afile = tmp_path / "afile"
    afile.write_text("x")  # not a directory -> output dir is unwritable
    fallback = tmp_path / "appcfg"
    fallback.mkdir()
    monkeypatch.setattr(storage, "app_config_dir", lambda: str(fallback))

    path = storage.save_apply_error_log(str(afile), "boom\n")
    assert path and os.path.dirname(path) == str(fallback)


# ------------------------------------------------------------------
# Bookkeeping consolidation into META_DIR_NAME (and legacy migration)
# ------------------------------------------------------------------

def test_bookkeeping_written_into_meta_not_output_root(tmp_path):
    out = str(tmp_path)
    storage.save_shortcut_index(out, {"shortcuts": {}})
    storage.save_last_run(out, {"actions": []})
    storage.save_confirmations(out, {"version": 1, "choices": {}})

    meta = os.path.join(out, storage.META_DIR_NAME)
    for name in (storage.INDEX_FILE_NAME, storage.RUN_LOG_NAME, storage.CONFIRM_FILE_NAME):
        assert os.path.exists(os.path.join(meta, name)), name
        # ...and no longer at the output root, where they used to clutter.
        assert not os.path.exists(os.path.join(out, name)), name


def test_backup_dir_lives_inside_meta(tmp_path):
    out = str(tmp_path)
    bdir = storage.backup_dir(out)
    assert os.path.isdir(bdir)
    assert os.path.normpath(bdir) == os.path.normpath(
        os.path.join(out, storage.META_DIR_NAME, storage.BACKUPS_SUBDIR)
    )


def test_migrates_legacy_top_level_files_into_meta(tmp_path):
    out = str(tmp_path)
    # Simulate a pre-consolidation output folder.
    legacy_idx = os.path.join(out, storage.INDEX_FILE_NAME)
    with open(legacy_idx, "w", encoding="utf-8") as f:
        json.dump({"index_version": 2, "shortcuts": {"GameA.lnk": {"display": "GameA"}}}, f)
    legacy_conf = os.path.join(out, storage.CONFIRM_FILE_NAME)
    with open(legacy_conf, "w", encoding="utf-8") as f:
        json.dump({"version": 1, "choices": {"k": {"treat_as_collection": True, "launchers": []}}}, f)

    idx = storage.load_shortcut_index(out)  # triggers migration
    conf = storage.load_confirmations(out)

    # Content preserved...
    assert "GameA.lnk" in idx["shortcuts"]
    assert conf["choices"]["k"]["treat_as_collection"] is True
    # ...moved into the meta folder, and gone from the root.
    meta = os.path.join(out, storage.META_DIR_NAME)
    assert os.path.exists(os.path.join(meta, storage.INDEX_FILE_NAME))
    assert os.path.exists(os.path.join(meta, storage.CONFIRM_FILE_NAME))
    assert not os.path.exists(legacy_idx)
    assert not os.path.exists(legacy_conf)


def test_migrates_legacy_backups_and_resolves_path(tmp_path):
    out = str(tmp_path)
    legacy_backups = os.path.join(out, storage.BACKUP_DIR_NAME)
    os.makedirs(legacy_backups)
    legacy_bak = os.path.join(legacy_backups, "Old Game_20260101-000000.lnk")
    with open(legacy_bak, "w", encoding="utf-8") as f:
        f.write("backup")

    # An undo log (still at the old top level) referencing that backup.
    with open(os.path.join(out, storage.RUN_LOG_NAME), "w", encoding="utf-8") as f:
        json.dump({"actions": [{"lnk": os.path.join(out, "Old Game.lnk"),
                                "backup_path": legacy_bak}]}, f)

    log = storage.load_last_run(out)  # triggers migration of the backups folder
    recorded = log["actions"][0]["backup_path"]
    assert recorded == legacy_bak  # the log still records the old path

    # The legacy folder is gone; the backup now lives under meta/backups, and
    # resolve_backup_path finds it by basename for undo.
    assert not os.path.isdir(legacy_backups)
    resolved = storage.resolve_backup_path(out, recorded)
    assert resolved and os.path.exists(resolved)
    assert os.path.normpath(resolved) == os.path.normpath(
        os.path.join(out, storage.META_DIR_NAME, storage.BACKUPS_SUBDIR, os.path.basename(legacy_bak))
    )
    with open(resolved, encoding="utf-8") as fh:
        assert fh.read() == "backup"
