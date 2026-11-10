# -*- coding: utf-8 -*-
"""Tests for the two independent histories and the standalone overwrite button.

Run: python tools/test_history.py
"""

from __future__ import annotations

import os
import shutil
import sys
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from PySide6.QtCore import QRectF  # noqa: E402
from PySide6.QtGui import QColor  # noqa: E402
from PySide6.QtTest import QTest  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from mangatrans.config import AppConfig  # noqa: E402
from mangatrans.document import Document, PageModel  # noqa: E402
from mangatrans.archive import load_input_images  # noqa: E402
from mangatrans.history import SnapshotHistory  # noqa: E402
from mangatrans.main_window import MainWindow  # noqa: E402
from mangatrans.region_dialog import RegionDialog  # noqa: E402
from mangatrans.textrender import RegionOp  # noqa: E402
from mangatrans.theme import apply_theme  # noqa: E402
from mangatrans.viewer import RegionDraft  # noqa: E402

FAILED: list[str] = []


def check(name: str, cond: bool, detail: str = "") -> None:
    print(("  PASS  " if cond else "  FAIL  ") + name + (f" {detail}" if detail else ""))
    if not cond:
        FAILED.append(name)


def op(text: str, rect=(0.1, 0.1, 0.4, 0.2)) -> RegionOp:
    return RegionOp(rect=QRectF(*rect), fill_color=QColor("#FFFFFF"), text=text,
                    font_family="Noto Sans SC", auto_fit=True)


# ---------------------------------------------------------------- unit level

def test_snapshot_history() -> None:
    print("[1] SnapshotHistory 基本行为")
    state = {"n": 0, "log": []}

    def capture():
        return {"n": state["n"], "log": list(state["log"])}

    def restore(snap):
        state["n"] = snap["n"]
        state["log"] = list(snap["log"])

    h = SnapshotHistory(capture, restore)
    h.reset()

    state["n"] = 1
    h.mark()                      # undo point BEFORE n=2
    state["n"] = 2

    check("可回退", h.can_undo)
    check("不可前进", not h.can_redo)

    h.undo()
    check("回退到 1", state["n"] == 1, str(state["n"]))
    check("回退后可前进", h.can_redo)

    h.redo()
    check("前进到 2", state["n"] == 2, str(state["n"]))

    state["n"] = 3
    h.mark()                      # undo point before n=4
    state["n"] = 4
    h.undo()
    check("多步回退", state["n"] == 3, str(state["n"]))
    # A new edit after undo must invalidate the redo branch.
    h.mark()
    state["n"] = 99
    check("新分支清空 future", not h.can_redo)


def test_two_stacks_isolated(app) -> None:
    print("[2] 翻译历史与视图历史互不影响")
    images, title = load_input_images(ROOT / "samples" / "sample_manga.zip")
    doc = Document([PageModel(p) for p in images], None, title)
    win = MainWindow()
    win.resize(1100, 800)
    win.show()
    win.doc = doc
    win.project_id = None
    win.canvas.set_document(doc)
    win.stack.setCurrentWidget(win.canvas)
    # Pin horizontal mode: the saved reading mode may be vertical, where page
    # navigation follows scrolling and makes page assertions nondeterministic.
    win.canvas.set_mode("horizontal")
    win._reset_histories()
    QTest.qWait(150)
    win.canvas.go_to_page(0)
    QTest.qWait(80)

    # 1) translation: add an op (through the real path)
    win._tx_mark()
    doc.add_op(0, op("第一处"))
    win.canvas.refresh_page(0)
    check("加译文后有可回退", win.tx_history.can_undo)
    check("视图历史未受影响", not win.view_history.can_undo)

    # 2) view: change page
    win._view_mark()
    win.canvas.go_to_page(1)
    QTest.qWait(60)
    check("翻页后有视图可回退", win.view_history.can_undo)
    check("视图操作未污染翻译历史",
          win.tx_history.undo_depth == 1, str(win.tx_history.undo_depth))

    # 3) undo translation only: the page must stay where it is
    QTest.qWait(60)
    page_before = win.canvas.current
    win.tx_undo()
    QTest.qWait(80)
    check("翻译回退后译文消失", not doc.pages[0].ops,
          f"ops={len(doc.pages[0].ops)}")
    check("翻译回退不改变页码", win.canvas.current == page_before,
          f"{page_before} -> {win.canvas.current}")

    # 4) undo view only: translations must not come back
    win.view_undo()
    QTest.qWait(60)
    check("视图回退后页码复位", win.canvas.current == 0, str(win.canvas.current))
    check("视图回退不恢复译文", not doc.pages[0].ops,
          f"ops={len(doc.pages[0].ops)}")

    # 5) redo both
    win.tx_redo()
    QTest.qWait(40)
    check("翻译可前进", len(doc.pages[0].ops) == 1, str(len(doc.pages[0].ops)))
    win.view_redo()
    QTest.qWait(80)
    check("视图可前进", win.canvas.current == 1, str(win.canvas.current))
    win.close()


