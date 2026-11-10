# -*- coding: utf-8 -*-
"""Tests for adjustable selection rects (需求2) and one-click apply (需求1).

Run: python tools/test_rect.py
"""

from __future__ import annotations

import os
import shutil
import sys
import tempfile
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from PySide6.QtCore import QPointF, QRectF  # noqa: E402
from PySide6.QtGui import QColor, QPixmap  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from mangatrans.archive import load_input_images  # noqa: E402
from mangatrans.config import AppConfig  # noqa: E402
from mangatrans.document import Document, PageModel  # noqa: E402
from mangatrans.region_dialog import RegionDialog  # noqa: E402
from mangatrans.textrender import RegionOp  # noqa: E402
from mangatrans.theme import apply_theme  # noqa: E402
from mangatrans.viewer import RegionDraft  # noqa: E402
from mangatrans.widgets import RegionPreview  # noqa: E402

FAILED: list[str] = []


def check(name: str, cond: bool, detail: str = "") -> None:
    print(("  PASS  " if cond else "  FAIL  ") + name + (f" {detail}" if detail else ""))
    if not cond:
        FAILED.append(name)


def make_doc() -> Document:
    images, title = load_input_images(ROOT / "samples" / "sample_manga_ja.zip")
    return Document([PageModel(p) for p in images], None, title)


def test_drag_math() -> None:
    print("[1] 拖拽数学与边界钳制")
    base = QRectF(0.2, 0.2, 0.4, 0.3)
    drag = RegionPreview._apply_drag

    r = drag(base, 0.1, 0.1, "move")
    check("移动", abs(r.x() - 0.3) < 1e-9 and abs(r.y() - 0.3) < 1e-9, str(r))
    r = drag(base, -0.9, -0.9, "move")
    check("移动撞左上界", r.x() == 0.0 and r.y() == 0.0, str(r))
    r = drag(base, 0.9, 0.9, "move")
    check("移动撞右下界", abs(r.x() + r.width() - 1.0) < 1e-9, str(r))

    r = drag(base, -0.1, 0, "l")
    check("拖左边扩大", abs(r.x() - 0.1) < 1e-9 and abs(r.width() - 0.5) < 1e-9, str(r))
    r = drag(base, 0.1, 0, "r")
    check("拖右边扩大", abs(r.width() - 0.5) < 1e-9, str(r))
    r = drag(base, 0, 0.1, "t")
    check("拖上边缩小", abs(r.y() - 0.3) < 1e-9, str(r))
    r = drag(base, 0, -0.1, "t")
    check("拖上边扩大", abs(r.y() - 0.1) < 1e-9 and abs(r.height() - 0.4) < 1e-9, str(r))

    r = drag(base, -0.9, 0, "r")
    check("拖过头保底最小尺寸", r.width() >= 0.011, str(r.width()))
    r = drag(base, 5.0, 5.0, "br")
    check("拖过界不超页面", r.x() + r.width() <= 1.0 + 1e-9, str(r))


def test_dialog_two_way_sync() -> None:
    print("[2] 数值框 ↔ 拖拽双向同步")
    doc = make_doc()
    draft = RegionDraft(0, QRectF(0.2, 0.2, 0.4, 0.3), doc.original_size(0))
    dlg = RegionDialog(doc, [draft], AppConfig(auto_ocr=False), None)
    dlg.resize(1200, 820)
    dlg.show()
    QApplication.processEvents()

    values = {k: round(s.value(), 1) for k, s in dlg._rect_spins.items()}
    check("初始值与选区一致",
          values == {"x": 20.0, "y": 20.0, "w": 40.0, "h": 30.0}, str(values))

    dlg._rect_spins["x"].setValue(30.0)
    QApplication.processEvents()
    check("改左值 → op.rect", abs(dlg.states[0].op.rect.x() - 0.3) < 1e-9,
          str(dlg.states[0].op.rect.x()))

    dlg._rect_spins["w"].setValue(55.0)
    QApplication.processEvents()
    check("改宽值 → op.rect", abs(dlg.states[0].op.rect.width() - 0.55) < 1e-9,
          str(dlg.states[0].op.rect.width()))

    new_rect = QRectF(0.1, 0.15, 0.6, 0.2)
    dlg._rect_committed(new_rect)
    QApplication.processEvents()
    values = {k: round(s.value(), 1) for k, s in dlg._rect_spins.items()}
    check("拖拽 → 数值框更新",
          values == {"x": 10.0, "y": 15.0, "w": 60.0, "h": 20.0}, str(values))
    check("拖拽 → op.rect 更新",
          abs(dlg.states[0].op.rect.width() - 0.6) < 1e-9)

    dlg._rect_spins["x"].setValue(95.0)
    QApplication.processEvents()
    r = dlg.states[0].op.rect
    check("越界自动收窄", r.x() + r.width() <= 1.0 + 1e-9,
          f"{r.x():.2f}+{r.width():.2f}")
    dlg.close()


