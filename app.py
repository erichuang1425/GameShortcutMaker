"""Thin entry point: build the QApplication and show the main window."""
from __future__ import annotations

from PySide6.QtWidgets import QApplication

from ui.theme import apply_theme
from ui.main_window import MainWindow


def run_app():
    app = QApplication([])
    apply_theme(app, "Midnight Blue")

    win = MainWindow()
    win.show()
    app.exec()
