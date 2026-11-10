# -*- coding: utf-8 -*-
"""Tests for page navigation consistency (arrows / slider / spin box).

Regression target: clicking 上一页/下一页 or dragging the slider jumped to the
last page. Two root causes were fixed:
  1. vertical mode assigned scene units to scrollbar (viewport) pixels;
  2. setRange() on document load clamped the old value and fired valueChanged.
Run: python tools/test_navigation.py
"""

from __future__ import annotations

import io
import os
import shutil
import sys
import zipfile
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from PySide6.QtCore import QPointF  # noqa: E402
from PySide6.QtTest import QTest  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from mangatrans.theme import apply_theme  # noqa: E402

FAILED: list[str] = []
PAGES = 12


def check(name: str, cond: bool, detail: str = "") -> None:
    print(("  PASS  " if cond else "  FAIL  ") + name + (f" {detail}" if detail else ""))
    if not cond:
        FAILED.append(name)


def make_archive(path: Path, pages: int = PAGES) -> None:
    """Build a simple multipage zip (needs Pillow only)."""
    from PIL import Image, ImageDraw

    path.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(path, "w") as zf:
        for i in range(1, pages + 1):
            img = Image.new("RGB", (800, 1200), "white")
            d = ImageDraw.Draw(img)
            d.rectangle((20, 20, 780, 1180), outline="black", width=4)
            d.text((300, 560), f"page {i}", fill="black")
            buf = io.BytesIO()
            img.save(buf, "JPEG", quality=80)
            zf.writestr(f"p{i:02d}.jpg", buf.getvalue())


def new_window(app, path: Path, restore: bool = False):
    from mangatrans.main_window import MainWindow

    win = MainWindow()
    win.resize(1200, 800)
    win.show()
    win.open_path(path, restore=restore)
    QTest.qWait(400)
    return win


def state(win) -> tuple[int, int, int]:
    return (win.canvas.current, win.page_spin.value(), win.page_slider.value())


def consistent(win) -> bool:
    """current (0-based) must match spin (1-based) and slider (0-based)."""
    cur, spin, slider = state(win)
    return spin == cur + 1 and slider == cur


def test_arrows(app, win) -> None:
    print("[1] 上下页按钮（两种模式）")
    for mode in ("horizontal", "vertical"):
        win._set_mode(mode)
        QTest.qWait(250)
        win.canvas.go_to_page(0)
        QTest.qWait(250)
        ok = True
        for expected in range(1, 6):
            win.btn_next.click()
            QTest.qWait(220)
            if win.canvas.current != expected or not consistent(win):
                ok = False
                break
        check(f"{mode} 下一页逐步前进", ok, f"current={win.canvas.current}")

        ok = True
        for expected in range(4, -1, -1):
            win.btn_prev.click()
            QTest.qWait(220)
            if win.canvas.current != expected or not consistent(win):
                ok = False
                break
        check(f"{mode} 上一页逐步后退", ok, f"current={win.canvas.current}")

        # Clamping at both ends must not overshoot.
        win.canvas.go_to_page(0)
        QTest.qWait(200)
        win.btn_prev.click()
        QTest.qWait(200)
        check(f"{mode} 第一页再按上一页不变", win.canvas.current == 0,
              str(win.canvas.current))
        win.canvas.go_to_page(PAGES - 1)
        QTest.qWait(220)
        win.btn_next.click()
        QTest.qWait(220)
        check(f"{mode} 最后一页再按下一页不变", win.canvas.current == PAGES - 1,
              str(win.canvas.current))


def test_slider(app, win) -> None:
    print("[2] 拖动进度条")
    for mode in ("horizontal", "vertical"):
        win._set_mode(mode)
        QTest.qWait(250)
        ok = True
        for target in (5, 11, 2, 8, 0):
            win.page_slider.setValue(target)
            QTest.qWait(240)
            if win.canvas.current != target or not consistent(win):
                ok = False
                break
        check(f"{mode} 滑块跳转准确", ok,
              f"target={target} current={win.canvas.current}")
        check(f"{mode} 滑块后无跳末尾", win.canvas.current != PAGES - 1 or target == PAGES - 1,
              str(win.canvas.current))


