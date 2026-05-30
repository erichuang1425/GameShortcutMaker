from __future__ import annotations

import os
import re
import time
import shutil
from typing import List
import glob

from PySide6.QtCore import Qt, QThread, Signal, QPoint
from PySide6.QtGui import QIcon, QAction
from PySide6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QFileDialog, QLineEdit, QMessageBox, QStackedWidget, QTableWidget, QTableWidgetItem,
    QHeaderView, QCheckBox, QProgressBar, QDialog, QListWidget, QListWidgetItem,
    QGroupBox, QFormLayout, QTextEdit, QComboBox, QMenu, QToolButton, QStyle
)

from html_scoring import score_html
from scanner import find_any_exe_exists, scan_html_candidates, _rel_depth
from models import ScanItem, ItemDecision, ExeCandidate
from scanner import list_game_folders, scan_game_folder_topmost_exes, build_candidates
from versioning import extract_version, strip_version_from_title, compare_versions
from shortcut_manager import (
    shortcut_path, create_or_replace_shortcut, read_shortcut_target,
    ensure_windows_shortcut_support, backup_shortcut, url_shortcut_path, create_url_shortcut, safe_filename
)
from rules import default_rules
import storage

THEMES = {
        "Paper Light": {
        "bg": "#f6f7fb",          # app background
        "surface": "#ffffff",      # inputs / tables background
        "card": "#ffffff",         # group boxes / panels
        "border": "#d6dbe6",       # borders / dividers
        "text": "#111827",         # main text
        "muted": "#4b5563",        # secondary text
        "accent": "#2563eb",       # primary button
        "accent_hover": "#1d4ed8", # button hover
        "danger": "#dc2626",
        "warning": "#d97706",
        "success": "#059669",
        "selection": "#dbeafe",    # selection highlight
    },
    "Midnight Blue": {
        "bg": "#0f1115",
        "surface": "#0c0f16",
        "card": "#141823",
        "border": "#2a2f3a",
        "text": "#e7eaf0",
        "muted": "#9aa6c2",
        "accent": "#2b5cff",
        "accent_hover": "#3a6cff",
        "danger": "#ff4d4f",
        "warning": "#ffcc00",
        "success": "#29d37e",
        "selection": "#1b335f",
    },
    "Forest": {
        "bg": "#0f1411",
        "surface": "#0c110e",
        "card": "#131b16",
        "border": "#2a3a30",
        "text": "#e7f0ea",
        "muted": "#9ab6a7",
        "accent": "#2aa86b",
        "accent_hover": "#35c17e",
        "danger": "#ff5a5f",
        "warning": "#ffd166",
        "success": "#29d37e",
        "selection": "#163826",
    },
    "Solarized Dark": {
        "bg": "#002b36",
        "surface": "#073642",
        "card": "#0b3b49",
        "border": "#1a4b57",
        "text": "#eee8d5",
        "muted": "#93a1a1",
        "accent": "#268bd2",
        "accent_hover": "#2aa1f0",
        "danger": "#dc322f",
        "warning": "#b58900",
        "success": "#859900",
        "selection": "#0b5160",
    },
}

