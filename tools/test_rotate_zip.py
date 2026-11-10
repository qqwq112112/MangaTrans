# -*- coding: utf-8 -*-
"""Tests for region rotation, ZIP export, and button-label fitting.

Run: python tools/test_rotate_zip.py
"""

from __future__ import annotations

import os
import shutil
import sys
import zipfile
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import numpy as np  # noqa: E402
from PySide6.QtCore import QRectF  # noqa: E402
from PySide6.QtGui import QColor, QFontMetrics, QImage, QPainter  # noqa: E402
from PySide6.QtTest import QTest  # noqa: E402
from PySide6.QtWidgets import QApplication, QPushButton  # noqa: E402

from mangatrans.archive import load_input_images  # noqa: E402
from mangatrans.config import AppConfig  # noqa: E402
from mangatrans.document import Document, PageModel  # noqa: E402
from mangatrans.project_store import op_from_dict, op_to_dict  # noqa: E402
from mangatrans.region_dialog import RegionDialog  # noqa: E402
from mangatrans.textrender import RegionOp, draw_region  # noqa: E402
from mangatrans.theme import apply_theme  # noqa: E402
from mangatrans.viewer import RegionDraft  # noqa: E402

FAILED: list[str] = []


def check(name: str, cond: bool, detail: str = "") -> None:
    print(("  PASS  " if cond else "  FAIL  ") + name + (f" {detail}" if detail else ""))
    if not cond:
        FAILED.append(name)


