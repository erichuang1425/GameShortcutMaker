"""Modal dialogs: launcher pickers and the duplicate-folder cleaner."""
from __future__ import annotations

import os

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QListWidget, QListWidgetItem, QMessageBox, QComboBox,
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


class LauncherPickerDialog(QDialog):
    """Lets the user choose EXE or HTML launcher for a game."""
    def __init__(self, item: ScanItem, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Choose launcher")
        self.resize(980, 600)

        self.item = item
        self.selected_path = item.chosen_exe or item.recommended_exe
        self.selected_type = getattr(item, "target_type", "exe") or "exe"

        root = QVBoxLayout(self)

        title = QLabel(
            f"<h3 style='margin:0;'>Choose launcher</h3>"
            f"<div style='color:#9aa6c2;'>Game: <b>{item.folder_name}</b></div>"
            f"<div style='color:#9aa6c2;'>The first item is the recommended pick.</div>"
        )
        title.setTextFormat(Qt.RichText)
        root.addWidget(title)

        top_row = QHBoxLayout()
        top_row.addWidget(QLabel("Type:"))
        self.type_combo = QComboBox()
        self.type_combo.addItems(["EXE", "HTML"])
        self.type_combo.setCurrentText("HTML" if self.selected_type == "html" else "EXE")
        top_row.addWidget(self.type_combo)
        top_row.addStretch(1)
        root.addLayout(top_row)

        self.listw = QListWidget()
        root.addWidget(self.listw, 1)

        btns = QHBoxLayout()
        self.btn_open_folder = QPushButton("Open selected folder")
        btn_cancel = QPushButton("Cancel")
        btn_ok = QPushButton("Use selected")
        btns.addWidget(self.btn_open_folder)
        btns.addStretch(1)
        btns.addWidget(btn_cancel)
        btns.addWidget(btn_ok)
        root.addLayout(btns)

        self.type_combo.currentTextChanged.connect(self._refresh_list)
        self.btn_open_folder.clicked.connect(self._open_selected_folder)
        btn_cancel.clicked.connect(self.reject)
        btn_ok.clicked.connect(self._accept)

        self._refresh_list()

    def _ensure_html_candidates(self) -> list[tuple[int, str, str]]:
        # Build scored HTML list on demand to avoid extra scanning cost.
        if not getattr(self.item, "html_candidates", None):
            self.item.html_candidates = scan_html_candidates(self.item.game_folder)

        scored = []
        for hp in self.item.html_candidates:
            # depth relative to the game folder (0 = root)
            rel = os.path.relpath(os.path.dirname(hp), self.item.game_folder)
            d = 0 if rel == "." else rel.count(os.sep) + 1
            sc, reason = score_html(hp, self.item.base_title, d)
            scored.append((sc, hp, reason))
        scored.sort(key=lambda x: x[0], reverse=True)
        return scored

    def _refresh_list(self):
        self.listw.clear()

        mode = self.type_combo.currentText()
        if mode == "EXE":
            cands = self.item.exe_candidates or []
            if not cands:
                self.listw.addItem(QListWidgetItem("No EXE candidates found."))
                return
            for idx, c in enumerate(cands):
                badge = "⭐ Recommended" if idx == 0 else ""
                text = (
                    f"{os.path.basename(c.path)}\n"
                    f"   Score: {c.score}   Size: {human_size(c.size_bytes)}   Date: {human_time(c.mtime)}   {badge}\n"
                    f"   Path: {c.path}"
                )
                li = QListWidgetItem(text)
                li.setData(Qt.UserRole, ("exe", c.path))
                self.listw.addItem(li)
            self.listw.setCurrentRow(0)
        else:
            scored = self._ensure_html_candidates()
            if not scored:
                self.listw.addItem(QListWidgetItem("No HTML files found."))
                return

            # Only show "likely launchers" near the top by default
            # (User can still pick anything in the list)
            for idx, (sc, hp, reason) in enumerate(scored):
                badge = "⭐ Recommended" if idx == 0 else ""
                text = (
                    f"{os.path.basename(hp)} (HTML)\n"
                    f"   Score: {sc}   {badge}   ({reason})\n"
                    f"   Path: {hp}"
                )
                li = QListWidgetItem(text)
                li.setData(Qt.UserRole, ("html", hp))
                self.listw.addItem(li)
            self.listw.setCurrentRow(0)

    def _open_selected_folder(self):
        cur = self.listw.currentItem()
        if not cur:
            return
        data = cur.data(Qt.UserRole)
        if not data:
            return
        _tt, path = data
        folder = os.path.dirname(path)
        try:
            if folder and os.path.isdir(folder):
                os.startfile(folder)
        except Exception:
            QMessageBox.warning(self, "Failed", "Could not open the folder.")

    def _accept(self):
        cur = self.listw.currentItem()
        if not cur:
            QMessageBox.warning(self, "Select one", "Please select a launcher.")
            return
        data = cur.data(Qt.UserRole)
        if not data:
            QMessageBox.warning(self, "Select one", "Please select a launcher.")
            return
        tt, path = data
        self.selected_type = tt
        self.selected_path = path
        self.accept()
