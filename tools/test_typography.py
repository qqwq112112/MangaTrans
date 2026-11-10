# -*- coding: utf-8 -*-
"""Tests for typography that follows the selection size (需求2 follow-up).

The question being answered: when the selection is resized, does the text
rescale *including* letter spacing, line spacing, column spacing and padding?

Run: python tools/test_typography.py
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from PySide6.QtCore import QRectF  # noqa: E402
from PySide6.QtGui import QColor, QImage, QPainter  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from mangatrans.project_store import op_from_dict, op_to_dict  # noqa: E402
from mangatrans.region_dialog import RegionDialog  # noqa: E402
from mangatrans.config import AppConfig  # noqa: E402
from mangatrans.textrender import (  # noqa: E402
    RegionOp,
    draw_region,
    fit_font_size,
    text_bounds,
    typing_metrics,
)
from mangatrans.theme import apply_theme  # noqa: E402
from mangatrans.viewer import RegionDraft  # noqa: E402

FAILED: list[str] = []
PAGE_W, PAGE_H = 1000, 1450
TEXT = "今天天气真不错。要不要一起出去？"


def check(name: str, cond: bool, detail: str = "") -> None:
    print(("  PASS  " if cond else "  FAIL  ") + name + (f" {detail}" if detail else ""))
    if not cond:
        FAILED.append(name)


def make_op(rect: QRectF, **kw) -> RegionOp:
    base = dict(
        rect=rect, fill_color=QColor("#FFFFFF"), text=TEXT,
        font_family="Noto Sans SC", auto_fit=True, padding=0.06,
        letter_spacing=0.10, line_spacing=1.12,
    )
    base.update(kw)
    return RegionOp(**base)


def measure(op: RegionOp):
    """Return (size, metrics) for the op's actual box."""
    rect = QRectF(op.rect.x() * PAGE_W, op.rect.y() * PAGE_H,
                  op.rect.width() * PAGE_W, op.rect.height() * PAGE_H)
    inner = text_bounds(rect, op)
    size = fit_font_size(op, inner)
    return size, typing_metrics(op, size, inner), inner


def test_horizontal_scaling() -> None:
    print("[1] 横排：框变大 → 字号/字距/行距/边距 全部等比放大")
    small = measure(make_op(QRectF(0.10, 0.10, 0.35, 0.25)))
    large = measure(make_op(QRectF(0.10, 0.10, 0.70, 0.50)))

    s_size, s_m, s_inner = small
    l_size, l_m, l_inner = large
    print(f"      小框 字号 {s_size} 字距 {s_m['letter_px']:.1f} 行距 {s_m['line_pitch_px']:.1f}")
    print(f"      大框 字号 {l_size} 字距 {l_m['letter_px']:.1f} 行距 {l_m['line_pitch_px']:.1f}")

    check("字号随框增大", l_size > s_size, f"{s_size} -> {l_size}")
    check("行距随框增大", l_m["line_pitch_px"] > s_m["line_pitch_px"],
          f"{s_m['line_pitch_px']:.1f} -> {l_m['line_pitch_px']:.1f}")
    check("字间距随框增大", l_m["letter_px"] > s_m["letter_px"],
          f"{s_m['letter_px']:.1f} -> {l_m['letter_px']:.1f}")
    check("边界内缩随框增大", l_inner.width() > s_inner.width())


def test_proportional_all_ratios() -> None:
    print("[2] 各项间距严格随字号比例变化（不是随机缩放）")
    # letter_spacing is a ratio of the font size, so px/size must be constant.
    ratios = []
    for fw, fh in ((0.30, 0.20), (0.45, 0.30), (0.65, 0.45)):
        size, m, _inner = measure(make_op(QRectF(0.1, 0.1, fw, fh)))
        ratios.append(m["letter_px"] / size)
    spread = max(ratios) - min(ratios)
    check("字距/字号 比例恒定", spread < 0.01,
          ", ".join(f"{r:.4f}" for r in ratios))


def test_vertical_layout() -> None:
    print("[3] 竖排：列距随框变化，且从右往左排")
    op_small = make_op(QRectF(0.10, 0.10, 0.35, 0.25), vertical=True,
                       column_gap=0.6, letter_spacing=0.05)
    op_large = make_op(QRectF(0.05, 0.05, 0.85, 0.70), vertical=True,
                       column_gap=0.6, letter_spacing=0.05)

    s_size, s_m, _ = measure(op_small)
    l_size, l_m, _ = measure(op_large)
    print(f"      小框 字号 {s_size} 列距 {s_m['column_gap_px']:.1f} 列数 {s_m['columns']}")
    print(f"      大框 字号 {l_size} 列距 {l_m['column_gap_px']:.1f} 列数 {l_m['columns']}")

    check("竖排字号随框增大", l_size > s_size, f"{s_size} -> {l_size}")
    check("列间距随框增大", l_m["column_gap_px"] > s_m["column_gap_px"],
          f"{s_m['column_gap_px']:.1f} -> {l_m['column_gap_px']:.1f}")
    check("竖排有多列", s_m["columns"] > 1, str(s_m["columns"]))
    check("列距/字号 比例恒定",
          abs(s_m["column_gap_px"] / s_size - l_m["column_gap_px"] / l_size) < 0.02,
          f"{s_m['column_gap_px']/s_size:.3f} vs {l_m['column_gap_px']/l_size:.3f}")


