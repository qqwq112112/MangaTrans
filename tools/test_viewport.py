# -*- coding: utf-8 -*-
"""Tests for: smooth panning, precise page navigation, auto fit-to-window.

Run: python tools/test_viewport.py
"""

from __future__ import annotations

import os
import shutil
import sys
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from PySide6.QtCore import QPoint, QRectF  # noqa: E402
from PySide6.QtGui import QColor  # noqa: E402
from PySide6.QtTest import QTest  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from mangatrans.archive import load_input_images  # noqa: E402
from mangatrans.document import Document, PageModel  # noqa: E402
from mangatrans.main_window import MainWindow  # noqa: E402
from mangatrans.textrender import RegionOp  # noqa: E402
from mangatrans.theme import apply_theme  # noqa: E402
from mangatrans.viewer import BASE_PAGE_WIDTH, CanvasView  # noqa: E402

FAILED: list[str] = []


def check(name: str, cond: bool, detail: str = "") -> None:
    print(("  PASS  " if cond else "  FAIL  ") + name + (f" {detail}" if detail else ""))
    if not cond:
        FAILED.append(name)


def make_view(app, path: Path) -> CanvasView:
    images, title = load_input_images(path)
    doc = Document([PageModel(p) for p in images], None, title)
    view = CanvasView()
    view.resize(1000, 760)
    view.show()
    view.set_document(doc)
    QTest.qWait(120)
    return view


