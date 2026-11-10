# -*- coding: utf-8 -*-
"""Screenshots for the project library (断点记忆) UI."""

from __future__ import annotations

import os
import shutil
import sys
import tempfile
from pathlib import Path

if os.environ.get("MGT_SHOTS_OFFSCREEN") == "1":
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from PySide6.QtCore import QRectF  # noqa: E402
from PySide6.QtGui import QColor, QFont, QPixmap  # noqa: E402
from PySide6.QtTest import QTest  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from mangatrans.archive import load_input_images  # noqa: E402
from mangatrans.document import Document, PageModel  # noqa: E402
from mangatrans.library_dialog import LibraryDialog  # noqa: E402
from mangatrans.main_window import MainWindow  # noqa: E402
from mangatrans.project_store import ProjectStore  # noqa: E402
from mangatrans.textrender import RegionOp  # noqa: E402
from mangatrans.theme import apply_theme  # noqa: E402

OUT = ROOT / "samples" / "shots"


def save(widget, name: str) -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    widget.repaint()
    QApplication.processEvents()
    pix = widget.grab()
    pix.save(str(OUT / name), "PNG")
    print(f"{name}: {pix.width()}x{pix.height()}")


def seed_store(store: ProjectStore, tmp: Path) -> None:
    books = [
        (ROOT / "samples" / "sample_manga_ja.zip", "第01話 雨の日に.zip",
         [(0, "等等一下！\n那声音……"), (1, "吵死了！\n去那边！")], 1, "连载中"),
        (ROOT / "samples" / "sample_manga.zip", "sample_manga.zip",
         [(0, "今天天气真不错。\n要不要一起出去？")], 0, "连载中"),
    ]
    for i, (path, title, texts, last_page, cat) in enumerate(books):
        if not path.exists():
            continue
        images, _ = load_input_images(path)
        doc = Document([PageModel(p) for p in images], path, title)
        for page, text in texts:
            doc.add_op(page, RegionOp(
                rect=QRectF(0.10, 0.08, 0.55, 0.28),
                fill_color=QColor("#FFFFFF"),
                text=text,
                font_family="Noto Sans SC",
                auto_fit=True,
                fill_shape="ellipse",
            ))
        project = store.touch(path, title, "archive", doc.page_count)
        project.title = title
        pix = QPixmap(160, 220)
        if doc.page_count:
            pix = doc.page_pixmap(0, 300)
        store.save_progress(project.id, doc, last_page, "horizontal", pix)
        if i == 0:
            project.category = cat
        store.save()
    store.add_category("连载中")


def main() -> int:
    app = QApplication(sys.argv)
    app.setFont(QFont("Microsoft YaHei UI", 9))
    apply_theme(app)

    tmp = Path(tempfile.mkdtemp(prefix="mgt_shots_"))
    try:
        store_path = tmp / "projects.json"
        store = ProjectStore(store_path, tmp / "thumbs")
        seed_store(store, tmp)

        win = MainWindow()
        win.store = store
        win.resize(1400, 900)
        win.show()
        win._refresh_library_button()
        QTest.qWait(200)
        save(win, "08_empty_recent.png")

        win.open_path(ROOT / "samples" / "sample_manga_ja.zip", restore=True)
        QTest.qWait(400)
        save(win, "09_resumed.png")

        dlg = LibraryDialog(store, win)
        dlg.resize(1040, 700)
        dlg.show()
        QTest.qWait(250)
        save(dlg, "10_library.png")

        dlg.project_list.setCurrentRow(0)
        QTest.qWait(80)
        dlg._project_menu(dlg.project_list.visualItemRect(
            dlg.project_list.currentItem()).center())
        QTest.qWait(200)
        save(dlg, "11_library_menu.png")
        dlg.close()
        win.close()
    finally:
        shutil.rmtree(tmp, ignore_errors=True)

    print("done ->", OUT)
    return 0


if __name__ == "__main__":
    sys.exit(main())
