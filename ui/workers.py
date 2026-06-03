"""Background QThread workers: scanning a game library and applying shortcuts."""
from __future__ import annotations

import os
import time
from typing import List

from PySide6.QtCore import QThread, Signal

from models import ScanItem, ItemDecision
from scanner import (
    scan_html_candidates, scan_swf_candidates, _rel_depth,
    list_game_folders, scan_game_folder_topmost_exes, build_candidates,
)
from collection import scan_targets, GameTarget
from versioning import extract_version, strip_version_from_title, compare_versions
from html_scoring import score_html
from shortcut_manager import (
    create_or_replace_shortcut, read_shortcut_target, backup_shortcut,
    create_url_shortcut, find_existing_shortcut, cleanup_duplicate_shortcuts,
    enforce_single_shortcut_type, canonical_paths, read_url_shortcut_target,
    summarize_errors, target_moved,
)
import storage


class ScanWorker(QThread):
    progress = Signal(int, str)
    finished = Signal(list)
    failed = Signal(str)

    def __init__(self, game_root: str, output_dir: str, rules: dict, prefer_html: bool,
                 detect_collections: bool = False, collection_threshold: int = 3,
                 collection_max_depth: int = 6):
        super().__init__()
        self.game_root = game_root
        self.output_dir = output_dir
        self.rules = rules
        self.prefer_html = prefer_html
        self.detect_collections = detect_collections
        self.collection_threshold = collection_threshold
        self.collection_max_depth = collection_max_depth

    def _item_out_dir(self, rel_subdir: str) -> str:
        return storage.item_output_dir(self.output_dir, rel_subdir)

    def run(self):
        try:
            if not os.path.isdir(self.game_root):
                self.failed.emit("Game root folder is invalid.")
                return
            os.makedirs(self.output_dir, exist_ok=True)

            index = storage.load_shortcut_index(self.output_dir)
            shortcuts_meta = index.get("shortcuts", {})

            # Either treat each top-level folder as one game (legacy), or detect
            # collections and mirror their structure into output subfolders.
            #
            # Collection detection walks the library once (it also records each
            # game's executables, so there is no second per-game walk). It has no
            # cheaply-known total, so report it as an indeterminate "busy" phase
            # (pct = -1) that animates per directory visited; the per-game build
            # loop below then owns the determinate 0-100% band.
            if self.detect_collections:
                self._dirs_seen = 0

                def _classify_cb(dirpath: str):
                    self._dirs_seen += 1
                    # Throttle: emitting every directory would flood the event loop.
                    if self._dirs_seen % 64 == 0:
                        self.progress.emit(
                            -1,
                            f"Detecting collections… {self._dirs_seen} folders scanned: {os.path.basename(dirpath)}",
                        )

                self.progress.emit(-1, "Detecting collections…")
                targets = scan_targets(
                    self.game_root, self.rules,
                    self.collection_threshold, self.collection_max_depth,
                    progress_cb=_classify_cb,
                )
            else:
                # Legacy per-folder scan: each top-level folder is one game and is
                # walked on demand in _build_scan_item (exe_scan=None).
                targets = [GameTarget(gf) for gf in list_game_folders(self.game_root)]

            n = len(targets)
            if n == 0:
                self.finished.emit([])
                return

            items: List[ScanItem] = []
            for i, t in enumerate(targets, start=1):
                if t.is_collection:
                    item = self._build_collection_item(t, shortcuts_meta)
                elif self.detect_collections:
                    # Topmost exes already captured by the single detection walk.
                    item = self._build_scan_item(
                        t.path, t.rel_output_subdir, t.collection_name, shortcuts_meta,
                        (t.best_depth, t.non_ignored_exes, t.all_exes),
                    )
                else:
                    item = self._build_scan_item(
                        t.path, t.rel_output_subdir, t.collection_name, shortcuts_meta, None,
                    )
                items.append(item)
                pct = int(i * 100 / n)
                self.progress.emit(pct, f"Scanning games… {i}/{n}: {item.folder_name}")

            self.finished.emit(items)
        except Exception as e:
            self.failed.emit(str(e))

    def _build_collection_item(self, t: GameTarget, shortcuts_meta: dict) -> ScanItem:
        """Build an unresolved 'collection' item the user confirms in the picker.

        Member items are prebuilt (ready to splice in if confirmed as a
        collection); the item's own exe_candidates are the shallowest sub-exes,
        used only if the user collapses it back into a single game.
        """
        folder_name = os.path.basename(t.path)
        vstr, vtuple = extract_version(folder_name)
        base_title = strip_version_from_title(folder_name)

        members: List[ScanItem] = []
        for m in t.members:
            mi = self._build_scan_item(
                m.path, m.rel_output_subdir, m.collection_name, shortcuts_meta,
                (m.best_depth, m.non_ignored_exes, m.all_exes),
            )
            mi.collection_root = t.path
            members.append(mi)

        exes_for = t.non_ignored_exes if t.non_ignored_exes else t.all_exes
        cands = build_candidates(t.path, base_title, t.best_depth, exes_for) if exes_for else []

        item = ScanItem(
            game_folder=t.path,
            folder_name=folder_name,
            base_title=base_title,
            version_str=vstr,
            version_tuple=vtuple,
            rel_output_subdir="",
            collection_name=t.collection_name,
            exe_candidates=cands,
            is_collection=True,
            collection_members=members,
            collection_root=t.path,
            decision=ItemDecision.NEEDS_RESOLVE,
            detail=f"Collection — {len(members)} sub-games (confirm)",
            selected=False,
        )
        return item

    def _decide_existing(self, item: ScanItem, suffix: str = "") -> None:
        """Set REPLACE/SKIP for an item that already has a shortcut.

        Requires `item.chosen_exe` to be populated. A newer version replaces the
        old shortcut; a same-version item whose launcher path no longer matches
        the recorded one (the files were relocated, e.g. by Flatten) is refreshed
        so the shortcut targets the new location instead of being silently kept.
        `suffix` annotates the detail (" (HTML)" for HTML targets)."""
        cmpv = compare_versions(item.version_tuple, item.existing_version_tuple)
        if cmpv > 0:
            item.decision = ItemDecision.REPLACE
            item.detail = f"Newer version replaces {item.existing_version_str or 'unknown'}{suffix}"
            item.selected = True
        elif cmpv == 0 and target_moved(item.existing_target, item.chosen_exe):
            item.decision = ItemDecision.REPLACE
            item.detail = f"Launcher moved — will refresh shortcut{suffix}"
            item.selected = True
        else:
            item.decision = ItemDecision.SKIP
            item.detail = "Shortcut already exists (kept)"
            item.selected = False

    def _build_scan_item(self, gf: str, rel_subdir: str, collection_name: str,
                         shortcuts_meta: dict, exe_scan=None) -> ScanItem:
        folder_name = os.path.basename(gf)
        vstr, vtuple = extract_version(folder_name)
        base_title = strip_version_from_title(folder_name)

        # ------------------------
        # Build EXE candidates (topmost depth). When collection detection ran it
        # already captured this during its single walk (exe_scan); otherwise walk
        # the folder now. Either source is authoritative, so best_depth >= 0 is an
        # exact "an .exe exists somewhere" check (no extra find_any_exe_exists walk).
        # ------------------------
        if exe_scan is None:
            best_depth, non_ignored, all_best = scan_game_folder_topmost_exes(gf, self.rules)
        else:
            best_depth, non_ignored, all_best = exe_scan
        if best_depth < 0:
            exes_for_candidates = []
        else:
            exes_for_candidates = non_ignored if non_ignored else all_best

        cands = build_candidates(gf, base_title, best_depth, exes_for_candidates) if exes_for_candidates else []

        # No usable .exe at the topmost level: treat a .swf (Flash) file as an
        # exe-equivalent launcher so Flash-only games still get a .lnk straight to
        # the Flash file. Done only when no .exe exists (so a real .exe always
        # wins) and before the HTML fallback below; the resulting candidates flow
        # through the normal exe path — picker, auto-pick, and version/replace
        # logic all apply, identical to an .exe launcher.
        if not cands:
            swfs = scan_swf_candidates(gf)
            if swfs:
                swf_depth = min(_rel_depth(gf, os.path.dirname(p)) for p in swfs)
                topmost = [p for p in swfs if _rel_depth(gf, os.path.dirname(p)) == swf_depth]
                cands = build_candidates(gf, base_title, swf_depth, topmost)

        item = ScanItem(
            game_folder=gf,
            folder_name=folder_name,
            base_title=base_title,
            version_str=vstr,
            version_tuple=vtuple,
            rel_output_subdir=rel_subdir,
            collection_name=collection_name,
            exe_candidates=cands,
        )

        display_name = base_title
        item_out_dir = self._item_out_dir(rel_subdir)

        # ------------------------
        # Existing shortcut detection (filesystem-first; .lnk/.url equivalent,
        # numbered duplicates included). Looks in this game's output subfolder.
        # ------------------------
        existing_path, existing_type = find_existing_shortcut(item_out_dir, display_name)
        item.existing_shortcut_path = existing_path

        # Version meta (used only for version comparison, not existence). Keyed by
        # the collision-free relative path; falls back to the legacy display-name key.
        meta = {}
        if existing_path:
            key = storage.index_key(self.output_dir, item_out_dir, os.path.basename(existing_path))
            meta = shortcuts_meta.get(key) or shortcuts_meta.get(display_name, {})
        item.existing_version_str = meta.get("version_str", "")
        item.existing_version_tuple = tuple(meta.get("version_tuple", [])) if meta.get("version_tuple") else tuple()
        item.existing_target = meta.get("target", "")

        # If no meta target but file exists, best-effort recover
        if item.existing_shortcut_path and not item.existing_target:
            try:
                if existing_type == "html" or item.existing_shortcut_path.lower().endswith(".url"):
                    item.existing_target = read_url_shortcut_target(item.existing_shortcut_path)
                else:
                    item.existing_target = read_shortcut_target(item.existing_shortcut_path)
            except Exception:
                item.existing_target = ""

        # ------------------------
        # Prefer HTML (if enabled) — only if high-confidence HTML exists
        # This can override EXE even if EXEs exist.
        # ------------------------
        if self.prefer_html:
            htmls = scan_html_candidates(gf)
            if htmls:
                scored_html = []
                for hp in htmls:
                    d = _rel_depth(gf, hp)
                    sc, _ = score_html(hp, base_title, d)
                    scored_html.append((sc, hp))
                scored_html.sort(key=lambda x: x[0], reverse=True)

                best_html_score, best_html = scored_html[0]
                item.html_candidates = [hp for (_sc, hp) in scored_html]
                HTML_SCORE_THRESHOLD = 40  # protects against docs/readme

                if best_html_score >= HTML_SCORE_THRESHOLD:
                    item.target_type = "html"
                    item.chosen_exe = best_html
                    item.recommended_exe = best_html
                    item.detail = "HTML preferred over EXE"

        # ------------------------
        # Decision logic
        # ------------------------

        # If HTML preference already selected a target
        if item.target_type == "html" and item.chosen_exe:
            # Determine create/replace/skip based on existing shortcut + version
            if item.existing_shortcut_path:
                self._decide_existing(item, suffix=" (HTML)")
            else:
                item.decision = ItemDecision.CREATE
                if not item.detail:
                    item.detail = "Ready to create (HTML)"

            return item

        # No .exe and no .swf launcher: fall back to an HTML entry point. (A .swf
        # would already have populated exe_candidates above, so it is preferred
        # over HTML.) Reached only when best_depth < 0 — no .exe anywhere.
        if not item.exe_candidates:
            if best_depth < 0:
                htmls = scan_html_candidates(gf)
                if htmls:
                    scored = []
                    for hp in htmls:
                        d = _rel_depth(gf, hp)
                        sc, reason = score_html(hp, base_title, d)
                        scored.append((sc, hp, reason))
                    scored.sort(key=lambda x: x[0], reverse=True)

                    best = scored[0][1]
                    item.html_candidates = [hp for (_sc, hp, _r) in scored]
                    item.target_type = "html"
                    item.recommended_exe = best
                    item.chosen_exe = best
                    item.decision = ItemDecision.CREATE
                    item.detail = f"HTML entry found ({os.path.basename(best)})"

                    if item.existing_shortcut_path:
                        self._decide_existing(item, suffix=" (HTML)")
                else:
                    item.decision = ItemDecision.ERROR
                    item.detail = "No .exe/.swf launcher or HTML entry point found"
                    item.selected = False
            else:
                item.decision = ItemDecision.ERROR
                item.detail = "No usable launcher found at topmost level"
                item.selected = False

            return item

        # If multiple EXEs, auto-resolve when one is clearly best. Keep all
        # candidates (don't truncate) so the user can still open the picker and
        # choose several launchers -> several shortcuts for a confident game.
        auto_pick = ""
        if len(item.exe_candidates) >= 2:
            top = item.exe_candidates[0]
            second = item.exe_candidates[1]
            if top.score >= 70 or (top.score - second.score) >= 20:
                auto_pick = top.path
                item.detail = f"Auto-picked (confidence {top.score})"

        # Now handle remaining cases
        if len(item.exe_candidates) > 1 and not auto_pick:
            item.decision = ItemDecision.NEEDS_RESOLVE
            item.detail = f"{len(item.exe_candidates)} candidates found"
            item.recommended_exe = item.exe_candidates[0].path
        else:
            item.target_type = "exe"
            item.chosen_exe = auto_pick or item.exe_candidates[0].path
            item.recommended_exe = item.chosen_exe

            if item.existing_shortcut_path:
                self._decide_existing(item)
            else:
                item.decision = ItemDecision.CREATE
                item.detail = "Ready to create"

        return item


