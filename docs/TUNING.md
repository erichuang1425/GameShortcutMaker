# Tuning collection detection and launcher scoring

Game Shortcut Maker classifies each top-level folder under your game root as a
single **game**, a **collection** of games, or **empty**, and then scores the
executables (or HTML entry points) inside a game to pick the launcher. A few
constants control that behavior. This document explains what they do and where
they live so you can tune them with confidence.

## Collection detection

These are persisted per user in `settings.json` (see `storage.py`,
`load_settings()`), and passed into `collection.classify_tree()` /
`collection.iter_game_targets()`.

| Setting (`settings.json`) | Constant (`collection.py`) | Default | Meaning |
|---------------------------|----------------------------|---------|---------|
| `detect_collections`      | —                          | `True`  | Master switch for recursive collection detection. |
| `collection_threshold`    | `DEFAULT_THRESHOLD`        | `3`     | Minimum number of **distinct** game-bearing subfolders a folder must contain before it is treated as a collection rather than a single game. |
| `collection_max_depth`    | `DEFAULT_MAX_DEPTH`        | `6`     | How many folder levels deep the classifier will recurse before deciding a folder is a game (if a launcher exists anywhere below it) or empty. |

### How the threshold works

A folder becomes a **collection** only when it has at least
`collection_threshold` immediate subfolders that are themselves games or
collections **and** those subfolders represent at least `collection_threshold`
*distinct* titles. The distinctness check (`collection._variant_title`) strips
version strings and architecture tokens (`x86_64`, `win64`, `64bit`, …) so that
`MyGame-win32` and `MyGame-win64` count as **one** game, not two. This stops a
single game shipped in several architecture/version variants from being
misclassified as a collection.

Raise the threshold if shallow folders of closely related games are being
split into collections; lower it (to `2`) if you want smaller groupings to be
mirrored.

### How the depth limit works

`classify_tree` recurses up to `collection_max_depth` levels. As soon as a
launcher sits **directly** in a folder, that folder is a game and recursion
stops there. At the depth limit, a folder is a game if any launcher exists in
its subtree, otherwise empty. Increase the depth only if your library nests
games unusually deeply; deeper limits mean more filesystem traversal.

## HTML launcher scoring

Some games (RenPy web exports, HTML5 games) launch from an HTML file rather
than an `.exe`. `html_scoring.score_html()` scores candidate `.html` / `.htm`
files; higher is more likely to be the real entry point:

- `index.html` / `index.htm` gets a strong bonus.
- A filename matching the game title gets a bonus.
- Documentation-like names (`readme`, `changelog`, `manual`, `license`,
  `credits`, `doc`) are penalized.
- Files closer to the top of the folder score higher.

### The `HTML_LAUNCHER_THRESHOLD` coupling

`collection.py` decides whether a folder's HTML file qualifies as a *launcher*
(and therefore makes the folder a game) using:

```python
HTML_LAUNCHER_THRESHOLD = 40  # collection.py
```

A folder is considered to have an HTML launcher when some HTML file scores
**at least 40**. With the current `score_html` weights this means `index.html`
qualifies while `readme.html` does not — which is exactly the intent. Because
the threshold and the scoring weights are coupled, changing one can silently
change which folders are detected as HTML games. That coupling is pinned by a
regression test (`tests/test_scoring.py`): `index.html` must score `>= 40` and
`readme.html` must score `< 40`. If you adjust `score_html`'s weights, update
the threshold and keep that test green.

## Executable scoring

`exe_scoring.score_exe()` ranks `.exe` candidates within a game folder. It
rewards title matches, "good" tokens (`launcher`, `game`, `client`, `shipping`,
…) and larger binaries, while penalizing installer/utility tokens (`setup`,
`unins`, `config`, `crash`, `vcredist`, …) and deeper nesting. The hard ignore
list (installers, redistributables, tools) lives separately in `rules.py`
(`default_rules()`), which is also persisted to and loaded from `rules.json`.
