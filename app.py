"""Thin entry point: build the QApplication and show the main window."""
from __future__ import annotations

from PySide6.QtWidgets import QApplication

from ui.theme import apply_theme
from ui.main_window import MainWindow


def run_app():
    app = QApplication([])
    apply_theme(app, "Midnight Blue")

    win = MainWindow()
    # Launch maximized so the window fills the screen instead of opening at a
    # fixed width that could be too wide / off-center. Un-maximizing restores
    # the centered default geometry set in MainWindow._set_initial_geometry.
    win.showMaximized()
    app.exec()
