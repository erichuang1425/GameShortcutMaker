"""Theme palettes, stylesheet builder, and small humanize helpers for the GUI."""
from __future__ import annotations

import time


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