def test_pan_precision(app) -> None:
    print("[1] 平移跟手精度（消除颤动）")
    view = make_view(app, ROOT / "samples" / "sample_manga_ja.zip")
    view.set_mode("horizontal")
    QTest.qWait(80)
    for zoom in (2.0, 4.0, 8.0):
        view._fit_mode = None      # stop resizeEvent from re-applying fit
        view._set_scale(zoom)
        QTest.qWait(80)
        vbar = view.verticalScrollBar()
        if vbar.maximum() <= 0:
            check(f"zoom {zoom:.0f}x 有滚动范围", False, "max=0")
            continue
        vbar.setValue(vbar.maximum() // 2)
        start = vbar.value()
        scale = view.transform().m11()

        view._begin_pan(QPoint(500, 400))
        for i in range(1, 21):
            view._pan_to(QPoint(500, 400 - 3 * i))   # 60 widget px total
        moved = vbar.value() - start
        expected = 20 * 3 / scale
        err = abs(moved - expected)
        # One scene unit of quantisation is unavoidable (integer scrollbars)
        # but truncation used to accumulate several per move event.
        check(f"zoom {zoom:.0f}x 位移准确", err <= 1.0,
              f"moved={moved} expect={expected:.2f} err={err:.2f}")

    print("[2] 往返平移对称（不漂移）")
    view._fit_mode = None
    view._set_scale(4.0)
    QTest.qWait(80)
    vbar = view.verticalScrollBar()
    vbar.setValue(vbar.maximum() // 2)
    origin = vbar.value()
    view._begin_pan(QPoint(500, 400))
    for i in range(1, 11):
        view._pan_to(QPoint(500, 400 - 2 * i))
    for i in range(9, -1, -1):
        view._pan_to(QPoint(500, 400 - 2 * i))
    check("回到原位", abs(vbar.value() - origin) <= 1,
          f"{origin} -> {vbar.value()}")

    print("[3] 撞边界后反向不跳变")
    vbar.setValue(vbar.maximum())
    view._begin_pan(QPoint(500, 400))
    view._pan_to(QPoint(500, 200))       # push past the end
    after_push = vbar.value()
    view._pan_to(QPoint(500, 260))       # reverse 60px
    moved_back = after_push - vbar.value()
    check("反向立即响应", moved_back > 0, f"moved_back={moved_back}")
    check("没有大跳变", moved_back <= int(60 / view.transform().m11()) + 2,
          f"moved_back={moved_back}")
    view.close()


def test_auto_fit(app) -> None:
    print("[4] 读取后自动填充窗口")
    win = MainWindow()
    win.resize(1100, 800)
    win.show()
    # restore=False: ignore any saved progress so the op count starts at zero
    win.open_path(ROOT / "samples" / "sample_manga_ja.zip", restore=False)
    QTest.qWait(200)
    view = win.canvas
    # The saved reading mode may be vertical; page-fit only applies to
    # single-page (horizontal) reading, so pin it for this test.
    win._set_mode("horizontal")
    view.fit_page()
    QTest.qWait(150)
    check("默认适应窗口模式", view._fit_mode == "page", str(view._fit_mode))

    vp = view.viewport()
    item = view._items[0]
    scene_box = item.sceneBoundingRect()
    shown_w = scene_box.width() * view.transform().m11()
    shown_h = scene_box.height() * view.transform().m11()
    check("页面完整可见（不超出窗口）",
          shown_h <= vp.height() + 2 and shown_w <= vp.width() + 2,
          f"page {shown_w:.0f}x{shown_h:.0f} vs view {vp.width()}x{vp.height()}")
    # "Fill" means one dimension is close to the viewport.
    fills = max(shown_w / vp.width(), shown_h / vp.height())
    check("占满了某一方向", fills > 0.85, f"fill ratio {fills:.2f}")

    print("[5] 等比缩放，不改画幅比例")
    orig = win.doc.original_size(0)
    ratio_orig = orig.width() / orig.height()
    ratio_shown = shown_w / shown_h
    check("显示比例 == 原图比例", abs(ratio_orig - ratio_shown) < 0.01,
          f"{ratio_orig:.4f} vs {ratio_shown:.4f}")
    check("视图变换 x/y 一致（无拉伸）",
          abs(view.transform().m11() - view.transform().m22()) < 1e-9,
          f"{view.transform().m11():.4f} / {view.transform().m22():.4f}")

    print("[6] 填充不影响页面数据结构")
    check("页面矩形未变", item.base_w == BASE_PAGE_WIDTH, str(item.base_w))
    expected_h = BASE_PAGE_WIDTH * orig.height() / orig.width()
    check("页面高度仍按比例", abs(item.base_h - expected_h) < 0.01,
          f"{item.base_h:.2f} vs {expected_h:.2f}")
    check("填充本身没有产生编辑", not win.doc.pages[0].ops,
          f"ops={len(win.doc.pages[0].ops)}")

    print("[7] 填充不影响导出")
    win.doc.add_op(0, RegionOp(
        rect=QRectF(0.1, 0.1, 0.5, 0.2), fill_color=QColor("#FFFFFF"),
        text="导出测试", font_family="Noto Sans SC", auto_fit=True))
    win.canvas.fit_page()
    QTest.qWait(60)
    out = ROOT / "samples" / "_fit_out"
    shutil.rmtree(out, ignore_errors=True)
    written = win.doc.export_all(out)
    from PIL import Image
    with Image.open(written[0]) as im:
        check("导出尺寸 == 原图尺寸", im.size == (orig.width(), orig.height()),
              f"{im.size} vs {(orig.width(), orig.height())}")
    shutil.rmtree(out, ignore_errors=True)

    print("[8] 缩放不影响导出（对比不同缩放）")
    sizes = []
    for scale in (0.3, 1.0, 3.0):
        win.canvas._set_scale(scale)
        QTest.qWait(40)
        out2 = ROOT / "samples" / "_fit_out2"
        shutil.rmtree(out2, ignore_errors=True)
        win.doc.export_all(out2)
        with Image.open(out2 / written[0].name) as im:
            sizes.append(im.size)
        shutil.rmtree(out2, ignore_errors=True)
    check("三种缩放下导出尺寸一致", len(set(sizes)) == 1, str(set(sizes)))
    win.close()


def test_page_navigation(app) -> None:
    print("[9] 精细页码控制")
    win = MainWindow()
    win.resize(1100, 800)
    win.show()
    win.open_path(ROOT / "samples" / "sample_manga.zip")
    QTest.qWait(200)
    win._set_mode("horizontal")
    QTest.qWait(100)
    win.canvas.go_to_page(0)
    QTest.qWait(80)

    check("默认第 1 页", win.canvas.current == 0)
    check("spin 显示 1", win.page_spin.value() == 1, str(win.page_spin.value()))

    win.page_spin.setValue(3)
    QTest.qWait(80)
    check("spin 跳到第 3 页", win.canvas.current == 2, str(win.canvas.current))
    check("label 同步", win.page_label.text() == "3 / 3", win.page_label.text())
    check("slider 同步", win.page_slider.value() == 2, str(win.page_slider.value()))

    win.page_slider.setValue(1)
    QTest.qWait(80)
    check("slider 翻页生效", win.canvas.current == 1, str(win.canvas.current))
    check("spin 同步", win.page_spin.value() == 2, str(win.page_spin.value()))

    win.canvas.prev_page()
    QTest.qWait(60)
    check("← 上一页后 spin=1", win.page_spin.value() == 1, str(win.page_spin.value()))

    check("spin 范围正确", win.page_spin.minimum() == 1 and win.page_spin.maximum() == 3,
          f"{win.page_spin.minimum()}..{win.page_spin.maximum()}")
    win.close()


def main() -> int:
    app = QApplication(sys.argv)
    apply_theme(app)
    test_pan_precision(app)
    test_auto_fit(app)
    test_page_navigation(app)
    print()
    if FAILED:
        print(f"失败 {len(FAILED)} 项：" + ", ".join(FAILED))
        return 1
    print("视口/翻页/填充 全部通过")
    return 0


if __name__ == "__main__":
    sys.exit(main())