def build_stylesheet(t: dict) -> str:
    return (f"""
    QMainWindow {{
      background: {t['bg']};
    }}
    QWidget {{
      color: {t['text']};
      font-size: 13px;
    }}

    QGroupBox {{
      border: 1px solid {t['border']};
      border-radius: 12px;
      margin-top: 10px;
      padding: 12px;
      background: {t['card']};
    }}
    QGroupBox::title {{
      subcontrol-origin: margin;
      left: 12px;
      padding: 0 6px;
      color: {t['text']};
    }}

    QLineEdit, QTextEdit, QPlainTextEdit {{
      background: {t['surface']};
      border: 1px solid {t['border']};
      border-radius: 10px;
      padding: 8px;
      selection-background-color: {t['selection']};
      selection-color: {t['text']};
    }}

    /* Buttons */
    QPushButton {{
      background: {t['accent']};
      border: 1px solid {t['accent']};
      border-radius: 10px;
      padding: 10px 14px;
      font-weight: 600;
      color: white;
    }}
    QPushButton:hover {{
      background: {t['accent_hover']};
      border-color: {t['accent_hover']};
    }}
    QPushButton:disabled {{
      background: {t['border']};
      border-color: {t['border']};
      color: {t['muted']};
    }}

    QToolButton {{
      background: {t['card']};
      border: 1px solid {t['border']};
      border-radius: 10px;
      padding: 8px 10px;
      color: {t['text']};
    }}
    QToolButton:hover {{
      background: {t['selection']};
    }}

    QCheckBox {{
      spacing: 8px;
    }}

    QProgressBar {{
      background: {t['surface']};
      border: 1px solid {t['border']};
      border-radius: 10px;
      height: 14px;
      text-align: center;
      color: {t['muted']};
    }}
    QProgressBar::chunk {{
      background: {t['accent']};
      border-radius: 10px;
    }}

    /* Tables */
    QTableWidget, QTableView {{
      background: {t['surface']};
      border: 1px solid {t['border']};
      border-radius: 12px;
      gridline-color: {t['border']};
      selection-background-color: {t['selection']};
      selection-color: {t['text']};
      alternate-background-color: {t['bg']};
    }}
    QHeaderView::section {{
      background: {t['bg']};
      border: none;
      padding: 8px;
      color: {t['text']};
      font-weight: 700;
    }}
    QTableWidget::item {{
      padding: 6px;
    }}

    /* Menus */
    QMenu {{
      background: {t['surface']};
      border: 1px solid {t['border']};
      padding: 6px;
    }}
    QMenu::item {{
      padding: 8px 12px;
      border-radius: 8px;
      color: {t['text']};
    }}
    QMenu::item:selected {{
      background: {t['selection']};
    }}

    QMessageBox {{
      background: {t['bg']};
    }}
    """)


def apply_theme(app, theme_name: str) -> None:
    t = THEMES.get(theme_name, next(iter(THEMES.values())))
    app.setStyle("Fusion")
    app.setStyleSheet(build_stylesheet(t))


def human_size(n: int) -> str:
    if n <= 0:
        return ""
    for unit in ["B", "KB", "MB", "GB"]:
        if n < 1024:
            return f"{n:.0f}{unit}"
        n /= 1024
    return f"{n:.1f}TB"


def human_time(ts: float) -> str:
    if ts <= 0:
        return ""
    return time.strftime("%Y-%m-%d", time.localtime(ts))