class ApplyWorker(QThread):
    progress = Signal(int, str)   # percent, message
    finished = Signal(int, int)   # errors, total
    failed = Signal(str)

    def __init__(self, items: list, output_dir: str, dry_run: bool):
        super().__init__()
        self.items = items
        self.output_dir = output_dir
        self.dry_run = dry_run
        # Non-fatal issues (e.g. a read-only output folder that blocks the
        # bookkeeping files). Surfaced in the completion dialog; never aborts.
        self.warnings: list[str] = []
        # Per-item apply failures, so a run with many errors is diagnosable
        # instead of a bare count. Aggregated into error_summary and exported
        # to error_log_path after the run.
        self.error_details: list[str] = []
        self.error_summary: dict = {}
        self.error_log_path: str = ""

    def run(self):
        try:
            index = storage.load_shortcut_index(self.output_dir)
            shortcuts_meta = index.setdefault("shortcuts", {})
            # Resolve the backup folder only for a real run — a Dry Run must not
            # create any files/folders (backup_shortcut makedirs it lazily when a
            # replace actually backs something up).
            backup_dir = storage.backup_dir(self.output_dir) if not self.dry_run else ""

            # Decide effective operations (same logic as UI)
            to_apply = []
            for it in self.items:
                if not getattr(it, "selected", False):
                    continue
                if not getattr(it, "chosen_exe", ""):
                    continue

                decision = it.decision
                if getattr(it, "existing_shortcut_path", "") and getattr(it, "force_replace", False):
                    decision = ItemDecision.REPLACE

                if decision in (ItemDecision.CREATE, ItemDecision.REPLACE):
                    to_apply.append((it, decision))

            total = len(to_apply)
            if total == 0:
                self.finished.emit(0, 0)
                return

            actions_log = {
                "timestamp": time.strftime("%Y-%m-%d %H:%M:%S"),
                "output_dir": self.output_dir,
                "actions": []
            }

            done = 0
            errors = 0

            for it, decision in to_apply:
                try:
                    display = it.base_title
                    tt = getattr(it, "target_type", "exe")  # "exe" or "html"
                    rel_subdir = getattr(it, "rel_output_subdir", "") or ""

                    # Mirror collection structure: write into the matching subfolder.
                    item_out_dir = storage.item_output_dir(self.output_dir, rel_subdir)
                    if not self.dry_run:
                        os.makedirs(item_out_dir, exist_ok=True)

                    canonical_lnk, canonical_url = canonical_paths(item_out_dir, display)
                    out_path = canonical_url if tt == "html" else canonical_lnk

                    # -----------------------------------------
                    # Clean numbered duplicates (Name (1).lnk/.url) and ensure only
                    # one shortcut type exists (remove the opposite type).
                    # -----------------------------------------
                    if not self.dry_run:
                        cleanup_duplicate_shortcuts(item_out_dir, display)
                    enforce_single_shortcut_type(item_out_dir, display, tt, self.dry_run)

                    # -----------------------------------------
                    # Backup on replace (backup whatever file we are replacing)
                    # -----------------------------------------
                    backup_path = ""
                    if decision == ItemDecision.REPLACE and os.path.exists(out_path) and not self.dry_run:
                        backup_path = backup_shortcut(out_path, backup_dir, name_prefix=rel_subdir.replace("/", "_"))

                    # -----------------------------------------
                    # Write shortcut
                    # -----------------------------------------
                    if not self.dry_run:
                        if tt == "html":
                            create_url_shortcut(out_path, it.chosen_exe)
                        else:
                            create_or_replace_shortcut(out_path, it.chosen_exe)

                    # -----------------------------------------
                    # Update index (collision-free key includes the subfolder).
                    # Drop any stale opposite-type entry for the same game.
                    # -----------------------------------------
                    other_name = os.path.basename(canonical_lnk if tt == "html" else canonical_url)
                    shortcuts_meta.pop(storage.index_key(self.output_dir, item_out_dir, other_name), None)
                    shortcuts_meta[storage.index_key(self.output_dir, item_out_dir, os.path.basename(out_path))] = {
                        "shortcut_name": os.path.basename(out_path),
                        "display": display,
                        "rel_output_subdir": rel_subdir,
                        "target": it.chosen_exe,
                        "target_type": tt,
                        "game_folder": it.game_folder,
                        "version_str": it.version_str,
                        "version_tuple": list(it.version_tuple),
                    }

                    actions_log["actions"].append({
                        "type": "replace" if decision == ItemDecision.REPLACE else "create",
                        "display": display,
                        "lnk": out_path,
                        "target": it.chosen_exe,
                        "backup_path": backup_path,
                    })

                    # Update item state for UI
                    it.existing_shortcut_path = out_path
                    it.existing_target = it.chosen_exe
                    it.existing_version_str = it.version_str
                    it.existing_version_tuple = it.version_tuple

                    it.detail = "Dry Run OK" if self.dry_run else "Applied ✅"
                    it.selected = False
                    it.force_replace = False

                except Exception as e:
                    errors += 1
                    it.detail = f"Apply error: {e}"
                    self.error_details.append(f"{getattr(it, 'base_title', '?')}: {e}")

                done += 1
                pct = int(done * 100 / total)
                self.progress.emit(pct, f"{done}/{total}: {it.base_title}")

            # Persist bookkeeping last. These are best-effort: a read-only or
            # encrypted output folder must not fail an apply whose shortcuts were
            # already written — surface a warning instead of aborting.
            if not self.dry_run:
                if not storage.save_shortcut_index(self.output_dir, index):
                    self.warnings.append(
                        "Could not write the shortcut index (.shortcut_index.json) — "
                        "the output folder may be read-only. Shortcuts were still created, "
                        "but version tracking/undo for them is limited."
                    )
                if not storage.save_last_run(self.output_dir, actions_log):
                    self.warnings.append(
                        "Could not write the undo log (.last_run.json) — the output folder "
                        "may be read-only."
                    )

            # Aggregate per-item failures and export the full list so a run with
            # many errors is diagnosable (the completion dialog shows only counts
            # + a summary). Written to a writable place — the output folder may
            # be the very thing that is read-only.
            self.error_summary = summarize_errors(self.error_details)
            if self.error_details and not self.dry_run:
                report = [
                    "Game Shortcut Maker — apply error report",
                    f"When:   {time.strftime('%Y-%m-%d %H:%M:%S')}",
                    f"Output: {self.output_dir}",
                    f"Errors: {errors} of {total}",
                    "",
                    "Summary:",
                ]
                for cat, n in sorted(self.error_summary.items(), key=lambda kv: -kv[1]):
                    report.append(f"  {n} x {cat}")
                report += ["", "Details:"]
                report += [f"  {d}" for d in self.error_details]
                self.error_log_path = storage.save_apply_error_log(
                    self.output_dir, "\n".join(report) + "\n"
                )

            self.finished.emit(errors, total)

        except Exception as e:
            self.failed.emit(str(e))


class SquashWorker(QThread):
    """Flatten redundant single-child folder nesting for a list of SquashPlans.

    Moves happen within each game folder (same volume), so each is an instant
    rename; the worker exists to keep the UI responsive over a large library and
    to collect per-folder failures without aborting the whole run.
    """
    progress = Signal(int, str)            # percent, message
    finished = Signal(list, list)          # undo records (applied), error strings
    failed = Signal(str)

    def __init__(self, plans: list):
        super().__init__()
        self.plans = plans

    def run(self):
        try:
            from squash import execute_squash

            total = len(self.plans)
            records: list[dict] = []
            errors: list[str] = []

            for i, plan in enumerate(self.plans, start=1):
                name = os.path.basename(plan.game_folder)
                try:
                    rec = execute_squash(plan)
                    if rec.get("applied"):
                        records.append(rec)
                except Exception as e:
                    errors.append(f"{name}: {e}")
                self.progress.emit(int(i * 100 / total), f"Flattening… {i}/{total}: {name}")

            self.finished.emit(records, errors)
        except Exception as e:
            self.failed.emit(str(e))
