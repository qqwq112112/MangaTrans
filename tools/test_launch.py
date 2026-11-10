# -*- coding: utf-8 -*-
"""Launch the real app entry point, open a file, then quit automatically."""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QApplication

from mangatrans.main_window import MainWindow


def run() -> int:
    from mangatrans.constants import APP_TITLE
    from mangatrans.theme import apply_theme
    from PySide6.QtGui import QFont

    app = QApplication(sys.argv)
    app.setApplicationName("MangaTrans")
    app.setApplicationDisplayName(APP_TITLE)
    app.setFont(QFont("Microsoft YaHei UI", 9))
    apply_theme(app)

    window = MainWindow()
    window.show()
    window.open_path(ROOT / "samples" / "sample_manga.zip")
    window._set_mode("vertical")

    def verify_and_quit():
        ok = window.doc is not None and window.doc.page_count == 3
        visible = window.isVisible()
        print(f"doc pages={window.doc.page_count if window.doc else None} visible={visible}")
        print("LAUNCH_OK" if ok and visible else "LAUNCH_FAIL")
        app.quit()

    QTimer.singleShot(1200, verify_and_quit)
    return app.exec()


if __name__ == "__main__":
    sys.exit(run())
