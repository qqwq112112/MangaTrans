# -*- coding: utf-8 -*-
"""Tests for cancelling / undoing selections.

Run: python tools/test_selection_cancel.py
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from PySide6.QtCore import QRectF, QSize, Qt  # noqa: E402
from PySide6.QtTest import QTest  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from mangatrans.archive import load_input_images  # noqa: E402
from mangatrans.document import Document, PageModel  # noqa: E402
from mangatrans.main_window import MainWindow  # noqa: E402
from mangatrans.theme import apply_theme  # noqa: E402
from mangatrans.viewer import RegionDraft  # noqa: E402

FAILED: list[str] = []


def check(name: str, cond: bool, detail: str = "") -> None:
    print(("  PASS  " if cond else "  FAIL  ") + name + (f" {detail}" if detail else ""))
    if not cond:
        FAILED.append(name)


def make_window(app, path: Path) -> MainWindow:
    images, title = load_input_images(path)
    doc = Document([PageModel(p) for p in images], None, title)
    win = MainWindow()
    win.resize(1200, 800)
    win.show()
    win.doc = doc
    win.project_id = None
    win.canvas.set_document(doc)
    win.stack.setCurrentWidget(win.canvas)
    win._reset_histories()
    QTest.qWait(180)
    return win


def add_pending(win: MainWindow, rect: QRectF) -> None:
    """Inject a pending selection the way a drag would."""
    view = win.canvas
    item = view._items[view.current]
    overlay = item.add_overlay(QRectF(
        rect.x() * item.base_w, rect.y() * item.base_h,
        rect.width() * item.base_w, rect.height() * item.base_h))
    draft = RegionDraft(view.current, QRectF(rect), QSize(item.orig_size))
    view._pending.append((view.current, overlay, draft))
    view.pendingChanged.emit(len(view._pending))


def test_visible_controls(app) -> None:
    print("[1] 可见的取消入口")
    win = make_window(app, ROOT / "samples" / "sample_manga_ja.zip")

    check("有「取消选区」按钮", win.btn_sel_clear.text() == "取消选区",
          win.btn_sel_clear.text())
    check("有「撤销选区」按钮", win.btn_sel_undo.text() == "撤销选区",
          win.btn_sel_undo.text())
    check("初始禁用", not win.btn_sel_clear.isEnabled()
          and not win.btn_sel_undo.isEnabled())
    check("初始不显示计数", not win.sel_label.isVisible())

    add_pending(win, QRectF(0.1, 0.1, 0.4, 0.2))
    add_pending(win, QRectF(0.5, 0.5, 0.3, 0.2))
    QTest.qWait(50)

    check("选区数 2", win.canvas.pending_count == 2, str(win.canvas.pending_count))
    check("按钮已启用", win.btn_sel_clear.isEnabled() and win.btn_sel_undo.isEnabled())
    check("显示计数", win.sel_label.isVisible() and "2" in win.sel_label.text(),
          win.sel_label.text())

    print("[2] 取消全部")
    win.cancel_selection()
    QTest.qWait(50)
    check("全部清空", win.canvas.pending_count == 0, str(win.canvas.pending_count))
    check("计数隐藏", not win.sel_label.isVisible())
    check("按钮又禁用", not win.btn_sel_clear.isEnabled())
    win.close()


def test_undo_last_only(app) -> None:
    print("[3] 只撤销最后一个")
    win = make_window(app, ROOT / "samples" / "sample_manga_ja.zip")
    add_pending(win, QRectF(0.10, 0.10, 0.3, 0.15))
    add_pending(win, QRectF(0.45, 0.45, 0.3, 0.15))
    add_pending(win, QRectF(0.70, 0.70, 0.2, 0.15))
    QTest.qWait(40)
    check("三处选区", win.canvas.pending_count == 3, str(win.canvas.pending_count))

    win.undo_last_selection()
    QTest.qWait(40)
    check("撤销后剩 2 处", win.canvas.pending_count == 2,
          str(win.canvas.pending_count))
    check("计数已更新", "2" in win.sel_label.text(), win.sel_label.text())

    win.undo_last_selection()
    win.undo_last_selection()
    QTest.qWait(40)
    check("全部撤完", win.canvas.pending_count == 0)

    win.undo_last_selection()
    check("空时给出提示", "没有" in win.statusBar().currentMessage(),
          win.statusBar().currentMessage())
    win.close()


def test_escape_without_canvas_focus(app) -> None:
    print("[4] 画布无焦点时 Esc 仍能取消")
    win = make_window(app, ROOT / "samples" / "sample_manga_ja.zip")
    add_pending(win, QRectF(0.2, 0.2, 0.4, 0.2))
    QTest.qWait(40)
    check("先有选区", win.canvas.pending_count == 1)

    # Move focus away from the canvas: this used to make Esc a no-op.
    win.btn_export.setFocus()
    QTest.qWait(30)
    check("焦点不在画布", not win.canvas.hasFocus())

    QTest.keyClick(win, Qt.Key_Escape)
    QTest.qWait(60)
    check("窗口级 Esc 清空了选区", win.canvas.pending_count == 0,
          str(win.canvas.pending_count))
    win.close()


def test_shift_backspace(app) -> None:
    print("[5] Shift+Backspace 撤销最后一个")
    win = make_window(app, ROOT / "samples" / "sample_manga_ja.zip")
    add_pending(win, QRectF(0.1, 0.1, 0.3, 0.2))
    add_pending(win, QRectF(0.5, 0.5, 0.3, 0.2))
    QTest.qWait(40)
    check("两处选区", win.canvas.pending_count == 2)

    QTest.keyClick(win, Qt.Key_Backspace, Qt.ShiftModifier)
    QTest.qWait(60)
    check("只剩 1 处", win.canvas.pending_count == 1,
          str(win.canvas.pending_count))
    win.close()


def test_cancel_does_not_touch_translations(app) -> None:
    print("[6] 取消选区不影响已应用的译文")
    from mangatrans.textrender import RegionOp
    from PySide6.QtGui import QColor

    win = make_window(app, ROOT / "samples" / "sample_manga_ja.zip")
    win.doc.add_op(0, RegionOp(rect=QRectF(0.1, 0.1, 0.3, 0.2),
                               fill_color=QColor("#FFFFFF"), text="已应用的译文"))
    win.canvas.refresh_page(0)
    add_pending(win, QRectF(0.5, 0.5, 0.3, 0.2))
    QTest.qWait(40)

    win.cancel_selection()
    QTest.qWait(40)
    check("选区清空", win.canvas.pending_count == 0)
    check("译文保留", len(win.doc.pages[0].ops) == 1,
          str(len(win.doc.pages[0].ops)))
    check("译文内容未变", win.doc.pages[0].ops[0].text == "已应用的译文",
          win.doc.pages[0].ops[0].text)
    win.close()


def main() -> int:
    app = QApplication(sys.argv)
    apply_theme(app)
    test_visible_controls(app)
    test_undo_last_only(app)
    test_escape_without_canvas_focus(app)
    test_shift_backspace(app)
    test_cancel_does_not_touch_translations(app)
    print()
    if FAILED:
        print(f"失败 {len(FAILED)} 项：" + ", ".join(FAILED))
        return 1
    print("选区取消功能全部通过")
    return 0


if __name__ == "__main__":
    sys.exit(main())