def test_vertical_renders_right_to_left() -> None:
    print("[4] 竖排绘制：首列在右、字符自上而下")
    img = QImage(PAGE_W, PAGE_H, QImage.Format_ARGB32)
    img.fill(QColor("#FFFFFF"))

    op = RegionOp(rect=QRectF(0.10, 0.10, 0.80, 0.70),
                  fill_color=QColor("#FFFFFF"), text="あいうえおかきくけこ",
                  font_family="Noto Sans SC", auto_fit=True, padding=0.02,
                  vertical=True, letter_spacing=0.0, column_gap=0.4)
    painter = QPainter(img)
    draw_region(painter, PAGE_W, PAGE_H, op)
    painter.end()

    import numpy as np
    arr = np.frombuffer(img.constBits(), dtype=np.uint8,
                        count=img.sizeInBytes()).reshape(
        PAGE_H, img.bytesPerLine() // 4, 4)[:, :PAGE_W, :3]
    dark = arr.mean(axis=2) < 100
    ys, xs = np.nonzero(dark)
    check("画面有字", len(xs) > 200, f"pixels={len(xs)}")
    if len(xs):
        # Ink must sit inside the box (with a little slack for antialiasing).
        x0, x1 = 0.10 * PAGE_W - 4, 0.90 * PAGE_W + 4
        y0, y1 = 0.10 * PAGE_H - 4, 0.80 * PAGE_H + 4
        check("墨迹在框内",
              xs.min() >= x0 and xs.max() <= x1 and ys.min() >= y0 and ys.max() <= y1,
              f"x {xs.min()}-{xs.max()} y {ys.min()}-{ys.max()}")


def test_serialization_roundtrip() -> None:
    print("[5] 新字段的断点记忆往返")
    op = make_op(QRectF(0.1, 0.2, 0.5, 0.3), vertical=True,
                 letter_spacing=0.12, column_gap=0.75)
    back = op_from_dict(op_to_dict(op))
    check("字间距保留", abs(back.letter_spacing - 0.12) < 1e-9, str(back.letter_spacing))
    check("列间距保留", abs(back.column_gap - 0.75) < 1e-9, str(back.column_gap))
    check("竖排保留", back.vertical is True)
    # Old saved files have none of these keys; they must still load.
    legacy = {"rect": [0.1, 0.1, 0.4, 0.2], "text": "旧数据"}
    old = op_from_dict(legacy)
    check("旧存档兼容", old.letter_spacing == 0.0 and old.vertical is False)


def test_dialog_controls(app) -> None:
    print("[6] 面板控件联动")
    from mangatrans.archive import load_input_images
    from mangatrans.document import Document, PageModel

    images, title = load_input_images(ROOT / "samples" / "sample_manga_ja.zip")
    doc = Document([PageModel(p) for p in images], None, title)
    dlg = RegionDialog(doc, [RegionDraft(0, QRectF(0.1, 0.1, 0.4, 0.3),
                                        doc.original_size(0))],
                       AppConfig(auto_ocr=False), None)
    dlg.show()
    app.processEvents()
    dlg.translated_edit.setPlainText(TEXT)
    app.processEvents()

    check("初始有读数", "字号" in dlg.metrics_label.text(), dlg.metrics_label.text()[:40])

    before = dlg.metrics_label.text()
    dlg.letter_spin.setValue(0.15)
    app.processEvents()
    check("改字间距 → op 更新", abs(dlg.states[0].op.letter_spacing - 0.15) < 1e-9)
    check("改字间距 → 读数变化", dlg.metrics_label.text() != before)

    dlg._set_layout_direction(True)
    app.processEvents()
    check("切竖排 → op.vertical", dlg.states[0].op.vertical is True)
    check("竖排时列间距可用", dlg.colgap_spin.isEnabled())
    check("竖排读数含列距", "列距" in dlg.metrics_label.text(),
          dlg.metrics_label.text()[:50])

    dlg._set_layout_direction(False)
    app.processEvents()
    check("切回横排 → 列间距禁用", not dlg.colgap_spin.isEnabled())
    check("横排读数含行距", "行距" in dlg.metrics_label.text())

    dlg.close()


def main() -> int:
    app = QApplication(sys.argv)
    apply_theme(app)
    test_horizontal_scaling()
    test_proportional_all_ratios()
    test_vertical_layout()
    test_vertical_renders_right_to_left()
    test_serialization_roundtrip()
    test_dialog_controls(app)
    print()
    if FAILED:
        print(f"失败 {len(FAILED)} 项：" + ", ".join(FAILED))
        return 1
    print("排版随选区缩放全部通过")
    return 0


if __name__ == "__main__":
    sys.exit(main())
