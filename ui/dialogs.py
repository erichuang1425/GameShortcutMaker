"""Modal dialogs: launcher pickers and the duplicate-folder cleaner."""
from __future__ import annotations

import os

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QListWidget, QListWidgetItem, QMessageBox, QComboBox, QCheckBox,
)

from models import ScanItem
from scanner import scan_html_candidates
from html_scoring import score_html
from ui.theme import human_size, human_time


class ConflictDialog(QDialog):
    def __init__(self, item: ScanItem, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Pick the launcher")
        self.resize(920, 560)
        self.item = item

        self.selected_exe = ""

        root = QVBoxLayout(self)

        title = QLabel(
            f"<h3 style='margin:0;'>Pick the launcher EXE</h3>"
            f"<div style='color:#cfd6e6;'>Game: <b>{item.folder_name}</b></div>"
            f"<div style='color:#9aa6c2;'>Tip: The top item is <b>Recommended</b>.</div>"
        )
        title.setTextFormat(Qt.RichText)
        root.addWidget(title)

        self.listw = QListWidget()
        for idx, c in enumerate(item.exe_candidates):
            badge = "⭐ Recommended" if idx == 0 else ""
            text = f"{c.path}\n   Score: {c.score}   Size: {human_size(c.size_bytes)}   Date: {human_time(c.mtime)}   {badge}"
            li = QListWidgetItem(text)
            li.setData(Qt.UserRole, c.path)
            self.listw.addItem(li)

        root.addWidget(self.listw, 1)

        # preselect recommended
        if self.listw.count() > 0:
            self.listw.setCurrentRow(0)

        btns = QHBoxLayout()
        btn_cancel = QPushButton("Cancel (skip this game)")
        btn_ok = QPushButton("Use selected")
        btns.addStretch(1)
        btns.addWidget(btn_cancel)
        btns.addWidget(btn_ok)
        root.addLayout(btns)

        btn_cancel.clicked.connect(self.reject)
        btn_ok.clicked.connect(self._accept)

    def _accept(self):
        cur = self.listw.currentItem()
        if not cur:
            QMessageBox.warning(self, "Select one", "Please select an executable.")
            return
        self.selected_exe = cur.data(Qt.UserRole)
        self.accept()



class DuplicateFolderDialog(QDialog):
    """Shows duplicated root folders like 'Game (1)' and lets user choose what to remove."""
    def __init__(self, duplicates: list[tuple[str, list[str]]], parent=None):
        super().__init__(parent)
        self.setWindowTitle("Duplicate game folders found")
        self.resize(920, 520)

        self.selected_paths: list[str] = []

        root = QVBoxLayout(self)

        root.addWidget(QLabel(
            "<h3 style='margin:0;'>Duplicate folders in game root</h3>"
            "<div style='color:#9aa6c2;'>These look like Windows duplicate names (e.g. <b>Game (1)</b>).</div>"
            "<div style='color:#9aa6c2;'>They will be <b>moved out of the root</b> (safer than deleting).</div>"
        ))

        self.listw = QListWidget()
        for keep_path, dup_paths in duplicates:
            keep_name = os.path.basename(keep_path)
            header = QListWidgetItem(f"Keep: {keep_name}")
            header.setFlags(Qt.ItemIsEnabled)
            self.listw.addItem(header)

            for p in dup_paths:
                name = os.path.basename(p)
                li = QListWidgetItem(f"Remove from root: {name}")
                li.setFlags(li.flags() | Qt.ItemIsUserCheckable)
                li.setCheckState(Qt.Checked)
                li.setData(Qt.UserRole, p)
                self.listw.addItem(li)

            self.listw.addItem(QListWidgetItem(""))

        root.addWidget(self.listw, 1)

        note = QLabel(
            "<div style='color:#9aa6c2;'>Tip: Uncheck anything you want to keep.</div>"
        )
        note.setTextFormat(Qt.RichText)
        root.addWidget(note)

        btns = QHBoxLayout()
        btn_cancel = QPushButton("Cancel")
        btn_ok = QPushButton("Move selected out of root")
        btns.addStretch(1)
        btns.addWidget(btn_cancel)
        btns.addWidget(btn_ok)
        root.addLayout(btns)

        btn_cancel.clicked.connect(self.reject)
        btn_ok.clicked.connect(self._accept)

    def _accept(self):
        chosen = []
        for i in range(self.listw.count()):
            it = self.listw.item(i)
            p = it.data(Qt.UserRole)
            if p and it.checkState() == Qt.Checked:
                chosen.append(p)
        self.selected_paths = chosen
        self.accept()


class FlattenPickerDialog(QDialog):
    """Choose *which* redundantly-nested folders to flatten.

    Each squashable folder is one checkable row (ticked by default) describing
    exactly what will happen: how many wrapper levels collapse and which items
    move up. Unlike the old all-or-nothing prompt, the user can flatten any
    subset — tick/untick individually, or use Select all / none. Double-click a
    row to open that folder and inspect it first. The "Flatten N" button tracks
    the live selection count and disables when nothing is ticked.

    Result attribute read by the caller:
      selected_plans -> list[SquashPlan] (in original order) the user confirmed.
    """

    def __init__(self, plans: list, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Flatten redundant folders")
        self.resize(860, 620)

        self._plans = list(plans)
        self.selected_plans: list = []

        root = QVBoxLayout(self)

        intro = QLabel(
            "<h3 style='margin:0;'>Flatten redundant folders</h3>"
            f"<div style='color:#9aa6c2;'><b>{len(self._plans)}</b> folder(s) have "
            "redundant single-child nesting.</div>"
            "<div style='color:#9aa6c2;'>Tick the ones to flatten — their contents "
            "move up into the top game folder (kept) and the empty wrappers are "
            "removed. Nothing is overwritten, and this is undoable.</div>"
            "<div style='color:#9aa6c2;'>Tip: double-click a row to open that folder.</div>"
        )
        intro.setTextFormat(Qt.RichText)
        intro.setWordWrap(True)
        root.addWidget(intro)

        # Select all / none, plus a live count of what's ticked.
        sel_row = QHBoxLayout()
        self.btn_all = QPushButton("Select all")
        self.btn_none = QPushButton("Select none")
        sel_row.addWidget(self.btn_all)
        sel_row.addWidget(self.btn_none)
        sel_row.addStretch(1)
        self.lbl_count = QLabel("")
        sel_row.addWidget(self.lbl_count)
        root.addLayout(sel_row)

        self.listw = QListWidget()
        for p in self._plans:
            chain = " / ".join(p.chain_names) or "(direct)"
            preview = ", ".join(p.entries[:6])
            if len(p.entries) > 6:
                preview += f", …(+{len(p.entries) - 6} more)"
            text = (
                f"{os.path.basename(p.game_folder)}\n"
                f"   Collapse {p.levels} level(s): {chain}\n"
                f"   Move {len(p.entries)} item(s) up: {preview}"
            )
            li = QListWidgetItem(text)
            li.setFlags(li.flags() | Qt.ItemIsUserCheckable)
            li.setCheckState(Qt.Checked)
            li.setData(Qt.UserRole, p)
            self.listw.addItem(li)
        root.addWidget(self.listw, 1)

        btns = QHBoxLayout()
        btn_cancel = QPushButton("Cancel")
        self.btn_ok = QPushButton("Flatten")
        btns.addStretch(1)
        btns.addWidget(btn_cancel)
        btns.addWidget(self.btn_ok)
        root.addLayout(btns)

        # Connect after populating so the initial setCheckState calls don't churn.
        self.listw.itemChanged.connect(lambda _it: self._update_count())
        self.listw.itemDoubleClicked.connect(self._open_folder)
        self.btn_all.clicked.connect(lambda: self._set_all(Qt.Checked))
        self.btn_none.clicked.connect(lambda: self._set_all(Qt.Unchecked))
        btn_cancel.clicked.connect(self.reject)
        self.btn_ok.clicked.connect(self._accept)

        self._update_count()

    def _set_all(self, state) -> None:
        self.listw.blockSignals(True)
        for i in range(self.listw.count()):
            self.listw.item(i).setCheckState(state)
        self.listw.blockSignals(False)
        self._update_count()

    def _checked_plans(self) -> list:
        out = []
        for i in range(self.listw.count()):
            li = self.listw.item(i)
            if li.checkState() == Qt.Checked:
                out.append(li.data(Qt.UserRole))
        return out

    def _update_count(self) -> None:
        n = len(self._checked_plans())
        total = self.listw.count()
        self.lbl_count.setText(f"{n} of {total} selected")
        self.btn_ok.setText(f"Flatten {n} folder(s)" if n else "Flatten")
        self.btn_ok.setEnabled(n > 0)

    def _open_folder(self, item: QListWidgetItem) -> None:
        plan = item.data(Qt.UserRole)
        folder = getattr(plan, "game_folder", "")
        try:
            if folder and os.path.isdir(folder):
                os.startfile(folder)
        except Exception:
            QMessageBox.warning(self, "Failed", "Could not open the folder.")

    def _accept(self) -> None:
        chosen = self._checked_plans()
        if not chosen:
            QMessageBox.warning(
                self, "Nothing selected",
                "Tick at least one folder to flatten (or Cancel).",
            )
            return
        self.selected_plans = chosen
        self.accept()


class LauncherPickerDialog(QDialog):
    """Confirm a folder's launcher(s).

    Tick one or more launchers -> one shortcut per ticked launcher. For a folder
    auto-detected as a *collection*, a "Treat as collection" toggle (on by
    default) lists the sub-games (one shortcut each); untick it to collapse the
    folder into a single game and pick launcher(s) from the flat candidate list.

    Result attributes read by the caller:
      selected_launchers   -> list[(type, path)] (when not confirmed as collection)
      selected_type/_path  -> first of selected_launchers (back-compat)
      treat_as_collection  -> bool
      included_members     -> list[int] member indices, or None for "all"
      remember             -> cache this choice
      batch_action         -> "" | "auto_all" | "skip_all" | "cached_all"
    """

    def __init__(self, item: ScanItem, parent=None, cached: dict | None = None):
        super().__init__(parent)
        self.setWindowTitle("Confirm launcher")
        self.resize(1000, 640)

        self.item = item
        self.cached = cached or {}

        # Results (defaults).
        self.selected_launchers: list[tuple[str, str]] = []
        self.selected_path = item.chosen_exe or item.recommended_exe
        self.selected_type = getattr(item, "target_type", "exe") or "exe"
        self.treat_as_collection = bool(getattr(item, "is_collection", False))
        self.included_members = None
        self.remember = True
        self.batch_action = ""

        self._cached_paths = {l.get("path", "") for l in self.cached.get("launchers", [])}

        root = QVBoxLayout(self)

        n_members = len(getattr(item, "collection_members", []) or [])
        subtitle = (
            f"Detected a collection of <b>{n_members}</b> sub-games."
            if item.is_collection else
            "Tick one or more launchers — each becomes its own shortcut."
        )
        title = QLabel(
            f"<h3 style='margin:0;'>Confirm launcher</h3>"
            f"<div style='color:#9aa6c2;'>Folder: <b>{item.folder_name}</b></div>"
            f"<div style='color:#9aa6c2;'>{subtitle}</div>"
        )
        title.setTextFormat(Qt.RichText)
        root.addWidget(title)

        top_row = QHBoxLayout()
        self.cb_collection = None
        if item.is_collection:
            self.cb_collection = QCheckBox(
                f"Treat as a collection (make a shortcut for each of the {n_members} sub-games)"
            )
            self.cb_collection.setChecked(True)
            self.cb_collection.toggled.connect(self._refresh_list)
            top_row.addWidget(self.cb_collection)
        top_row.addStretch(1)
        top_row.addWidget(QLabel("Type:"))
        self.type_combo = QComboBox()
        self.type_combo.addItems(["EXE", "HTML"])
        self.type_combo.setCurrentText("HTML" if self.selected_type == "html" else "EXE")
        top_row.addWidget(self.type_combo)
        root.addLayout(top_row)

        self.listw = QListWidget()
        root.addWidget(self.listw, 1)

        self.cb_remember = QCheckBox("Remember my choice for this folder (cached in the output folder)")
        self.cb_remember.setChecked(True)
        root.addWidget(self.cb_remember)

        # Batch actions for the rest of the run.
        batch_row = QHBoxLayout()
        self.btn_auto_all = QPushButton("Stop asking — auto-create rest (best/cached)")
        self.btn_skip_all = QPushButton("Stop asking — skip rest")
        self.btn_cached_all = QPushButton("Auto-apply cached, ask the rest")
        for b in (self.btn_auto_all, self.btn_skip_all, self.btn_cached_all):
            batch_row.addWidget(b)
        batch_row.addStretch(1)
        root.addLayout(batch_row)

        btns = QHBoxLayout()
        self.btn_open_folder = QPushButton("Open selected folder")
        btn_cancel = QPushButton("Cancel (skip this folder)")
        btn_ok = QPushButton("Use selected")
        btns.addWidget(self.btn_open_folder)
        btns.addStretch(1)
        btns.addWidget(btn_cancel)
        btns.addWidget(btn_ok)
        root.addLayout(btns)

        self.type_combo.currentTextChanged.connect(self._refresh_list)
        self.btn_open_folder.clicked.connect(self._open_selected_folder)
        self.btn_auto_all.clicked.connect(lambda: self._batch("auto_all"))
        self.btn_skip_all.clicked.connect(lambda: self._batch("skip_all"))
        self.btn_cached_all.clicked.connect(lambda: self._batch("cached_all"))
        btn_cancel.clicked.connect(self.reject)
        btn_ok.clicked.connect(self._accept)

        self._refresh_list()

    # -- mode helpers ------------------------------------------------------
    def _collection_mode(self) -> bool:
        return bool(self.cb_collection and self.cb_collection.isChecked())

    def _ensure_html_candidates(self) -> list[tuple[int, str, str]]:
        # Build scored HTML list on demand to avoid extra scanning cost.
        if not getattr(self.item, "html_candidates", None):
            self.item.html_candidates = scan_html_candidates(self.item.game_folder)

        scored = []
        for hp in self.item.html_candidates:
            rel = os.path.relpath(os.path.dirname(hp), self.item.game_folder)
            d = 0 if rel == "." else rel.count(os.sep) + 1
            sc, reason = score_html(hp, self.item.base_title, d)
            scored.append((sc, hp, reason))
        scored.sort(key=lambda x: x[0], reverse=True)
        return scored

    def _add_checkable(self, text: str, data, checked: bool):
        li = QListWidgetItem(text)
        li.setFlags(li.flags() | Qt.ItemIsUserCheckable)
        li.setCheckState(Qt.Checked if checked else Qt.Unchecked)
        li.setData(Qt.UserRole, data)
        self.listw.addItem(li)

    def _refresh_list(self):
        self.listw.clear()
        collection = self._collection_mode()
        self.type_combo.setEnabled(not collection)

        if collection:
            members = getattr(self.item, "collection_members", []) or []
            for idx, m in enumerate(members):
                launcher = m.chosen_exe or m.recommended_exe
                where = getattr(m, "rel_output_subdir", "") or "(top)"
                text = (
                    f"{m.base_title}\n"
                    f"   Launcher: {os.path.basename(launcher) if launcher else 'NONE — no launcher found'}\n"
                    f"   Output subfolder: {where}"
                )
                # Members without a launcher are excluded by default.
                self._add_checkable(text, ("member", idx), checked=bool(launcher))
            return

        if self.type_combo.currentText() == "EXE":
            cands = self.item.exe_candidates or []
            if not cands:
                self.listw.addItem(QListWidgetItem("No EXE candidates found."))
                return
            preselect = self._cached_paths or {self.item.chosen_exe or self.item.recommended_exe}
            for idx, c in enumerate(cands):
                badge = "⭐ Recommended" if idx == 0 else ""
                text = (
                    f"{os.path.basename(c.path)}\n"
                    f"   Score: {c.score}   Size: {human_size(c.size_bytes)}   Date: {human_time(c.mtime)}   {badge}\n"
                    f"   Path: {c.path}"
                )
                self._add_checkable(text, ("exe", c.path), checked=(c.path in preselect))
            self.listw.setCurrentRow(0)
        else:
            scored = self._ensure_html_candidates()
            if not scored:
                self.listw.addItem(QListWidgetItem("No HTML files found."))
                return
            preselect = self._cached_paths
            for idx, (sc, hp, reason) in enumerate(scored):
                badge = "⭐ Recommended" if idx == 0 else ""
                text = (
                    f"{os.path.basename(hp)} (HTML)\n"
                    f"   Score: {sc}   {badge}   ({reason})\n"
                    f"   Path: {hp}"
                )
                self._add_checkable(text, ("html", hp), checked=(hp in preselect))
            self.listw.setCurrentRow(0)

    # -- selection gathering ----------------------------------------------
    def _gather_launchers(self) -> list[tuple[str, str]]:
        launchers: list[tuple[str, str]] = []
        for i in range(self.listw.count()):
            li = self.listw.item(i)
            data = li.data(Qt.UserRole)
            if not data or data[0] == "member":
                continue
            if li.checkState() == Qt.Checked:
                launchers.append((data[0], data[1]))
        if not launchers:
            cur = self.listw.currentItem()
            if cur and cur.data(Qt.UserRole) and cur.data(Qt.UserRole)[0] != "member":
                d = cur.data(Qt.UserRole)
                launchers = [(d[0], d[1])]
        return launchers

    def _gather_members(self) -> list[int]:
        included = []
        for i in range(self.listw.count()):
            li = self.listw.item(i)
            data = li.data(Qt.UserRole)
            if data and data[0] == "member" and li.checkState() == Qt.Checked:
                included.append(data[1])
        return included

    def _capture(self) -> bool:
        """Read the current UI selection into result attrs. False if nothing chosen."""
        self.remember = self.cb_remember.isChecked()
        if self._collection_mode():
            self.treat_as_collection = True
            self.included_members = self._gather_members()
            return bool(self.included_members)
        self.treat_as_collection = False
        launchers = self._gather_launchers()
        if not launchers:
            return False
        self.selected_launchers = launchers
        self.selected_type, self.selected_path = launchers[0]
        return True

    def _open_selected_folder(self):
        cur = self.listw.currentItem()
        if not cur:
            return
        data = cur.data(Qt.UserRole)
        if not data or data[0] == "member":
            return
        folder = os.path.dirname(data[1])
        try:
            if folder and os.path.isdir(folder):
                os.startfile(folder)
        except Exception:
            QMessageBox.warning(self, "Failed", "Could not open the folder.")

    def _accept(self):
        if not self._capture():
            QMessageBox.warning(
                self, "Nothing selected",
                "Tick at least one launcher (or, for a collection, at least one sub-game).",
            )
            return
        self.accept()

    def _batch(self, action: str):
        # Capture whatever is currently selected (used as this folder's choice
        # under cached_all); auto_all/skip_all resolve this folder by rule.
        self._capture()
        self.batch_action = action
        self.accept()
