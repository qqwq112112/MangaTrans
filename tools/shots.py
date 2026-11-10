# -*- coding: utf-8 -*-
"""Render the UI to PNG files offscreen for visual inspection."""

from __future__ import annotations

import os
import sys
from pathlib import Path

# Renders real windows with the native Windows platform plugin: the offscreen
# plugin cannot see system fonts (0 families), so Chinese text would render as boxes.
if os.environ.get("MGT_SHOTS_OFFSCREEN") == "1":
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from PySide6.QtCore import QPoint, Qt  # noqa: E402
from PySide6.QtGui import QFont  # noqa: E402
from PySide6.QtTest import QTest  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from mangatrans.archive import load_input_images  # noqa: E402
from mangatrans.config import AppConfig  # noqa: E402
from mangatrans.document import Document, PageModel  # noqa: E402
from mangatrans.main_window import MainWindow  # noqa: E402
from mangatrans.region_dialog import RegionDialog  # noqa: E402
from mangatrans.settings_dialog import SettingsDialog  # noqa: E402
from mangatrans.theme import apply_theme  # noqa: E402

OUT = ROOT / "samples" / "shots"


def save(widget, name: str) -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    widget.repaint()
    QApplication.processEvents()
    pix = widget.grab()
    path = OUT / name
    pix.save(str(path), "PNG")
    print(f"{name}: {pix.width()}x{pix.height()}")


def main() -> int:
    app = QApplication(sys.argv)
    app.setFont(QFont("Microsoft YaHei UI", 9))
    apply_theme(app)

    win = MainWindow()
    win.resize(1400, 900)
    win.show()
    QTest.qWait(150)
    save(win, "01_empty.png")

    zip_path = ROOT / "samples" / "sample_manga.zip"
    images, title = load_input_images(zip_path)
    doc = Document([PageModel(p) for p in images], zip_path, title)
    win.doc = doc
    win.canvas.set_document(doc)
    win.stack.setCurrentWidget(win.canvas)
    win.doc_label.setText(f"{doc.title} · {doc.page_count} 页")
    win.page_slider.setRange(0, doc.page_count - 1)
    win._page_changed(0)
    win._update_enabled()
    QTest.qWait(250)
    save(win, "02_loaded.png")

    # simulate long press + drag selection on page 1
    view = win.canvas
    vp = view.viewport()
    start = QPoint(int(vp.width() * 0.30), int(vp.height() * 0.22))
    end = QPoint(int(vp.width() * 0.72), int(vp.height() * 0.40))
    QTest.mousePress(vp, Qt.LeftButton, Qt.NoModifier, start)
    QTest.qWait(400)
    for i in range(1, 11):
        pt = QPoint(start.x() + (end.x() - start.x()) * i // 10,
                    start.y() + (end.y() - start.y()) * i // 10)
        QTest.mouseMove(vp, pt)
        QTest.qWait(12)
    QTest.mouseRelease(vp, Qt.LeftButton, Qt.NoModifier, end)
    QTest.qWait(120)
    save(win, "03_selection.png")
    print("pending regions:", view.pending_count)

    if view.pending_count:
        drafts = [d for _i, _o, d in view._pending]
        cfg = AppConfig()
        cfg.auto_ocr = False
        dlg = RegionDialog(doc, drafts, cfg, view, win)
        dlg.resize(1300, 940)
        dlg.show()
        QTest.qWait(200)
        dlg.source_edit.setPlainText("今天天气真不错。\n要不要一起出去？")
        dlg._translate_done(0, (True, "今天天气真不错。\n要不要一起出去？"))
        dlg.auto_fit.setChecked(True)
        QTest.qWait(200)
        save(dlg, "04_region_dialog.png")
        dlg.close()

    settings = SettingsDialog(AppConfig(), win)
    settings.show()
    QTest.qWait(150)
    save(settings, "05_settings.png")

    # Also capture the cloud-provider view of the same dialog.
    idx = settings.provider_combo.findData("siliconflow")
    settings.provider_combo.setCurrentIndex(idx)
    QTest.qWait(150)
    save(settings, "05b_settings_cloud.png")
    settings.close()

    # vertical mode
    win._set_mode("vertical")
    QTest.qWait(300)
    save(win, "06_vertical.png")

    win.close()
    print("done ->", OUT)
    return 0


if __name__ == "__main__":
    sys.exit(main())