def ink_bounds(rotation: float) -> tuple[int, tuple[int, int, int, int] | None]:
    """Render a wide bar and report its dark-pixel count and bounding box."""
    w = h = 600
    img = QImage(w, h, QImage.Format_ARGB32)
    img.fill(QColor("#FFFFFF"))
    op = RegionOp(rect=QRectF(0.3, 0.42, 0.4, 0.06),
                  fill_color=QColor("#000000"), text="", rotation=rotation)
    painter = QPainter(img)
    draw_region(painter, w, h, op)
    painter.end()

    arr = np.frombuffer(img.constBits(), dtype=np.uint8,
                        count=img.sizeInBytes()).reshape(
        h, img.bytesPerLine() // 4, 4)[:, :w, :3]
    mask = arr.mean(axis=2) < 100
    ys, xs = np.nonzero(mask)
    if len(xs) == 0:
        return 0, None
    return int(mask.sum()), (int(xs.min()), int(xs.max()),
                             int(ys.min()), int(ys.max()))


def test_rotation_render() -> None:
    print("[1] 旋转渲染")
    n0, b0 = ink_bounds(0)
    n90, b90 = ink_bounds(90)
    n45, b45 = ink_bounds(45)

    check("0° 有墨迹", n0 > 1000 and b0 is not None, str(n0))
    check("90° 有墨迹", n90 > 1000 and b90 is not None, str(n90))
    check("面积基本不变", abs(n0 - n90) / max(1, n0) < 0.05,
          f"{n0} vs {n90}")

    w0, h0 = b0[1] - b0[0], b0[3] - b0[2]
    w90, h90 = b90[1] - b90[0], b90[3] - b90[2]
    check("0° 是横向长条", w0 > h0 * 2, f"{w0}x{h0}")
    check("90° 是纵向长条", h90 > w90 * 2, f"{h90}x{w90}")
    check("旋转 90° 后宽高互换",
          abs(w0 - h90) <= 3 and abs(h0 - w90) <= 3, f"{w0}x{h0} vs {w90}x{h90}")
    check("45° 也是斜向（bbox 变方）",
          b45 is not None and (b45[1] - b45[0]) > w0 * 0.5,
          str(b45))


def test_rotation_serialization() -> None:
    print("[2] 旋转序列化")
    for angle in (0, 15, -90, 137.5):
        op = RegionOp(rect=QRectF(0, 0, 1, 1), rotation=float(angle))
        back = op_from_dict(op_to_dict(op))
        check(f"{angle:>6}° 往返", abs(back.rotation - angle) < 1e-9,
              str(back.rotation))
    check("旧存档默认 0°", op_from_dict({"rect": [0, 0, 1, 1]}).rotation == 0.0)
    src = RegionOp(rect=QRectF(0, 0, 1, 1), rotation=33.0)
    check("clone 保留角度", src.cloned().rotation == 33.0)


def test_rotation_ui(app) -> None:
    print("[3] 面板旋转控件")
    images, title = load_input_images(ROOT / "samples" / "sample_manga_ja.zip")
    doc = Document([PageModel(p) for p in images], None, title)
    dlg = RegionDialog(doc, [RegionDraft(0, QRectF(0.1, 0.1, 0.4, 0.3),
                                        doc.original_size(0))],
                       AppConfig(auto_ocr=False), None)
    dlg.show()
    app.processEvents()

    check("默认 0°", dlg.rotation_spin.value() == 0)
    dlg.rotation_spin.setValue(-30)
    app.processEvents()
    check("改角度写入 op", abs(dlg.states[0].op.rotation + 30) < 1e-9,
          str(dlg.states[0].op.rotation))
    check("滑块同步", dlg.rotation_slider.value() == -30,
          str(dlg.rotation_slider.value()))
    dlg._rotation_changed(0)
    check("可归零", dlg.states[0].op.rotation == 0.0)
    dlg.close()


def test_zip_export() -> None:
    print("[4] 整体导出 ZIP")
    images, title = load_input_images(ROOT / "samples" / "sample_manga_ja.zip")
    doc = Document([PageModel(p) for p in images], None, title)
    doc.add_op(0, RegionOp(rect=QRectF(0.1, 0.1, 0.4, 0.2),
                           fill_color=QColor("#FFFFFF"), text="压缩包测试"))

    out = ROOT / "samples" / "_zip_export.zip"
    out.unlink(missing_ok=True)
    progress: list[tuple] = []
    result = doc.export_zip(out, progress=lambda d, t, n: progress.append((d, t, n.name)))

    check("返回路径", result == out, str(result))
    check("文件存在且非空", out.exists() and out.stat().st_size > 5000,
          f"{out.stat().st_size if out.exists() else 0} B")
    check("进度回调完整",
          [p[0] for p in progress] == list(range(1, doc.page_count + 1)),
          str(progress))

    with zipfile.ZipFile(out) as zf:
        names = zf.namelist()
        check("条目数 = 页数", len(names) == doc.page_count, str(names))
        check("CRC 全部通过", zf.testzip() is None)
        check("文件名以 _zh 结尾", all("_zh" in n for n in names), str(names))
        check("无临时文件残留",
              not any(n.endswith((".tmp", ".part")) for n in names), str(names))

        data = zf.read(names[0])
        check("条目是有效 PNG", data[:8] == b"\x89PNG\r\n\x1a\n", str(data[:8]))

    check("没有遗留 .part 文件",
          not (out.with_suffix(out.suffix + ".part")).exists())
    out.unlink(missing_ok=True)


def test_zip_cancel_cleanup() -> None:
    print("[5] ZIP 导出失败不留残file")
    images, title = load_input_images(ROOT / "samples" / "sample_manga_ja.zip")
    doc = Document([PageModel(p) for p in images], None, title)
    out = ROOT / "samples" / "_zip_cancel.zip"
    out.unlink(missing_ok=True)

    def boom(done, total, name):
        raise RuntimeError("用户取消")

    try:
        doc.export_zip(out, progress=boom)
        check("应抛出", False)
    except RuntimeError:
        check("取消失败会抛出", True)
    check("没有半成品 zip", not out.exists())
    check("没有 .part 残留",
          not out.with_suffix(out.suffix + ".part").exists())


def test_buttons_fit(app) -> None:
    print("[6] 窄窗口下按钮文字不截断")
    from mangatrans.main_window import MainWindow

    win = MainWindow()
    win.show()
    QTest.qWait(250)

    def clipped() -> list[tuple]:
        bad = []
        for btn in win.findChildren(QPushButton):
            if not btn.text() or not btn.isVisible():
                continue
            fm = QFontMetrics(btn.font())
            need = fm.horizontalAdvance(btn.text()) + 22
            if btn.width() < need:
                bad.append((btn.text(), btn.width(), need))
        return bad

    for width in (1400, 1280, 1180):
        win.resize(width, 800)
        QTest.qWait(180)
        bad = clipped()
        check(f"{width}px 无截断", not bad, str(bad[:3]))

    win.close()

    print("[7] 翻译面板按钮不截断")
    images, title = load_input_images(ROOT / "samples" / "sample_manga_ja.zip")
    doc = Document([PageModel(p) for p in images], None, title)
    dlg = RegionDialog(doc, [RegionDraft(0, QRectF(0.1, 0.1, 0.4, 0.2),
                                        doc.original_size(0))],
                       AppConfig(auto_ocr=False), None)
    dlg.resize(dlg.minimumSize())
    dlg.show()
    app.processEvents()
    bad = []
    for btn in dlg.findChildren(QPushButton):
        if not btn.text() or not btn.isVisible():
            continue
        fm = QFontMetrics(btn.font())
        need = fm.horizontalAdvance(btn.text()) + 22
        if btn.width() < need:
            bad.append((btn.text(), btn.width(), need))
    check("面板按钮无截断", not bad, str(bad[:3]))
    dlg.close()


def main() -> int:
    app = QApplication(sys.argv)
    apply_theme(app)
    try:
        test_rotation_render()
        test_rotation_serialization()
        test_rotation_ui(app)
        test_zip_export()
        test_zip_cancel_cleanup()
        test_buttons_fit(app)
    finally:
        shutil.rmtree(ROOT / "samples" / "_zip_out", ignore_errors=True)

    print()
    if FAILED:
        print(f"失败 {len(FAILED)} 项：" + ", ".join(FAILED))
        return 1
    print("旋转/导出ZIP/按钮自适应 全部通过")
    return 0


if __name__ == "__main__":
    sys.exit(main())