def test_spin(app, win) -> None:
    print("[3] 输入页码")
    for mode in ("horizontal", "vertical"):
        win._set_mode(mode)
        QTest.qWait(250)
        ok = True
        for target in (3, 12, 7, 1):
            win.page_spin.setValue(target)
            QTest.qWait(240)
            if win.canvas.current != target - 1 or not consistent(win):
                ok = False
                break
        check(f"{mode} 页码框跳转准确", ok,
              f"target={target} current={win.canvas.current}")


def test_zoom_levels(app, win) -> None:
    print("[4] 不同缩放下仍准确（滚动单位回归）")
    for mode in ("horizontal", "vertical"):
        win._set_mode(mode)
        QTest.qWait(250)
        for label, zoom in (("适应窗口", "page"), ("适应宽度", "width"),
                            ("3x", 3.0)):
            win.canvas._fit_mode = None
            if zoom == "page":
                win.canvas.fit_page()
            elif zoom == "width":
                win.canvas.fit_width()
            else:
                win.canvas._set_scale(zoom)
            QTest.qWait(250)
            win.canvas.go_to_page(0)
            QTest.qWait(250)
            ok = True
            for target in (4, 10, 2):
                win.page_spin.setValue(target)
                QTest.qWait(240)
                if win.canvas.current != target - 1 or not consistent(win):
                    ok = False
                    break
            check(f"{mode} @{label} 跳转准确", ok,
                  f"current={win.canvas.current}")


def test_document_switch_no_jump(app) -> None:
    print("[5] 换文档不跳最后页（setRange 回归）")
    big = ROOT / "samples" / "_nav_big.zip"
    small = ROOT / "samples" / "_nav_small.zip"
    make_archive(big, 12)
    make_archive(small, 3)
    win = new_window(app, big)
    try:
        win.canvas.go_to_page(10)
        QTest.qWait(250)
        check("大文档跳到第 11 页", win.canvas.current == 10,
              str(win.canvas.current))

        win.open_path(small, restore=False)
        QTest.qWait(400)
        check("换小文档回到第 1 页", win.canvas.current == 0,
              str(win.canvas.current))
        check("页码框重置为 1", win.page_spin.value() == 1,
              str(win.page_spin.value()))
        check("滑块重置为 0", win.page_slider.value() == 0,
              str(win.page_slider.value()))
        check("范围已更新", win.page_spin.maximum() == 3,
              str(win.page_spin.maximum()))

        # Reverse direction: small -> big must not jump either.
        win.open_path(big, restore=False)
        QTest.qWait(400)
        check("换回大文档仍在第 1 页", win.canvas.current == 0,
              str(win.canvas.current))
    finally:
        win.close()
        big.unlink(missing_ok=True)
        small.unlink(missing_ok=True)


def test_vertical_scroll_units(app) -> None:
    print("[6] 竖排滚动定位使用设备像素")
    win = new_window(app, ROOT / "samples" / "sample_manga_ja.zip")
    try:
        win._set_mode("vertical")
        QTest.qWait(300)
        win.canvas._fit_mode = None
        win.canvas._set_scale(2.0)
        QTest.qWait(250)
        win.canvas.go_to_page(1)
        QTest.qWait(300)

        item = win.canvas._items[1]
        vbar = win.canvas.verticalScrollBar()
        # The page's top must be near the viewport top after the jump.
        top_in_view = win.canvas.mapFromScene(QPointF(0, item.sceneBoundingRect().top())).y()
        check("第 2 页顶部对齐视口", abs(top_in_view) <= 6, f"offset={top_in_view}")
        check("滚动条确实移动了", vbar.value() > 0, str(vbar.value()))
        check("当前页正确", win.canvas.current == 1, str(win.canvas.current))
    finally:
        win.close()


def main() -> int:
    app = QApplication(sys.argv)
    apply_theme(app)
    nav = ROOT / "samples" / "_nav_pages.zip"
    make_archive(nav)
    win = new_window(app, nav)
    try:
        check("页数正确", win.doc.page_count == PAGES, str(win.doc.page_count))
        test_arrows(app, win)
        test_slider(app, win)
        test_spin(app, win)
        test_zoom_levels(app, win)
    finally:
        win.close()
        nav.unlink(missing_ok=True)

    test_document_switch_no_jump(app)
    test_vertical_scroll_units(app)

    shutil.rmtree(ROOT / "samples" / "_nav_out", ignore_errors=True)
    print()
    if FAILED:
        print(f"失败 {len(FAILED)} 项：" + ", ".join(FAILED))
        return 1
    print("翻页一致性全部通过")
    return 0


if __name__ == "__main__":
    sys.exit(main())
