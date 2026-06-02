"""The three-page main window: Setup -> Review -> Confirm."""
from __future__ import annotations

import os
import re
import copy
import time
import shutil
from typing import List

from PySide6.QtCore import Qt, QPoint
from PySide6.QtGui import QAction
from PySide6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QFileDialog, QLineEdit, QMessageBox, QStackedWidget, QTableWidget, QTableWidgetItem,
    QHeaderView, QCheckBox, QProgressBar, QDialog, QGroupBox, QFormLayout, QTextEdit,
    QComboBox, QMenu, QToolButton, QStyle, QSpinBox,
)

from models import ScanItem, ItemDecision
from versioning import compare_versions
from shortcut_manager import (
    ensure_windows_shortcut_support, multi_shortcut_names, find_existing_shortcut,
)
from rules import default_rules
import storage

from ui.theme import THEMES, apply_theme
from ui.workers import ScanWorker, ApplyWorker
from ui.dialogs import DuplicateFolderDialog, LauncherPickerDialog


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Game Shortcut Maker")
        self.resize(1180, 760)

        self.settings = storage.load_settings()
        self.rules = storage.load_rules(default_rules())

        self.items: List[ScanItem] = []
        self.game_root = ""
        self.output_dir = ""
        # Remembered launcher choices, keyed by source folder (persisted per
        # output folder). Loaded after each scan; see _on_scan_finished.
        self.confirm_cache: dict = {"version": 1, "choices": {}}
        # Lazily-loaded shortcut index meta (for version comparison when a pick
        # re-detects an existing shortcut). Reset at the start of each scan.
        self._scan_index_meta = None

        self.stack = QStackedWidget()
        self.setCentralWidget(self.stack)

        self.page_setup = self._build_setup()
        self.page_review = self._build_review()
        self.page_confirm = self._build_confirm()

        self.stack.addWidget(self.page_setup)
        self.stack.addWidget(self.page_review)
        self.stack.addWidget(self.page_confirm)
        self.stack.setCurrentWidget(self.page_setup)

        theme_name = self.settings.get("theme", "Paper Light")
        apply_theme(QApplication.instance(), theme_name)
        self.theme_combo.setCurrentText(theme_name)
        self.theme_combo.currentTextChanged.connect(self._on_theme_changed)

    def _on_theme_changed(self, name: str):
        apply_theme(QApplication.instance(), name)
        self.settings["theme"] = name
        storage.save_settings(self.settings)


    # ---------------- Setup page ----------------
    def _build_setup(self) -> QWidget:
        w = QWidget()
        root = QVBoxLayout(w)
        root.setSpacing(12)

        header = QLabel(
            "<h2 style='margin:0;'>Game Shortcut Maker</h2>"
            "<div style='color:#9aa6c2;'>Scan → Review → Apply. Safe by default.</div>"
        )
        header.setTextFormat(Qt.RichText)
        root.addWidget(header)

        theme_row = QHBoxLayout()
        theme_row.addWidget(QLabel("Theme:"))
        self.theme_combo = QComboBox()
        self.theme_combo.addItems(list(THEMES.keys()))
        self.theme_combo.setCurrentText("Midnight Blue")
        theme_row.addWidget(self.theme_combo)
        theme_row.addStretch(1)
        root.addLayout(theme_row)

        card = QGroupBox("Step 1 — Choose folders")
        form = QFormLayout(card)

        self.ed_root = QLineEdit(self.settings.get("game_root", ""))
        self.ed_out = QLineEdit(self.settings.get("shortcut_output", ""))

        b1 = QToolButton()
        b1.setText("Browse…")
        b2 = QToolButton()
        b2.setText("Browse…")

        r1 = QHBoxLayout()
        r1.addWidget(self.ed_root, 1)
        r1.addWidget(b1)

        r2 = QHBoxLayout()
        r2.addWidget(self.ed_out, 1)
        r2.addWidget(b2)

        form.addRow("Game root folder:", r1)
        form.addRow("Shortcut output folder:", r2)

        root.addWidget(card)

        tips = QGroupBox("What you’ll see next")
        tl = QVBoxLayout(tips)
        tl.addWidget(QLabel(
            "• Existing shortcuts show up as <b>Skipped</b> by default.\n"
            "• If a folder name has a version (e.g. v0.14 or 0.14.17), newer versions replace older ones.\n"
            "• If multiple EXEs are found, you pick the launcher (a Recommended option is highlighted).\n"
            "• You can Dry Run before writing anything."
        ))
        root.addWidget(tips)

        self.cb_prefer_html = QCheckBox("Prefer HTML launcher if present")
        self.cb_prefer_html.setChecked(self.settings.get("prefer_html", False))
        root.addWidget(self.cb_prefer_html)

        coll_row = QHBoxLayout()
        self.cb_detect_collections = QCheckBox("Detect game collections (mirror subfolders)")
        self.cb_detect_collections.setChecked(self.settings.get("detect_collections", True))
        self.sp_threshold = QSpinBox()
        self.sp_threshold.setRange(2, 10)
        self.sp_threshold.setValue(int(self.settings.get("collection_threshold", 3)))
        self.sp_threshold.setToolTip("A folder becomes a collection when it has at least this many game subfolders.")
        self.sp_threshold.setEnabled(self.cb_detect_collections.isChecked())
        self.cb_detect_collections.toggled.connect(self.sp_threshold.setEnabled)
        coll_row.addWidget(self.cb_detect_collections)
        coll_row.addStretch(1)
        coll_row.addWidget(QLabel("Min games per collection:"))
        coll_row.addWidget(self.sp_threshold)
        root.addLayout(coll_row)

        actions = QHBoxLayout()
        self.btn_rules = QPushButton("Ignore rules")
        self.btn_undo = QPushButton("Undo last run")
        self.btn_scan = QPushButton("Scan")
        actions.addWidget(self.btn_rules)
        actions.addWidget(self.btn_undo)
        actions.addStretch(1)
        actions.addWidget(self.btn_scan)
        root.addLayout(actions)

        self.pb = QProgressBar()
        self.pb.setValue(0)
        self.lbl_status = QLabel("Ready.")
        self.lbl_status.setStyleSheet("color:#9aa6c2;")
        root.addWidget(self.pb)
        root.addWidget(self.lbl_status)

        b1.clicked.connect(self._pick_root)
        b2.clicked.connect(self._pick_out)
        self.btn_rules.clicked.connect(self._edit_rules)
        self.btn_scan.clicked.connect(self._scan)
        self.btn_undo.clicked.connect(self._undo_last_run)

        return w

    def _pick_root(self):
        p = QFileDialog.getExistingDirectory(self, "Select game root folder")
        if p:
            self.ed_root.setText(p)

    def _pick_out(self):
        p = QFileDialog.getExistingDirectory(self, "Select shortcut output folder")
        if p:
            self.ed_out.setText(p)

    def _edit_rules(self):
        dlg = QDialog(self)
        dlg.setWindowTitle("Ignore rules")
        dlg.resize(940, 660)
        lay = QVBoxLayout(dlg)
        lay.addWidget(QLabel("One pattern per line. Use * as wildcard."))

        t1 = QTextEdit("\n".join(self.rules.get("ignore_exe_name_globs", [])))
        t2 = QTextEdit("\n".join(self.rules.get("ignore_path_globs", [])))

        g1 = QGroupBox("Ignore EXE names")
        l1 = QVBoxLayout(g1)
        l1.addWidget(t1)

        g2 = QGroupBox("Ignore paths")
        l2 = QVBoxLayout(g2)
        l2.addWidget(t2)

        lay.addWidget(g1, 1)
        lay.addWidget(g2, 1)

        btns = QHBoxLayout()
        c = QPushButton("Cancel")
        s = QPushButton("Save")
        btns.addStretch(1)
        btns.addWidget(c)
        btns.addWidget(s)
        lay.addLayout(btns)

        c.clicked.connect(dlg.reject)

        def do_save():
            self.rules["ignore_exe_name_globs"] = [x.strip() for x in t1.toPlainText().splitlines() if x.strip()]
            self.rules["ignore_path_globs"] = [x.strip() for x in t2.toPlainText().splitlines() if x.strip()]
            storage.save_rules(self.rules)
            dlg.accept()

        s.clicked.connect(do_save)

    def _handle_duplicate_game_folders(self) -> bool:
        """
        Looks for Windows-style duplicates in the root like:
          - Game
          - Game (1)
          - Game (2)

        If found, we ask the user, then MOVE the duplicates into a timestamp folder.
        This removes clutter without destroying files.
        """
        root = self.game_root
        try:
            names = [n for n in os.listdir(root) if os.path.isdir(os.path.join(root, n))]
        except Exception:
            return True

        # Map lowercase name -> real name (for case-insensitive match)
        name_map = {n.lower(): n for n in names}

        dup_groups: list[tuple[str, list[str]]] = []
        dup_re = re.compile(r"^(.*)\s\((\d+)\)$")

        for n in names:
            m = dup_re.match(n)
            if not m:
                continue
            base = m.group(1).strip()
            if not base:
                continue
            base_real = name_map.get(base.lower())
            if not base_real:
                continue

            keep = os.path.join(root, base_real)
            dup = os.path.join(root, n)

            # group by keep path
            found = False
            for i, (kp, dups) in enumerate(dup_groups):
                if os.path.normcase(kp) == os.path.normcase(keep):
                    if dup not in dups:
                        dups.append(dup)
                    found = True
                    break
            if not found:
                dup_groups.append((keep, [dup]))

        if not dup_groups:
            return True

        dlg = DuplicateFolderDialog(dup_groups, self)
        if dlg.exec() != QDialog.Accepted:
            return False

        to_move = dlg.selected_paths
        if not to_move:
            return True

        dest = os.path.join(root, f"_Duplicates_Removed_{time.strftime('%Y%m%d-%H%M%S')}")
        os.makedirs(dest, exist_ok=True)

        moved = 0
        failed = 0
        for src in to_move:
            try:
                if os.path.exists(src):
                    shutil.move(src, os.path.join(dest, os.path.basename(src)))
                    moved += 1
            except Exception:
                failed += 1

        QMessageBox.information(
            self,
            "Duplicates handled",
            f"Moved: {moved}\nFailed: {failed}\n\nMoved to:\n{dest}"
        )
        return True


    def _recompute_item_decision(self, it: ScanItem) -> None:
        """Recompute CREATE / REPLACE / SKIP after the user changes launcher."""
        if not it.chosen_exe:
            it.decision = ItemDecision.SKIP
            it.detail = "No launcher selected"
            it.selected = False
            return

        if it.existing_shortcut_path:
            cmpv = compare_versions(it.version_tuple, it.existing_version_tuple)
            if cmpv > 0:
                it.decision = ItemDecision.REPLACE
                it.detail = "User selected (newer version)"
                it.selected = True
            else:
                # keep existing by default; user can tick Force later
                it.decision = ItemDecision.SKIP
                it.detail = "User selected, but shortcut already exists (kept)"
                it.selected = False
        else:
            it.decision = ItemDecision.CREATE
            it.detail = "User selected"
            it.selected = True

    # ---------------- Confirmation: launcher resolution + caching ----------------
    def _item_out_dir(self, rel_subdir: str) -> str:
        return storage.item_output_dir(self.output_dir, rel_subdir)

    def _shortcuts_meta(self) -> dict:
        """Index metadata (keyed by relative shortcut path) for version compares,
        loaded lazily and cached for the current scan."""
        if self._scan_index_meta is None:
            self._scan_index_meta = storage.load_shortcut_index(self.output_dir).get("shortcuts", {})
        return self._scan_index_meta

    def _mark_skipped(self, it: ScanItem) -> None:
        it.is_collection = False
        it.selected = False
        it.decision = ItemDecision.SKIP
        it.detail = "Skipped (not resolved)"

    def _finalize_picked_item(self, it: ScanItem, redetect: bool) -> None:
        """Recompute existing-shortcut + decision for a freshly picked item.

        `redetect` re-runs filesystem existence for the item's (possibly new)
        display name; skip it for a plain game's primary pick, whose existence
        and version meta were already resolved (with index data) during the scan.
        """
        if redetect:
            item_out_dir = self._item_out_dir(it.rel_output_subdir)
            existing, _ext = find_existing_shortcut(item_out_dir, it.base_title)
            it.existing_shortcut_path = existing
            # Recover version meta from the index so an up-to-date existing
            # shortcut is kept (SKIP), not needlessly replaced. Mirrors the scan
            # worker's lookup (collision-free key, with a legacy display fallback).
            meta = {}
            if existing:
                key = storage.index_key(self.output_dir, item_out_dir, os.path.basename(existing))
                meta = self._shortcuts_meta().get(key) or self._shortcuts_meta().get(it.base_title, {})
            it.existing_version_str = meta.get("version_str", "")
            it.existing_version_tuple = tuple(meta.get("version_tuple", [])) if meta.get("version_tuple") else tuple()
            it.existing_target = meta.get("target", "")
        self._recompute_item_decision(it)

    def _expand_launchers(self, it: ScanItem, launchers: list) -> list:
        """Turn one item + chosen launcher(s) into one ScanItem per shortcut."""
        was_collection = it.is_collection
        paths = [p for (_tt, p) in launchers]
        names = multi_shortcut_names(it.base_title, paths)

        out: list[ScanItem] = []
        for idx, ((tt, path), name) in enumerate(zip(launchers, names)):
            ni = it if idx == 0 else copy.deepcopy(it)
            ni.is_collection = False
            ni.collection_members = []
            ni.target_type = tt
            ni.chosen_exe = path
            ni.recommended_exe = path
            ni.base_title = name
            # A collapsed collection's title is new to the output folder; a plain
            # game's primary keeps its scanned name (and its version meta).
            self._finalize_picked_item(ni, redetect=was_collection or idx > 0)
            out.append(ni)
        return out

    def _collection_member_items(self, it: ScanItem, included) -> list:
        members = list(getattr(it, "collection_members", []) or [])
        if included is not None:
            chosen = set(included)
            members = [m for i, m in enumerate(members) if i in chosen]
        # A member with several ambiguous EXEs is still NEEDS_RESOLVE; auto-pick
        # its recommended launcher so it is actionable (the user can re-pick it
        # individually later). Other members pass through unchanged.
        out: list[ScanItem] = []
        for m in members:
            if m.decision == ItemDecision.NEEDS_RESOLVE:
                out.extend(self._auto_resolve(m, self._cached_choice(m)))
            else:
                out.append(m)
        return out

    def _cached_choice(self, it: ScanItem):
        entry = self.confirm_cache.get("choices", {}).get(it.game_folder)
        if not entry:
            return None
        if entry.get("treat_as_collection"):
            return entry
        if any(os.path.exists(l.get("path", "")) for l in entry.get("launchers", [])):
            return entry
        return None

    def _store_choice(self, it: ScanItem, launchers: list, treat_as_collection: bool) -> None:
        self.confirm_cache.setdefault("choices", {})[it.game_folder] = {
            "treat_as_collection": treat_as_collection,
            "launchers": [{"type": tt, "path": p} for (tt, p) in launchers],
        }

    def _apply_cached(self, it: ScanItem, cached: dict):
        """Resolve `it` from a cached choice; None if the cache no longer fits."""
        if cached.get("treat_as_collection") and it.is_collection:
            return self._collection_member_items(it, None)
        launchers = [(l.get("type", "exe"), l.get("path", ""))
                     for l in cached.get("launchers", []) if os.path.exists(l.get("path", ""))]
        if not launchers:
            return None
        return self._expand_launchers(it, launchers)

    def _auto_resolve(self, it: ScanItem, cached) -> list:
        """Resolve `it` with no prompt: cached choice, else the recommended pick."""
        if cached:
            res = self._apply_cached(it, cached)
            if res is not None:
                return res
        if it.is_collection:
            return self._collection_member_items(it, None)
        rec = it.recommended_exe or it.chosen_exe or (it.exe_candidates[0].path if it.exe_candidates else "")
        if not rec:
            self._mark_skipped(it)
            return [it]
        return self._expand_launchers(it, [(getattr(it, "target_type", "exe") or "exe", rec)])

    def _resolve_from_dialog(self, it: ScanItem, dlg) -> list:
        """Apply an accepted picker dialog to `it`, caching if requested."""
        if it.is_collection and dlg.treat_as_collection:
            items = self._collection_member_items(it, dlg.included_members)
            if dlg.remember:
                self._store_choice(it, [], True)
        else:
            launchers = dlg.selected_launchers or [(dlg.selected_type, dlg.selected_path)]
            items = self._expand_launchers(it, launchers)
            if dlg.remember:
                self._store_choice(it, launchers, False)
        return items

    def _open_launcher_picker_for_row(self, row: int) -> None:
        if row < 0 or row >= len(self.items):
            return
        it = self.items[row]

        dlg = LauncherPickerDialog(it, self, cached=self._cached_choice(it))
        if dlg.exec() != QDialog.Accepted:
            return

        new_items = self._resolve_from_dialog(it, dlg)
        if not new_items:
            return
        self.items[row:row + 1] = new_items
        if dlg.remember:
            storage.save_confirmations(self.output_dir, self.confirm_cache)
        self._populate_review()

    def _scan(self):
        self.game_root = self.ed_root.text().strip()
        self.output_dir = self.ed_out.text().strip()

        if not self.game_root or not os.path.isdir(self.game_root):
            QMessageBox.critical(self, "Invalid folder", "Pick a valid game root folder.")
            return
        if not self.output_dir:
            QMessageBox.critical(self, "Invalid folder", "Pick a shortcut output folder.")
            return


        # --- Detect and handle duplicate folders like "Game (1)" in the root ---
        if not self._handle_duplicate_game_folders():
            # user cancelled
            return

        try:
            ensure_windows_shortcut_support()
        except Exception as e:
            QMessageBox.critical(self, "Missing dependency", str(e))
            return

        os.makedirs(self.output_dir, exist_ok=True)

        self.settings["game_root"] = self.game_root
        self.settings["shortcut_output"] = self.output_dir
        self.settings["prefer_html"] = self.cb_prefer_html.isChecked()
        self.settings["detect_collections"] = self.cb_detect_collections.isChecked()
        self.settings["collection_threshold"] = self.sp_threshold.value()
        storage.save_settings(self.settings)


        self.btn_scan.setEnabled(False)
        self.pb.setRange(0, 100)
        self.pb.setValue(0)
        self.lbl_status.setText("Scanning…")
        self.worker = ScanWorker(
            self.game_root,
            self.output_dir,
            self.rules,
            self.settings.get("prefer_html", False),
            detect_collections=self.settings.get("detect_collections", True),
            collection_threshold=int(self.settings.get("collection_threshold", 3)),
            collection_max_depth=int(self.settings.get("collection_max_depth", 6)),
        )
        self.worker.progress.connect(self._on_scan_progress)
        self.worker.finished.connect(self._on_scan_finished)
        self.worker.failed.connect(self._on_scan_failed)
        self.worker.start()

    def _on_scan_progress(self, pct: int, msg: str):
        # pct < 0 means the indeterminate "busy" phase (collection detection):
        # show an animated bar since there is no cheaply-known total yet.
        if pct < 0:
            if self.pb.maximum() != 0:
                self.pb.setRange(0, 0)
        else:
            if self.pb.maximum() == 0:
                self.pb.setRange(0, 100)
            self.pb.setValue(pct)
        self.lbl_status.setText(msg)

    def _on_scan_failed(self, err: str):
        self.btn_scan.setEnabled(True)
        self.pb.setRange(0, 100)
        self.pb.setValue(0)
        self.lbl_status.setText("Scan failed.")
        QMessageBox.critical(self, "Scan failed", err)

    def _on_scan_finished(self, items: list):
        self.btn_scan.setEnabled(True)
        # Leave the indeterminate "busy" state (e.g. the no-folders path emits
        # no determinate value) and settle the bar.
        self.pb.setRange(0, 100)
        self.pb.setValue(100 if items else 0)
        self.items = items

        if not items:
            self.lbl_status.setText("No game folders found.")
            QMessageBox.information(self, "No folders", "No game folders found in the game root.")
            return

        self._resolve_confirmations()

        self._populate_review()
        self.stack.setCurrentWidget(self.page_review)

    def _resolve_confirmations(self) -> None:
        """Walk items needing a launcher choice: reuse cached picks, prompt the
        rest, and honor the batch actions (auto-create / skip / cached-only).
        Collection items expand into their members; multi-pick games expand into
        one item per chosen launcher."""
        self.confirm_cache = storage.load_confirmations(self.output_dir)
        self._scan_index_meta = None  # reload index meta fresh for this scan

        batch_mode = None  # None | "auto_all" | "skip_all" | "cached_all"
        resolved: List[ScanItem] = []
        cache_dirty = False

        for it in self.items:
            if it.decision != ItemDecision.NEEDS_RESOLVE:
                resolved.append(it)
                continue

            cached = self._cached_choice(it)

            if batch_mode == "skip_all":
                self._mark_skipped(it)
                resolved.append(it)
                continue
            if batch_mode == "auto_all":
                resolved.extend(self._auto_resolve(it, cached))
                continue
            if batch_mode == "cached_all" and cached:
                res = self._apply_cached(it, cached)
                if res is not None:
                    resolved.extend(res)
                    continue
            # cached_all with no usable cache falls through to a prompt.

            dlg = LauncherPickerDialog(it, self, cached=cached)
            if dlg.exec() != QDialog.Accepted:
                self._mark_skipped(it)
                resolved.append(it)
                continue

            if dlg.batch_action == "skip_all":
                batch_mode = "skip_all"
                self._mark_skipped(it)
                resolved.append(it)
                continue
            if dlg.batch_action == "auto_all":
                batch_mode = "auto_all"
                resolved.extend(self._auto_resolve(it, cached))
                continue
            if dlg.batch_action == "cached_all":
                batch_mode = "cached_all"
                # Resolve THIS folder from the choice shown in the dialog.

            new_items = self._resolve_from_dialog(it, dlg)
            if not new_items:
                # Empty selection (e.g. a batch click with no launcher/member
                # ticked) must not silently drop the folder — keep it as skipped.
                self._mark_skipped(it)
                new_items = [it]
            resolved.extend(new_items)
            if dlg.remember:
                cache_dirty = True

        self.items = resolved
        if cache_dirty:
            storage.save_confirmations(self.output_dir, self.confirm_cache)

    # ---------------- Review page ----------------
    def _build_review(self) -> QWidget:
        w = QWidget()
        root = QVBoxLayout(w)
        root.setSpacing(10)

        header = QLabel("<h2 style='margin:0;'>Step 2 — Review</h2><div style='color:#9aa6c2;'>Search, filter, and confirm what you want to apply.</div>")
        header.setTextFormat(Qt.RichText)
        root.addWidget(header)

        # Search + filters bar
        bar = QGroupBox("Controls")
        bl = QHBoxLayout(bar)

        self.ed_search = QLineEdit()
        self.ed_search.setPlaceholderText("Search (game name / base title / version)…")

        self.f_create = QCheckBox("Create")
        self.f_replace = QCheckBox("Replace")
        self.f_skip = QCheckBox("Skip")
        self.f_error = QCheckBox("Error")
        self.f_done = QCheckBox("Done")
        self.f_dry = QCheckBox("Dry")

        for cb in [self.f_create, self.f_replace, self.f_skip, self.f_error, self.f_done, self.f_dry]:
            cb.setChecked(True)
            cb.stateChanged.connect(self._apply_filters)

        self.ed_search.textChanged.connect(self._apply_filters)

        self.btn_select_all = QPushButton("Select all")
        self.btn_select_none = QPushButton("Select none")
        self.btn_select_create = QPushButton("Select Create")
        self.btn_select_replace = QPushButton("Select Replace")

        self.btn_select_all.clicked.connect(lambda: self._bulk_select(True))
        self.btn_select_none.clicked.connect(lambda: self._bulk_select(False))
        self.btn_select_create.clicked.connect(lambda: self._bulk_select_by(ItemDecision.CREATE))
        self.btn_select_replace.clicked.connect(lambda: self._bulk_select_by(ItemDecision.REPLACE))

        bl.addWidget(QLabel("Search:"))
        bl.addWidget(self.ed_search, 1)
        bl.addWidget(self.f_create)
        bl.addWidget(self.f_replace)
        bl.addWidget(self.f_skip)
        bl.addWidget(self.f_error)
        bl.addWidget(self.f_done)
        bl.addWidget(self.f_dry)
        bl.addStretch(1)
        bl.addWidget(self.btn_select_all)
        bl.addWidget(self.btn_select_none)
        bl.addWidget(self.btn_select_create)
        bl.addWidget(self.btn_select_replace)

        root.addWidget(bar)

        # Table
        self.tbl = QTableWidget(0, 12)
        self.tbl.setHorizontalHeaderLabels([
            "Use", "Force", "Status", "Type", "Game Folder", "Collection", "Base Title", "Version",
            "Target", "Existing", "Detail", "Score"
        ])

        self.tbl.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        self.tbl.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.tbl.setContextMenuPolicy(Qt.CustomContextMenu)
        self.tbl.customContextMenuRequested.connect(self._open_context_menu)
        self.tbl.cellDoubleClicked.connect(lambda r, c: self._open_launcher_picker_for_row(r))
        root.addWidget(self.tbl, 1)

        nav = QHBoxLayout()
        self.btn_back = QPushButton("Back")
        self.btn_next = QPushButton("Continue")
        nav.addWidget(self.btn_back)
        nav.addStretch(1)
        nav.addWidget(self.btn_next)
        root.addLayout(nav)

        self.btn_back.clicked.connect(lambda: self.stack.setCurrentWidget(self.page_setup))
        self.btn_next.clicked.connect(self._go_confirm)

        return w

    def _effective_decision(self, it: ScanItem) -> ItemDecision:
        if not it.selected:
            return ItemDecision.SKIP
        if not it.chosen_exe:
            return ItemDecision.SKIP
        if it.existing_shortcut_path and it.force_replace:
            return ItemDecision.REPLACE
        return it.decision

    def _status_text(self, it: ScanItem) -> str:
        # If already applied in this session, show DONE
        if (it.detail or "").startswith("Applied"):
            return "DONE"
        if (it.detail or "").startswith("Dry Run OK"):
            return "DRY"

        d = self._effective_decision(it)
        if d == ItemDecision.CREATE:
            return "CREATE"
        if d == ItemDecision.REPLACE:
            return "REPLACE"
        if it.decision == ItemDecision.ERROR:
            return "ERROR"
        return "SKIP"


    def _populate_review(self):
        self.tbl.setRowCount(0)

        for idx, it in enumerate(self.items):
            row = self.tbl.rowCount()
            self.tbl.insertRow(row)

            cb_use = QCheckBox()
            cb_use.setChecked(it.selected)

            cb_force = QCheckBox()
            cb_force.setChecked(it.force_replace)
            cb_force.setEnabled(bool(it.existing_shortcut_path))

            def on_use_changed(_state, row=row):
                item = self.items[row]
                item.selected = cb_use.isChecked()

                # If user selects a SKIP item that already exists, auto-enable Force so it does something
                if item.selected and item.existing_shortcut_path and item.decision == ItemDecision.SKIP:
                    cb_force.setChecked(True)

                self._refresh_row(row)
                self._apply_filters()

            def on_force_changed(_state, row=row):
                self.items[row].force_replace = cb_force.isChecked()
                self._refresh_row(row)
                self._apply_filters()

            cb_use.stateChanged.connect(on_use_changed)
            cb_force.stateChanged.connect(on_force_changed)

            self.tbl.setCellWidget(row, 0, cb_use)
            self.tbl.setCellWidget(row, 1, cb_force)

            def put(col: int, text: str):
                item = QTableWidgetItem(text)
                item.setFlags(item.flags() ^ Qt.ItemIsEditable)
                self.tbl.setItem(row, col, item)
            
            target_name = os.path.basename(it.chosen_exe or it.recommended_exe)
            if getattr(it, "target_type", "exe") == "html":
                target_name = f"{target_name} (HTML)" 

            # Status text + icon
            status_text = self._status_text(it)
            status_item = QTableWidgetItem(status_text)
            status_item.setFlags(status_item.flags() ^ Qt.ItemIsEditable)

            if status_text == "CREATE":
                status_item.setIcon(self.style().standardIcon(QStyle.SP_DialogYesButton))
            elif status_text == "REPLACE":
                status_item.setIcon(self.style().standardIcon(QStyle.SP_BrowserReload))
            elif status_text == "ERROR":
                status_item.setIcon(self.style().standardIcon(QStyle.SP_MessageBoxCritical))
            elif status_text == "DONE":
                status_item.setIcon(self.style().standardIcon(QStyle.SP_DialogApplyButton))
            else:
                status_item.setIcon(self.style().standardIcon(QStyle.SP_DialogNoButton))

            self.tbl.setItem(row, 2, status_item)

            # Type column + icon. A .swf is created as an .exe-style .lnk (target
            # type "exe"), but label it SWF so a Flash launcher is recognizable.
            tt = getattr(it, "target_type", "exe")
            target_for_type = (it.chosen_exe or it.recommended_exe or "")
            if tt == "html":
                type_text = "HTML"
            elif target_for_type.lower().endswith(".swf"):
                type_text = "SWF"
            else:
                type_text = "EXE"
            type_item = QTableWidgetItem(type_text)
            type_item.setFlags(type_item.flags() ^ Qt.ItemIsEditable)
            type_item.setIcon(self.style().standardIcon(QStyle.SP_FileIcon))
            self.tbl.setItem(row, 3, type_item)

            # Target name with HTML label (clear)
            target_name = os.path.basename(it.chosen_exe or it.recommended_exe)
            if tt == "html":
                target_name = f"{target_name} (HTML)"

            put(4, it.folder_name)
            put(5, getattr(it, "rel_output_subdir", "") or "—")
            put(6, it.base_title)
            put(7, it.version_str or "")
            put(8, target_name)
            put(9, f"{it.existing_version_str or ''} {os.path.basename(it.existing_shortcut_path) if it.existing_shortcut_path else ''}".strip())
            put(10, it.detail)

            top_score = it.exe_candidates[0].score if it.exe_candidates else 0
            put(11, str(top_score) if top_score else "")


            # store index in row for context menu
            self.tbl.setRowHeight(row, 44)

        self._apply_filters()

    def _refresh_row(self, row: int):
        it = self.items[row]
        cell = self.tbl.item(row, 2)
        if cell:
            cell.setText(self._status_text(it))

    def _bulk_select(self, value: bool):
        for r in range(self.tbl.rowCount()):
            cb = self.tbl.cellWidget(r, 0)
            if isinstance(cb, QCheckBox):
                cb.setChecked(value)

    def _bulk_select_by(self, decision: ItemDecision):
        for r, it in enumerate(self.items):
            cb = self.tbl.cellWidget(r, 0)
            if isinstance(cb, QCheckBox):
                cb.setChecked(it.decision == decision)

    def _apply_filters(self):
        term = self.ed_search.text().strip().lower()

        allowed = set()
        if self.f_create.isChecked():
            allowed.add("CREATE")
        if self.f_replace.isChecked():
            allowed.add("REPLACE")
        if self.f_skip.isChecked():
            allowed.add("SKIP")
        if self.f_error.isChecked():
            allowed.add("ERROR")
        if self.f_done.isChecked():
            allowed.add("DONE")
        if self.f_dry.isChecked():
            allowed.add("DRY")

        for r, it in enumerate(self.items):
            status = self._status_text(it)

            text_blob = f"{it.folder_name} {getattr(it, 'rel_output_subdir', '')} {getattr(it, 'collection_name', '')} {it.base_title} {it.version_str}".lower()
            match_term = (term in text_blob) if term else True
            match_status = status in allowed

            self.tbl.setRowHidden(r, not (match_term and match_status))

    def _open_context_menu(self, pos: QPoint):
        row = self.tbl.currentRow()
        if row < 0 or row >= len(self.items):
            return
        it = self.items[row]

        menu = QMenu(self)

        a_choose = QAction("Choose launcher…", self)
        a_open_game = QAction("Open game folder", self)
        a_open_exe = QAction("Open chosen EXE folder", self)
        a_open_output = QAction("Open output folder", self)
        a_open_shortcut = QAction("Open shortcut (if exists)", self)
        a_copy_game = QAction("Copy game folder path", self)
        a_copy_exe = QAction("Copy chosen EXE path", self)
        a_copy_short = QAction("Copy shortcut path", self)

        def safe_start(path: str):
            try:
                if path and os.path.exists(path):
                    os.startfile(path)
            except Exception:
                QMessageBox.warning(self, "Failed", "Could not open the path.")

        a_choose.triggered.connect(lambda: self._open_launcher_picker_for_row(row))
        a_open_game.triggered.connect(lambda: safe_start(it.game_folder))
        a_open_exe.triggered.connect(lambda: safe_start(os.path.dirname(it.chosen_exe or it.recommended_exe)))
        a_open_output.triggered.connect(lambda: safe_start(self.output_dir))
        a_open_shortcut.triggered.connect(lambda: safe_start(it.existing_shortcut_path))

        def copy_text(t: str):
            QApplication.clipboard().setText(t or "")

        a_copy_game.triggered.connect(lambda: copy_text(it.game_folder))
        a_copy_exe.triggered.connect(lambda: copy_text(it.chosen_exe or it.recommended_exe))
        a_copy_short.triggered.connect(lambda: copy_text(it.existing_shortcut_path))

        menu.addAction(a_choose)
        menu.addAction(a_open_game)
        menu.addAction(a_open_exe)
        menu.addSeparator()
        menu.addAction(a_open_output)
        menu.addAction(a_open_shortcut)
        menu.addSeparator()
        menu.addAction(a_copy_game)
        menu.addAction(a_copy_exe)
        menu.addAction(a_copy_short)

        menu.exec(self.tbl.mapToGlobal(pos))

    def _go_confirm(self):
        self._populate_confirm()
        self.stack.setCurrentWidget(self.page_confirm)

    # ---------------- Confirm page ----------------
    def _build_confirm(self) -> QWidget:
        w = QWidget()
        root = QVBoxLayout(w)
        root.setSpacing(10)

        header = QLabel("<h2 style='margin:0;'>Step 3 — Confirm</h2><div style='color:#9aa6c2;'>Nothing is written until you click Apply.</div>")
        header.setTextFormat(Qt.RichText)
        root.addWidget(header)

        box = QGroupBox("Summary")
        bl = QVBoxLayout(box)
        self.lbl_summary = QLabel("")
        self.lbl_summary.setTextFormat(Qt.RichText)
        self.lbl_summary.setWordWrap(True)
        bl.addWidget(self.lbl_summary)

        self.cb_dryrun = QCheckBox("Dry Run (no files will be created/changed)")
        self.cb_dryrun.setChecked(False)
        bl.addWidget(self.cb_dryrun)

        root.addWidget(box)

        self.pb_apply = QProgressBar()
        self.pb_apply.setValue(0)
        root.addWidget(self.pb_apply)

        nav = QHBoxLayout()
        self.btn_back2 = QPushButton("Back")
        self.btn_open_out = QPushButton("Open output folder")
        self.btn_apply = QPushButton("Apply")
        nav.addWidget(self.btn_back2)
        nav.addStretch(1)
        nav.addWidget(self.btn_open_out)
        nav.addWidget(self.btn_apply)
        root.addLayout(nav)

        self.btn_back2.clicked.connect(lambda: self.stack.setCurrentWidget(self.page_review))
        self.btn_open_out.clicked.connect(lambda: os.startfile(self.output_dir) if self.output_dir and os.path.isdir(self.output_dir) else None)
        self.btn_apply.clicked.connect(self._apply)

        return w

    def _populate_confirm(self):
        creates = [it for it in self.items if self._effective_decision(it) == ItemDecision.CREATE]
        replaces = [it for it in self.items if self._effective_decision(it) == ItemDecision.REPLACE]
        skipped = [it for it in self.items if self._effective_decision(it) in (ItemDecision.SKIP, ItemDecision.ERROR)]

        self.lbl_summary.setText(
            f"<b>Game root:</b> {self.game_root}<br/>"
            f"<b>Output:</b> {self.output_dir}<br/><br/>"
            f"<b>Will create:</b> {len(creates)}<br/>"
            f"<b>Will replace:</b> {len(replaces)}<br/>"
            f"<b>Skipped / errors:</b> {len(skipped)}<br/><br/>"
            f"<span style='color:#9aa6c2;'>Replace operations will backup old shortcuts.</span>"
        )
        self.pb_apply.setValue(0)

    def _apply(self):
        dry = self.cb_dryrun.isChecked()

        # Pre-flight: a read-only / encrypted output folder is the usual reason a
        # whole run fails to create any shortcuts. Warn before doing the work.
        if not dry and self.output_dir and not storage.is_dir_writable(self.output_dir):
            resp = QMessageBox.question(
                self, "Output folder may be read-only",
                "The output folder does not appear to be writable:\n"
                f"{self.output_dir}\n\n"
                "Shortcuts (and the index/undo log) probably can't be created "
                "there — most items would fail. Continue anyway?",
                QMessageBox.Yes | QMessageBox.No,
            )
            if resp != QMessageBox.Yes:
                return

        # Optional: disable buttons while applying
        self.btn_apply.setEnabled(False)
        self.btn_open_out.setEnabled(False)
        self.pb_apply.setValue(0)

        # Start worker
        self.apply_worker = ApplyWorker(self.items, self.output_dir, dry)
        self.apply_worker.progress.connect(self._on_apply_progress)
        self.apply_worker.finished.connect(self._on_apply_finished)
        self.apply_worker.failed.connect(self._on_apply_failed)
        self.apply_worker.start()

    def _on_apply_progress(self, pct: int, msg: str):
        self.pb_apply.setValue(pct)
        # Show lightweight progress feedback without bloating the summary
        self.lbl_status.setText(f"Applying… {msg}")

    def _on_apply_failed(self, err: str):
        self.btn_apply.setEnabled(True)
        self.btn_open_out.setEnabled(True)
        self.lbl_status.setText("Apply failed.")
        QMessageBox.critical(self, "Apply failed", err)

    def _on_apply_finished(self, errors: int, total: int):
        self.btn_apply.setEnabled(True)
        self.btn_open_out.setEnabled(True)

        # Refresh the review table so users see updated DONE/DRY statuses
        self._populate_review()
        self._populate_confirm()

        self.lbl_status.setText("Apply complete.")
        warnings = getattr(self.apply_worker, "warnings", []) or []
        warn_block = ("\n\nWarnings:\n- " + "\n- ".join(warnings)) if warnings else ""

        # Show *why* items failed (categorized) and where the full log landed,
        # so a run with many errors is actionable rather than an opaque count.
        summary = getattr(self.apply_worker, "error_summary", {}) or {}
        log_path = getattr(self.apply_worker, "error_log_path", "") or ""
        err_block = ""
        if summary:
            err_block += "\n\nError summary:\n- " + "\n- ".join(
                f"{n} × {cat}"
                for cat, n in sorted(summary.items(), key=lambda kv: -kv[1])
            )
        if log_path:
            err_block += f"\n\nFull error log:\n{log_path}"

        QMessageBox.information(
            self,
            "Completed",
            f"{'Dry Run finished' if self.cb_dryrun.isChecked() else 'Applied changes'}\n"
            f"Total: {total}\nErrors: {errors}\n\nOutput:\n{self.output_dir}"
            f"{warn_block}{err_block}"
        )

        # Stay on confirm page
        self.btn_apply.setText("Applied")


    def _undo_last_run(self):
        out_dir = self.ed_out.text().strip()
        if not out_dir or not os.path.isdir(out_dir):
            QMessageBox.information(self, "Undo", "Pick a valid output folder first.")
            return

        log = storage.load_last_run(out_dir)
        actions = log.get("actions", [])

        if not actions:
            QMessageBox.information(self, "Undo", "No previous run log found.")
            return

        # If dry run, backups likely empty; still allow "undo" message.
        resp = QMessageBox.question(
            self, "Undo last run",
            "This will restore backed up shortcuts (when available).\n\nContinue?",
            QMessageBox.Yes | QMessageBox.No
        )
        if resp != QMessageBox.Yes:
            return

        restored = 0
        skipped = 0

        for a in reversed(actions):
            lnk = a.get("lnk", "")
            backup_path = a.get("backup_path", "")
            if backup_path and os.path.exists(backup_path):
                try:
                    shutil.copy2(backup_path, lnk)
                    restored += 1
                except Exception:
                    skipped += 1
            else:
                # for creates (no backup), we won't delete automatically (safer)
                skipped += 1

        QMessageBox.information(
            self, "Undo complete",
            f"Restored: {restored}\nSkipped: {skipped}\n\nNote: created shortcuts are not auto-deleted for safety."
        )