class ScanWorker(QThread):
    progress = Signal(int, str)
    finished = Signal(list)
    failed = Signal(str)

    def __init__(self, game_root: str, output_dir: str, rules: dict, prefer_html: bool):
        super().__init__()
        self.game_root = game_root
        self.output_dir = output_dir
        self.rules = rules
        self.prefer_html = prefer_html

    def run(self):
        try:

            items: List[ScanItem] = []
            if not os.path.isdir(self.game_root):
                self.failed.emit("Game root folder is invalid.")
                return
            os.makedirs(self.output_dir, exist_ok=True)

            index = storage.load_shortcut_index(self.output_dir)
            shortcuts_meta = index.get("shortcuts", {})

            folders = list_game_folders(self.game_root)
            n = len(folders)
            if n == 0:
                self.finished.emit([])
                return

            for i, gf in enumerate(folders, start=1):
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
                    exe_candidates=cands,
                )

                display_name = base_title

                # ------------------------
                # Existing shortcut detection (filesystem-first)
                # Treat .lnk and .url as equivalent "existing shortcut"
                # Also detect (1), (2) duplicates as "existing"
                # ------------------------
                base = safe_filename(display_name)
                canonical_lnk = os.path.join(self.output_dir, f"{base}.lnk")
                canonical_url = os.path.join(self.output_dir, f"{base}.url")

                existing_path = ""
                existing_type = ""  # "exe" or "html"

                if os.path.exists(canonical_lnk):
                    existing_path = canonical_lnk
                    existing_type = "exe"
                elif os.path.exists(canonical_url):
                    existing_path = canonical_url
                    existing_type = "html"
                else:
                    # fallback to numbered duplicates (Name (1).lnk / .url)
                    dup_lnk = sorted(glob.glob(os.path.join(self.output_dir, f"{base} (*).lnk")))
                    dup_url = sorted(glob.glob(os.path.join(self.output_dir, f"{base} (*).url")))
                    if dup_lnk:
                        existing_path = dup_lnk[0]
                        existing_type = "exe"
                    elif dup_url:
                        existing_path = dup_url[0]
                        existing_type = "html"

                item.existing_shortcut_path = existing_path

                # Meta used mainly for version comparisons; do not trust it for existence
                meta = shortcuts_meta.get(display_name, {})
                item.existing_version_str = meta.get("version_str", "")
                item.existing_version_tuple = tuple(meta.get("version_tuple", [])) if meta.get("version_tuple") else tuple()
                item.existing_target = meta.get("target", "")

                # If no meta target but file exists, best-effort recover
                if item.existing_shortcut_path and not item.existing_target:
                    try:
                        if existing_type == "html" or item.existing_shortcut_path.lower().endswith(".url"):
                            with open(item.existing_shortcut_path, "r", encoding="utf-8", errors="ignore") as f:
                                for line in f:
                                    if line.strip().lower().startswith("url="):
                                        item.existing_target = line.split("=", 1)[1].strip()
                                        break
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

                    items.append(item)
                    pct = int(i * 100 / n)
                    self.progress.emit(pct, f"Scanned {i}/{n}: {folder_name}")
                    continue

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

                    items.append(item)
                    pct = int(i * 100 / n)
                    self.progress.emit(pct, f"Scanned {i}/{n}: {folder_name}")
                    continue

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

                items.append(item)

                pct = int(i * 100 / n)
                self.progress.emit(pct, f"Scanned {i}/{n}: {folder_name}")

            self.finished.emit(items)
        except Exception as e:
            self.failed.emit(str(e))


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
                    base = safe_filename(display)

                    canonical_lnk = os.path.join(self.output_dir, f"{base}.lnk")
                    canonical_url = os.path.join(self.output_dir, f"{base}.url")

                    tt = getattr(it, "target_type", "exe")  # "exe" or "html"
                    out_path = canonical_url if tt == "html" else canonical_lnk
                    other_path = canonical_lnk if tt == "html" else canonical_url

                    # -----------------------------------------
                    # Clean numbered duplicates: Name (1).lnk/.url, etc.
                    # -----------------------------------------
                    if not self.dry_run:
                        for p in glob.glob(os.path.join(self.output_dir, f"{base} (*).lnk")):
                            try:
                                os.remove(p)
                            except Exception:
                                pass
                        for p in glob.glob(os.path.join(self.output_dir, f"{base} (*).url")):
                            try:
                                os.remove(p)
                            except Exception:
                                pass

                        # Ensure only one type exists (remove opposite type)
                        if os.path.exists(other_path):
                            try:
                                os.remove(other_path)
                            except Exception:
                                pass

                    # -----------------------------------------
                    # Backup on replace (backup whatever file we are replacing)
                    # -----------------------------------------
                    backup_path = ""
                    if decision == ItemDecision.REPLACE and os.path.exists(out_path) and not self.dry_run:
                        backup_path = backup_shortcut(out_path, backup_dir)

                    # -----------------------------------------
                    # Write shortcut
                    # -----------------------------------------
                    if not self.dry_run:
                        if tt == "html":
                            create_url_shortcut(out_path, it.chosen_exe)
                        else:
                            create_or_replace_shortcut(out_path, it.chosen_exe)

                    # -----------------------------------------
                    # Update index
                    # -----------------------------------------
                    shortcuts_meta[display] = {
                        "shortcut_name": os.path.basename(out_path),
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


    def _open_launcher_picker_for_row(self, row: int) -> None:
        if row < 0 or row >= len(self.items):
            return
        it = self.items[row]

        dlg = LauncherPickerDialog(it, self)
        if dlg.exec() != QDialog.Accepted:
            return

        it.target_type = dlg.selected_type
        it.chosen_exe = dlg.selected_path

        # Keep the recommended visible (first EXE candidate) even if user picks something else
        if it.exe_candidates:
            it.recommended_exe = it.exe_candidates[0].path

        self._recompute_item_decision(it)
        self._populate_review()

        dlg.exec()

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
        storage.save_settings(self.settings)


        self.btn_scan.setEnabled(False)
        self.pb.setValue(0)
        self.lbl_status.setText("Scanning…")
        self.worker = ScanWorker(
            self.game_root,
            self.output_dir,
            self.rules,
            self.settings.get("prefer_html", False)
        )
        self.worker.progress.connect(self._on_scan_progress)
        self.worker.finished.connect(self._on_scan_finished)
        self.worker.failed.connect(self._on_scan_failed)
        self.worker.start()

    def _on_scan_progress(self, pct: int, msg: str):
        self.pb.setValue(pct)
        self.lbl_status.setText(msg)

    def _on_scan_failed(self, err: str):
        self.btn_scan.setEnabled(True)
        self.lbl_status.setText("Scan failed.")
        QMessageBox.critical(self, "Scan failed", err)

    def _on_scan_finished(self, items: list):
        self.btn_scan.setEnabled(True)
        self.items = items

        if not items:
            self.lbl_status.setText("No game folders found.")
            QMessageBox.information(self, "No folders", "No game folders found in the game root.")
            return

        # Resolve conflicts with a friendly picker
        for it in self.items:
            if it.decision == ItemDecision.NEEDS_RESOLVE:
                dlg = LauncherPickerDialog(it, self)
                if dlg.exec() != QDialog.Accepted:
                    it.selected = False
                    it.decision = ItemDecision.SKIP
                    it.detail = "Skipped (not resolved)"
                    continue

                it.chosen_exe = dlg.selected_path
                it.target_type = dlg.selected_type
                it.recommended_exe = it.exe_candidates[0].path if it.exe_candidates else it.chosen_exe

                if it.existing_shortcut_path:
                    cmpv = compare_versions(it.version_tuple, it.existing_version_tuple)
                    if cmpv > 0:
                        it.decision = ItemDecision.REPLACE
                        it.detail = f"Newer version replaces {it.existing_version_str or 'unknown'}"
                    else:
                        it.decision = ItemDecision.SKIP
                        it.detail = "Shortcut already exists (kept)"
                        it.selected = False
                else:
                    it.decision = ItemDecision.CREATE
                    it.detail = "Ready to create"

        self._populate_review()
        self.stack.setCurrentWidget(self.page_review)

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
        self.tbl = QTableWidget(0, 11)
        self.tbl.setHorizontalHeaderLabels([
            "Use", "Force", "Status", "Type", "Game Folder", "Base Title", "Version",
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

            # Type column + icon
            tt = getattr(it, "target_type", "exe")
            type_text = "HTML" if tt == "html" else "EXE"
            type_item = QTableWidgetItem(type_text)
            type_item.setFlags(type_item.flags() ^ Qt.ItemIsEditable)
            type_item.setIcon(self.style().standardIcon(QStyle.SP_FileIcon))
            self.tbl.setItem(row, 3, type_item)

            # Target name with HTML label (clear)
            target_name = os.path.basename(it.chosen_exe or it.recommended_exe)
            if tt == "html":
                target_name = f"{target_name} (HTML)"

            put(4, it.folder_name)
            put(5, it.base_title)
            put(6, it.version_str or "")
            put(7, target_name)
            put(8, f"{it.existing_version_str or ''} {os.path.basename(it.existing_shortcut_path) if it.existing_shortcut_path else ''}".strip())
            put(9, it.detail)

            top_score = it.exe_candidates[0].score if it.exe_candidates else 0
            put(10, str(top_score) if top_score else "")


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

            text_blob = f"{it.folder_name} {it.base_title} {it.version_str}".lower()
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
        QMessageBox.information(
            self,
            "Completed",
            f"{'Dry Run finished' if self.cb_dryrun.isChecked() else 'Applied changes'}\n"
            f"Total: {total}\nErrors: {errors}\n\nOutput:\n{self.output_dir}"
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


def run_app():
    app = QApplication([])
    apply_theme(app, "Midnight Blue")

    win = MainWindow()
    win.show()
    app.exec()
