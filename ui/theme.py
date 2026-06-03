"""Theme palettes, stylesheet builder, and small humanize helpers for the GUI.

The stylesheet aims for a clean, modern, "designed" look while staying purely
cosmetic — every selector is keyed off the same palette tokens, so all four
themes get the same polished treatment (focus rings, primary/secondary button
hierarchy, themed scrollbars / checkboxes, consistent radii and spacing).
Nothing here changes behaviour: callers wire the same widgets the same way.
"""
from __future__ import annotations

import os
import time

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QWidget, QVBoxLayout, QLabel, QSizePolicy


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


# ------------------------------------------------------------------
# Small colour helpers (derive hover/pressed/handle shades from a palette so
# every theme — light or dark — gets a consistent, intentional treatment).
# ------------------------------------------------------------------

def _clamp(v: float) -> int:
    return max(0, min(255, int(round(v))))


def _rgb(hex_color: str) -> tuple[int, int, int]:
    h = hex_color.lstrip("#")
    return int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)


def _hex(r: float, g: float, b: float) -> str:
    return f"#{_clamp(r):02x}{_clamp(g):02x}{_clamp(b):02x}"


def _mix(a: str, b: str, t: float) -> str:
    """Blend colour `a` toward `b` by fraction `t` (0..1). Works for any pair, so
    a tint reads as intentional on both light and dark backgrounds."""
    ar, ag, ab = _rgb(a)
    br, bg, bb = _rgb(b)
    return _hex(ar + (br - ar) * t, ag + (bg - ag) * t, ab + (bb - ab) * t)


# ------------------------------------------------------------------
# QSS icon assets (checkmark for checkable indicators). Written once per theme
# to a per-user cache dir and referenced by absolute, forward-slashed path.
# Best-effort: if anything fails, the indicator still reads as a filled accent
# box, so checkbox state stays legible without the glyph.
# ------------------------------------------------------------------

_CHECK_SVG = (
    "<svg xmlns='http://www.w3.org/2000/svg' width='16' height='16' viewBox='0 0 16 16'>"
    "<path d='M3.5 8.5 L6.6 11.4 L12.5 4.6' fill='none' stroke='{c}' "
    "stroke-width='2.2' stroke-linecap='round' stroke-linejoin='round'/></svg>"
)


def _write_qss_icons(t: dict) -> dict:
    try:
        from storage import app_config_dir
        d = os.path.join(app_config_dir(), "_qss_icons")
        os.makedirs(d, exist_ok=True)

        # Tick colour: white on the accent fill, unless the accent is so light a
        # dark tick reads better (keeps contrast on pale-accent themes).
        ar, ag, ab = _rgb(t["accent"])
        luminance = (0.299 * ar + 0.587 * ag + 0.114 * ab)
        tick = "#0b0d12" if luminance > 170 else "#ffffff"

        path = os.path.join(d, f"check_{tick.lstrip('#')}.svg")
        if not os.path.exists(path):
            with open(path, "w", encoding="utf-8") as f:
                f.write(_CHECK_SVG.format(c=tick))
        return {"check": path.replace("\\", "/")}
    except Exception:
        return {}