def test_history_ignores_restore(app) -> None:
    print("[3] 恢复历史时不再产生新历史")
    images, title = load_input_images(ROOT / "samples" / "sample_manga.zip")
    doc = Document([PageModel(p) for p in images], None, title)
    win = MainWindow()
    win.resize(1100, 800)
    win.show()
    win.doc = doc
    win.project_id = None
    win.canvas.set_document(doc)
    win._reset_histories()
    QTest.qWait(100)

    win._tx_mark()
    doc.add_op(0, op("A"))
    depth_after_add = win.tx_history.undo_depth

    win.tx_undo()
    QTest.qWait(40)
    # Undo/redo restore must not create extra undo points.
    check("undo 未新增历史", win.tx_history.undo_depth == depth_after_add - 1,
          f"{depth_after_add} -> {win.tx_history.undo_depth}")
    check("redo 后历史长度稳定", win.tx_history.redo_depth == 1,
          str(win.tx_history.redo_depth))
    win.close()


# ---------------------------------------------------------------- overwrite

def test_overwrite_only(app) -> None:
    print("[4] 单独覆写：只写文字，不识别不翻译，面板不关")
    images, title = load_input_images(ROOT / "samples" / "sample_manga_ja.zip")
    doc = Document([PageModel(p) for p in images], None, title)
    cfg = AppConfig()
    cfg.auto_ocr = False

    draft = RegionDraft(0, QRectF(0.1, 0.1, 0.4, 0.2), doc.original_size(0))
    dlg = RegionDialog(doc, [draft], cfg, None)
    dlg.show()
    app.processEvents()

    # nothing to overwrite yet
    dlg._overwrite_only()
    app.processEvents()
    check("空译文时拒绝覆写", "空的" in dlg.status.text(), dlg.status.text()[:30])

    got: list[tuple] = []
    dlg.overwriteRequested.connect(lambda idx, o: got.append((idx, o)))

    dlg.translated_edit.setPlainText("手动输入的译文")
    app.processEvents()
    dlg._overwrite_only()
    app.processEvents()

    check("发出覆写信号", len(got) == 1, str(len(got)))
    check("文字正确", got and got[0][1].text == "手动输入的译文",
          got[0][1].text if got else "")
    check("面板仍打开", dlg.isVisible())
    check("未触发 OCR", dlg.states[0].ocr_state == "idle", dlg.states[0].ocr_state)

    # second overwrite must be flagged as an update, not a new region
    dlg.translated_edit.setPlainText("改过的译文")
    app.processEvents()
    dlg._overwrite_only()
    app.processEvents()
    check("再次覆写仍发信号", len(got) == 2, str(len(got)))
    check("第二次标记为更新", "更新" in dlg.status.text(), dlg.status.text()[:30])
    check("文字已更新", got[-1][1].text == "改过的译文", got[-1][1].text)
    dlg.close()


def test_overwrite_in_window(app) -> None:
    print("[5] 主窗口：单独覆写不重复堆叠")
    images, title = load_input_images(ROOT / "samples" / "sample_manga_ja.zip")
    doc = Document([PageModel(p) for p in images], None, title)

    win = MainWindow()
    win.doc = doc
    win.project_id = None
    win.canvas.set_document(doc)
    win._reset_histories()

    store: dict = {}
    fake_dialog = object()
    o1 = op("第一次", (0.1, 0.1, 0.3, 0.15))
    win._apply_overwrite(fake_dialog, 0, o1, store)
    check("首次覆写写入 1 处", len(doc.pages[0].ops) == 1,
          str(len(doc.pages[0].ops)))

    o2 = op("第二次", (0.1, 0.1, 0.35, 0.18))
    win._apply_overwrite(fake_dialog, 0, o2, store)
    check("再次覆写不堆叠", len(doc.pages[0].ops) == 1,
          str(len(doc.pages[0].ops)))
    check("内容已替换", doc.pages[0].ops[0].text == "第二次",
          doc.pages[0].ops[0].text)
    check("位置已替换", abs(doc.pages[0].ops[0].rect.width() - 0.35) < 1e-9,
          str(doc.pages[0].ops[0].rect.width()))
    check("覆写可回退", win.tx_history.can_undo)

    # Undo #1 -> back to the state after the FIRST overwrite (still 1 op).
    win.tx_undo()
    check("回退一步 = 第一次覆写状态", len(doc.pages[0].ops) == 1,
          str(len(doc.pages[0].ops)))
    check("回退一步内容正确", doc.pages[0].ops[0].text == "第一次",
          doc.pages[0].ops[0].text)
    # Undo #2 -> back to before any overwrite.
    win.tx_undo()
    check("回退两步 = 无覆写", not doc.pages[0].ops, str(len(doc.pages[0].ops)))
    win.close()


def main() -> int:
    app = QApplication(sys.argv)
    apply_theme(app)
    tmp = ROOT / "samples" / "_hist_out"
    try:
        test_snapshot_history()
        test_two_stacks_isolated(app)
        test_history_ignores_restore(app)
        test_overwrite_only(app)
        test_overwrite_in_window(app)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)

    print()
    if FAILED:
        print(f"失败 {len(FAILED)} 项：" + ", ".join(FAILED))
        return 1
    print("双历史 + 单独覆写 全部通过")
    return 0


if __name__ == "__main__":
    sys.exit(main())