def test_resize_after_applied() -> None:
    """The core of 需求2: change the size of an ALREADY written region."""
    print("[3] 已覆写区域改大小后重新渲染")
    doc = make_doc()
    original = RegionOp(
        rect=QRectF(0.20, 0.20, 0.35, 0.18),
        fill_color=QColor("#FFFFFF"),
        text="等等一下！",
        font_family="Noto Sans SC",
        auto_fit=True,
        fill_shape="ellipse",
    )
    doc.add_op(0, original)
    before = doc.pages[0].full_image()
    old_rect = QRectF(original.rect)

    # Right-click path: reopen the dialog with the existing op as preset.
    draft = RegionDraft(0, QRectF(old_rect), doc.original_size(0))
    dlg = RegionDialog(doc, [draft], AppConfig(auto_ocr=False), None,
                       preset_ops=[original])
    dlg.resize(1200, 820)
    dlg.show()
    QApplication.processEvents()

    check("编辑模式打开", dlg.preset_mode)
    check("预设内容载入", dlg.states[0].op.text == "等等一下！",
          dlg.states[0].op.text)
    check("预设形状保留", dlg.states[0].op.fill_shape == "ellipse")

    # Enlarge it substantially.
    bigger = QRectF(0.10, 0.12, 0.62, 0.32)
    dlg._rect_committed(bigger)
    QApplication.processEvents()
    ops = dlg.result_ops()
    check("调整后仍在结果里", len(ops) == 1, str(len(ops)))
    check("新尺寸生效", abs(ops[0][1].rect.width() - 0.62) < 1e-9,
          str(ops[0][1].rect.width()))
    check("译文未丢", ops[0][1].text == "等等一下！")

    # Apply back to the page the way main_window does.
    doc.pages[0].replace_op(0, ops[0][1])
    doc.pages[0].invalidate()
    after = doc.pages[0].full_image()
    dlg.close()

    check("页面已重绘", after.size() == before.size(), str(after.size()))
    w, h = after.width(), after.height()
    # New area should be white-ish where the enlarged fill landed; the old
    # band outside it must have gone back to the original artwork.
    px_new = after.pixelColor(int(0.60 * w), int(0.38 * h))
    check("新区域内已覆盖", px_new.red() > 200 and px_new.green() > 200,
          px_new.name())
    px_outside = after.pixelColor(int(0.05 * w), int(0.05 * h))
    check("新区域外仍是原图", px_outside.name() != "#ffffff", px_outside.name())


def test_preview_hit_testing() -> None:
    print("[4] 手柄命中判定")
    preview = RegionPreview()
    preview.resize(600, 500)
    pix = QPixmap(1000, 1400)
    pix.fill(QColor("#FFFFFF"))
    op = RegionOp(rect=QRectF(0.3, 0.3, 0.4, 0.4), text="测试")
    preview.set_scene(pix, op)
    box = QRectF(100, 100, 200, 200)

    check("角点 = tl", preview._hit(box, QPointF(101, 101)) == "tl")
    check("角点 = br", preview._hit(box, QPointF(299, 299)) == "br")
    check("边中点 = t", preview._hit(box, QPointF(200, 101)) == "t")
    check("边中点 = l", preview._hit(box, QPointF(101, 200)) == "l")
    check("内部 = move", preview._hit(box, QPointF(200, 200)) == "move")
    check("外部 = None", preview._hit(box, QPointF(400, 400)) is None)


def main() -> int:
    app = QApplication(sys.argv)
    apply_theme(app)
    tmp = Path(tempfile.mkdtemp(prefix="mgt_rect_"))
    try:
        test_drag_math()
        test_dialog_two_way_sync()
        test_resize_after_applied()
        test_preview_hit_testing()
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
        del app

    print()
    if FAILED:
        print(f"失败 {len(FAILED)} 项：" + ", ".join(FAILED))
        return 1
    print("选区调整全部通过")
    return 0


if __name__ == "__main__":
    sys.exit(main())
