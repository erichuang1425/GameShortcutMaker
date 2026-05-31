"""Background QThread workers: scanning a game library and applying shortcuts."""
from __future__ import annotations

import os
import time
from typing import List

from PySide6.QtCore import QThread, Signal

from models import ScanItem, ItemDecision
from scanner import (
    find_any_exe_exists, scan_html_candidates, _rel_depth,
    list_game_folders, scan_game_folder_topmost_exes, build_candidates,
)
from collection import iter_game_targets
from versioning import extract_version, strip_version_from_title, compare_versions
from html_scoring import score_html
from shortcut_manager import (
    create_or_replace_shortcut, read_shortcut_target, backup_shortcut,
    create_url_shortcut, find_existing_shortcut, cleanup_duplicate_shortcuts,
    enforce_single_shortcut_type, canonical_paths, read_url_shortcut_target,
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
        if not rel_subdir:
            return self.output_dir
        return os.path.join(self.output_dir, *rel_subdir.split("/"))

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
            if self.detect_collections:
                targets = iter_game_targets(
                    self.game_root, self.rules,
                    self.collection_threshold, self.collection_max_depth,
                )
            else:
                targets = [(gf, "", "") for gf in list_game_folders(self.game_root)]

            n = len(targets)
            if n == 0:
                self.finished.emit([])
                return

            items: List[ScanItem] = []
            for i, (gf, rel_subdir, collection_name) in enumerate(targets, start=1):
                item = self._build_scan_item(gf, rel_subdir, collection_name, shortcuts_meta)
                items.append(item)
                pct = int(i * 100 / n)
                self.progress.emit(pct, f"Scanned {i}/{n}: {item.folder_name}")

            self.finished.emit(items)
        except Exception as e:
            self.failed.emit(str(e))

    def _build_scan_item(self, gf: str, rel_subdir: str, collection_name: str, shortcuts_meta: dict) -> ScanItem:
        folder_name = os.path.basename(gf)
        vstr, vtuple = extract_version(folder_name)
        base_title = strip_version_from_title(folder_name)

        # ------------------------
        # Build EXE candidates (topmost depth)
        # ------------------------
        best_depth, non_ignored, all_best = scan_game_folder_topmost_exes(gf, self.rules)
        if best_depth < 0:
            exes_for_candidates = []
        else:
            exes_for_candidates = non_ignored if non_ignored else all_best

        cands = build_candidates(gf, base_title, best_depth, exes_for_candidates) if exes_for_candidates else []

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
                cmpv = compare_versions(item.version_tuple, item.existing_version_tuple)
                if cmpv > 0:
                    item.decision = ItemDecision.REPLACE
                    item.detail = f"Newer version replaces {item.existing_version_str or 'unknown'} (HTML)"
                else:
                    item.decision = ItemDecision.SKIP
                    item.detail = "Shortcut already exists (kept)"
                    item.selected = False
            else:
                item.decision = ItemDecision.CREATE
                if not item.detail:
                    item.detail = "Ready to create (HTML)"

            return item

        # If no EXE candidates, fallback to HTML ONLY when no EXE exists anywhere
        if not item.exe_candidates:
            if not find_any_exe_exists(gf):
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
                        cmpv = compare_versions(item.version_tuple, item.existing_version_tuple)
                        if cmpv > 0:
                            item.decision = ItemDecision.REPLACE
                            item.detail = f"Newer version replaces {item.existing_version_str or 'unknown'} (HTML)"
                        else:
                            item.decision = ItemDecision.SKIP
                            item.detail = "Shortcut already exists (kept)"
                            item.selected = False
                else:
                    item.decision = ItemDecision.ERROR
                    item.detail = "No EXE found and no HTML found"
                    item.selected = False
            else:
                item.decision = ItemDecision.ERROR
                item.detail = "No EXE found at topmost level"
                item.selected = False

            return item

        # If multiple EXEs, auto-resolve when high confidence
        if len(item.exe_candidates) >= 2:
            top = item.exe_candidates[0]
            second = item.exe_candidates[1]
            if top.score >= 70 or (top.score - second.score) >= 20:
                item.chosen_exe = top.path
                item.recommended_exe = top.path
                item.exe_candidates = [top]
                item.detail = f"Auto-picked (confidence {top.score})"

        # Now handle remaining cases
        if len(item.exe_candidates) > 1:
            item.decision = ItemDecision.NEEDS_RESOLVE
            item.detail = f"{len(item.exe_candidates)} candidates found"
            item.recommended_exe = item.exe_candidates[0].path
        else:
            item.target_type = "exe"
            item.chosen_exe = item.exe_candidates[0].path
            item.recommended_exe = item.chosen_exe

            if item.existing_shortcut_path:
                cmpv = compare_versions(item.version_tuple, item.existing_version_tuple)
                if cmpv > 0:
                    item.decision = ItemDecision.REPLACE
                    item.detail = f"Newer version replaces {item.existing_version_str or 'unknown'}"
                else:
                    item.decision = ItemDecision.SKIP
                    item.detail = "Shortcut already exists (kept)"
                    item.selected = False
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

    def run(self):
        try:
            index = storage.load_shortcut_index(self.output_dir)
            shortcuts_meta = index.setdefault("shortcuts", {})
            backup_dir = storage.backup_dir(self.output_dir)

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
                    item_out_dir = self.output_dir if not rel_subdir else os.path.join(self.output_dir, *rel_subdir.split("/"))
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

                done += 1
                pct = int(done * 100 / total)
                self.progress.emit(pct, f"{done}/{total}: {it.base_title}")

            storage.save_shortcut_index(self.output_dir, index)
            storage.save_last_run(self.output_dir, actions_log)

            self.finished.emit(errors, total)

        except Exception as e:
            self.failed.emit(str(e))
