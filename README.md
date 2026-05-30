# Game Shortcut Maker

A small Windows desktop app (PySide6 / Qt) that scans a folder full of games and
creates Windows shortcuts (`.lnk` for executables, `.url` for HTML launchers) for
each one in an output folder of your choice. It is **safe by default**: nothing is
written until you review the results and click Apply, and you can always do a Dry
Run first.

## What it does

1. **Scan** — point it at a *game root* folder. Each subfolder is treated as a
   game; the app finds the most likely launcher (scoring executables by name,
   depth, size, and an ignore list that filters out installers, redists,
   crash handlers, etc.).
2. **Review** — inspect every result in a table. Pick a different launcher when
   several executables are found, filter by status, search, and choose what to
   apply.
3. **Apply** — write the shortcuts. Existing shortcuts are skipped unless the
   game's folder name carries a newer version (e.g. `v0.14` → `0.14.17`), in
   which case they are replaced. Replaced shortcuts are backed up first, and the
   last run can be undone.

## Collections (mirroring nested folders)

Sometimes a folder under the game root isn't a single game but a **collection**:
a folder whose subfolders are each their own game. When *Detect game collections*
is enabled, the app recognizes this and **mirrors the source folder structure**
in the output dir, creating a subfolder of shortcuts instead of one ambiguous
shortcut for the whole bundle.

```
GameRoot/                          Output/
  SoloGame/                          SoloGame.lnk
    game.exe
  RenPyCollection/         ─────►    RenPyCollection/
    GameA v1.0/                        GameA.lnk
      GameA.exe                        GameB.lnk
    GameB/                             GameC.lnk
      bin/GameB.exe
    GameC/
      GameC.exe
```

Detection is **recursive** (a collection can contain sub-collections, nested as
deep as the folder tree goes). A folder is treated as a collection only when it
contains at least *N* game-bearing subfolders — **N is configurable on the setup
page (default 3)**. Architecture/version variants of a single game (e.g.
`Game win32` / `Game win64`) are detected and kept as one game rather than being
split into a collection. The whole feature is a toggle, so you can fall back to
flat, one-shortcut-per-top-folder behavior at any time.

## Requirements

- **Windows** (shortcut creation uses `win32com` from `pywin32`).
- Python 3.9+.

```bash
pip install -r requirements.txt
```

## Run

```bash
python main.py
```

## Build a standalone executable

```bash
pyinstaller main.py --onefile --windowed
```

## Tips

- Existing shortcuts show up as **Skipped** by default.
- If a folder name has a version, newer versions replace older ones.
- If multiple executables are found, you pick the launcher (a *Recommended*
  option is highlighted).
- Use **Ignore rules** to add patterns (e.g. `*setup*.exe`, `*\tools\*`) that
  should never be chosen as a launcher.
- Always **Dry Run** first if you're unsure.

## Tests

The folder-classification logic and path/index helpers are pure and run
cross-platform (no Windows or Qt needed):

```bash
pytest tests/ -v
```

The GUI and the actual shortcut-writing path require Windows.

## Project layout

| File | Responsibility |
|------|----------------|
| `main.py` | Entry point (`run_app()`). |
| `app.py` | Qt GUI, scan/apply workers, review table. |
| `scanner.py` | Folder traversal and topmost-executable discovery. |
| `collection.py` | Pure recursive collection vs. game classifier. |
| `exe_scoring.py` / `html_scoring.py` | Heuristics for ranking launchers. |
| `rules.py` | Ignore patterns (installers, redists, tools, …). |
| `versioning.py` | Version parsing and comparison from folder names. |
| `shortcut_manager.py` | Shortcut creation, cleanup, backups, safe names. |
| `storage.py` | Settings, ignore rules, the per-output shortcut index, run log. |
| `models.py` | `ScanItem` / `ExeCandidate` / `ItemDecision` data types. |