def build_stylesheet(t: dict, icons: dict | None = None) -> str:
    icons = icons or {}

    # Derived shades.
    accent_pressed = _mix(t["accent"], "#000000", 0.16)
    sec_bg = t["card"]
    sec_hover = _mix(t["card"], t["accent"], 0.14)
    sec_pressed = _mix(t["card"], t["accent"], 0.22)
    sec_border = _mix(t["border"], t["accent"], 0.10)
    field_bg = t["surface"]
    field_disabled = _mix(t["surface"], t["bg"], 0.6)
    handle = _mix(t["border"], t["text"], 0.22)
    handle_hover = _mix(t["border"], t["text"], 0.45)
    row_hover = _mix(t["surface"], t["accent"], 0.07)
    header_bg = _mix(t["card"], t["bg"], 0.5)
    divider = t["border"]

    check_rule = (
        f"image: url({icons['check']});" if icons.get("check") else ""
    )

    return f"""
    QWidget {{
      color: {t['text']};
      font-family: "Segoe UI Variable", "Segoe UI", system-ui, Arial, sans-serif;
      font-size: 13px;
    }}
    QMainWindow, QDialog {{
      background: {t['bg']};
    }}
    QToolTip {{
      background: {t['card']};
      color: {t['text']};
      border: 1px solid {t['border']};
      border-radius: 6px;
      padding: 6px 8px;
    }}

    /* Heading / caption roles (set via QLabel.setProperty("role", ...)) */
    QLabel[role="title"] {{
      font-size: 19px;
      font-weight: 800;
      color: {t['text']};
    }}
    QLabel[role="subtitle"] {{
      font-size: 13px;
      color: {t['muted']};
    }}
    QLabel[role="muted"] {{
      color: {t['muted']};
    }}
    QLabel[role="section"] {{
      font-weight: 600;
      color: {t['text']};
    }}

    /* Cards / group boxes */
    QGroupBox {{
      border: 1px solid {t['border']};
      border-radius: 12px;
      margin-top: 16px;
      padding: 14px;
      background: {t['card']};
      font-weight: 600;
    }}
    QGroupBox::title {{
      subcontrol-origin: margin;
      subcontrol-position: top left;
      left: 14px;
      padding: 2px 6px;
      color: {t['muted']};
      font-weight: 700;
    }}

    /* Text inputs */
    QLineEdit, QTextEdit, QPlainTextEdit, QSpinBox, QComboBox {{
      background: {field_bg};
      border: 1px solid {t['border']};
      border-radius: 8px;
      padding: 7px 9px;
      selection-background-color: {t['selection']};
      selection-color: {t['text']};
    }}
    QLineEdit:hover, QTextEdit:hover, QPlainTextEdit:hover,
    QSpinBox:hover, QComboBox:hover {{
      border-color: {sec_border};
    }}
    QLineEdit:focus, QTextEdit:focus, QPlainTextEdit:focus,
    QSpinBox:focus, QComboBox:focus {{
      border-color: {t['accent']};
    }}
    QLineEdit:disabled, QSpinBox:disabled, QComboBox:disabled {{
      background: {field_disabled};
      color: {t['muted']};
    }}
    QComboBox::drop-down {{
      border: none;
      width: 22px;
    }}
    QComboBox QAbstractItemView {{
      background: {t['surface']};
      border: 1px solid {t['border']};
      border-radius: 8px;
      padding: 4px;
      selection-background-color: {t['selection']};
      selection-color: {t['text']};
      outline: none;
    }}

    /* Primary buttons (the one main action per screen) */
    QPushButton {{
      background: {t['accent']};
      border: 1px solid {t['accent']};
      border-radius: 8px;
      padding: 8px 16px;
      min-height: 18px;
      font-weight: 600;
      color: white;
    }}
    QPushButton:hover {{
      background: {t['accent_hover']};
      border-color: {t['accent_hover']};
    }}
    QPushButton:pressed {{
      background: {accent_pressed};
      border-color: {accent_pressed};
    }}
    QPushButton:disabled {{
      background: {t['border']};
      border-color: {t['border']};
      color: {t['muted']};
    }}

    /* Secondary buttons (everything that isn't the primary action) */
    QPushButton[variant="secondary"] {{
      background: {sec_bg};
      border: 1px solid {t['border']};
      color: {t['text']};
    }}
    QPushButton[variant="secondary"]:hover {{
      background: {sec_hover};
      border-color: {sec_border};
    }}
    QPushButton[variant="secondary"]:pressed {{
      background: {sec_pressed};
    }}
    QPushButton[variant="secondary"]:disabled {{
      background: {field_disabled};
      border-color: {t['border']};
      color: {t['muted']};
    }}

    /* Destructive buttons */
    QPushButton[variant="danger"] {{
      background: transparent;
      border: 1px solid {t['danger']};
      color: {t['danger']};
    }}
    QPushButton[variant="danger"]:hover {{
      background: {_mix(t['card'], t['danger'], 0.16)};
    }}

    QToolButton {{
      background: {sec_bg};
      border: 1px solid {t['border']};
      border-radius: 8px;
      padding: 7px 12px;
      min-height: 18px;
      color: {t['text']};
    }}
    QToolButton:hover {{
      background: {sec_hover};
      border-color: {sec_border};
    }}
    QToolButton:pressed {{
      background: {sec_pressed};
    }}

    /* Checkboxes (and checkable list/table items) */
    QCheckBox {{
      spacing: 8px;
    }}
    QCheckBox::indicator,
    QListView::indicator,
    QTreeView::indicator {{
      width: 18px;
      height: 18px;
      border: 1px solid {_mix(t['border'], t['text'], 0.15)};
      border-radius: 5px;
      background: {field_bg};
    }}
    QCheckBox::indicator:hover,
    QListView::indicator:hover {{
      border-color: {t['accent']};
    }}
    QCheckBox::indicator:checked,
    QListView::indicator:checked,
    QTreeView::indicator:checked {{
      background: {t['accent']};
      border-color: {t['accent']};
      {check_rule}
    }}
    QCheckBox::indicator:disabled {{
      background: {field_disabled};
      border-color: {t['border']};
    }}

    /* Spin box buttons */
    QSpinBox::up-button, QSpinBox::down-button {{
      width: 18px;
      border: none;
      background: transparent;
    }}

    /* Progress */
    QProgressBar {{
      background: {field_bg};
      border: 1px solid {t['border']};
      border-radius: 8px;
      height: 14px;
      text-align: center;
      color: {t['muted']};
    }}
    QProgressBar::chunk {{
      background: {t['accent']};
      border-radius: 7px;
      margin: 1px;
    }}

    /* Lists (dialog pickers) */
    QListWidget, QListView, QTreeView {{
      background: {t['surface']};
      border: 1px solid {t['border']};
      border-radius: 10px;
      padding: 4px;
      outline: none;
      alternate-background-color: {_mix(t['surface'], t['bg'], 0.5)};
    }}
    QListWidget::item {{
      border-radius: 8px;
      padding: 8px;
      margin: 1px 2px;
    }}
    QListWidget::item:hover {{
      background: {row_hover};
    }}
    QListWidget::item:selected {{
      background: {t['selection']};
      color: {t['text']};
    }}

    /* Tables */
    QTableWidget, QTableView {{
      background: {t['surface']};
      border: 1px solid {t['border']};
      border-radius: 12px;
      gridline-color: {divider};
      selection-background-color: {t['selection']};
      selection-color: {t['text']};
      alternate-background-color: {_mix(t['surface'], t['bg'], 0.5)};
    }}
    QTableView::item {{
      padding: 6px;
    }}
    QTableView::item:hover {{
      background: {row_hover};
    }}
    QHeaderView::section {{
      background: {header_bg};
      border: none;
      border-bottom: 1px solid {divider};
      padding: 9px 10px;
      color: {t['muted']};
      font-weight: 700;
    }}
    QHeaderView::section:horizontal {{
      border-right: 1px solid {_mix(divider, t['surface'], 0.4)};
    }}
    QTableCornerButton::section {{
      background: {header_bg};
      border: none;
      border-bottom: 1px solid {divider};
    }}

    /* Scrollbars */
    QScrollBar:vertical {{
      background: transparent;
      width: 12px;
      margin: 2px;
    }}
    QScrollBar::handle:vertical {{
      background: {handle};
      border-radius: 5px;
      min-height: 28px;
    }}
    QScrollBar::handle:vertical:hover {{
      background: {handle_hover};
    }}
    QScrollBar:horizontal {{
      background: transparent;
      height: 12px;
      margin: 2px;
    }}
    QScrollBar::handle:horizontal {{
      background: {handle};
      border-radius: 5px;
      min-width: 28px;
    }}
    QScrollBar::handle:horizontal:hover {{
      background: {handle_hover};
    }}
    QScrollBar::add-line, QScrollBar::sub-line {{
      width: 0; height: 0;
    }}
    QScrollBar::add-page, QScrollBar::sub-page {{
      background: transparent;
    }}

    /* Menus */
    QMenu {{
      background: {t['surface']};
      border: 1px solid {t['border']};
      border-radius: 10px;
      padding: 6px;
    }}
    QMenu::item {{
      padding: 8px 14px;
      border-radius: 7px;
      color: {t['text']};
    }}
    QMenu::item:selected {{
      background: {t['selection']};
    }}
    QMenu::separator {{
      height: 1px;
      background: {divider};
      margin: 6px 8px;
    }}

    QMessageBox {{
      background: {t['bg']};
    }}
    """


def apply_theme(app, theme_name: str) -> None:
    t = THEMES.get(theme_name, next(iter(THEMES.values())))
    app.setStyle("Fusion")
    icons = _write_qss_icons(t)
    app.setStyleSheet(build_stylesheet(t, icons))


def make_header(title: str, *subtitles: str) -> QWidget:
    """A page/dialog header: a bold title with one or more muted caption lines,
    styled purely via QSS role properties so it tracks the active theme (unlike
    the old inline-coloured rich-text headers, which were hard-coded to the dark
    palette and looked wrong on the light theme)."""
    w = QWidget()
    # Never let the header grow past its content — otherwise, on a page with no
    # expanding widget, the layout would stretch it and push the title away from
    # the subtitle.
    w.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Maximum)
    lay = QVBoxLayout(w)
    lay.setContentsMargins(0, 0, 0, 0)
    lay.setSpacing(2)

    t = QLabel(title)
    t.setProperty("role", "title")
    t.setTextFormat(Qt.RichText)
    lay.addWidget(t)

    for line in subtitles:
        if not line:
            continue
        s = QLabel(line)
        s.setProperty("role", "subtitle")
        s.setTextFormat(Qt.RichText)
        s.setWordWrap(True)
        lay.addWidget(s)
    return w


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
