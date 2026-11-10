# -*- coding: utf-8 -*-
"""Tests for fill shapes, freehand strokes, and the model badge.

Run: python tools/test_shapes.py
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import numpy as np  # noqa: E402
from PySide6.QtCore import QRectF  # noqa: E402
from PySide6.QtGui import QColor, QImage, QPainter  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from mangatrans import lmstudio  # noqa: E402
from mangatrans.archive import load_input_images  # noqa: E402
from mangatrans.config import AppConfig  # noqa: E402
from mangatrans.document import Document, PageModel  # noqa: E402
from mangatrans.project_store import op_from_dict, op_to_dict  # noqa: E402
from mangatrans.region_dialog import RegionDialog  # noqa: E402
from mangatrans.textrender import RegionOp, draw_region, shape_path  # noqa: E402
from mangatrans.theme import apply_theme  # noqa: E402
from mangatrans.viewer import RegionDraft  # noqa: E402

FAILED: list[str] = []
W, H = 800, 1000


def check(name: str, cond: bool, detail: str = "") -> None:
    print(("  PASS  " if cond else "  FAIL  ") + name + (f" {detail}" if detail else ""))
    if not cond:
        FAILED.append(name)


def render(op: RegionOp) -> np.ndarray:
    img = QImage(W, H, QImage.Format_ARGB32)
    img.fill(QColor("#EEEEEE"))
    painter = QPainter(img)
    draw_region(painter, W, H, op)
    painter.end()
    # QImage Format_ARGB32 is stored as BGRA in memory, so channel 2 is red.
    arr = np.frombuffer(img.constBits(), dtype=np.uint8,
                        count=img.sizeInBytes()).reshape(
        H, img.bytesPerLine() // 4, 4)[:, :W, :]
    return arr.copy()


def filled_ratio(arr: np.ndarray, op: RegionOp) -> float:
    """Fraction of the selection rect painted in the fill colour."""
    x0, y0 = int(op.rect.x() * W), int(op.rect.y() * H)
    x1, y1 = int((op.rect.x() + op.rect.width()) * W), int((op.rect.y() + op.rect.height()) * H)
    crop = arr[y0:y1, x0:x1]
    if crop.size == 0:
        return 0.0
    # BGRA: index 2 = red, 1 = green, 0 = blue.
    red = (crop[:, :, 2] > 200) & (crop[:, :, 1] < 100) & (crop[:, :, 0] < 100)
    return float(red.mean())


def test_shapes() -> None:
    print("[1] 五种填充形状")
    base = dict(rect=QRectF(0.2, 0.2, 0.4, 0.2), fill_color=QColor("#FF0000"))

    rect_ratio = filled_ratio(render(RegionOp(**base, fill_shape="rect")),
                              RegionOp(**base))
    check("方形几乎填满", rect_ratio > 0.95, f"{rect_ratio:.2f}")

    none_ratio = filled_ratio(render(RegionOp(**base, fill_shape="none")),
                              RegionOp(**base))
    check("不填充 = 0", none_ratio < 0.01, f"{none_ratio:.2f}")

    ell_ratio = filled_ratio(render(RegionOp(**base, fill_shape="ellipse")),
                             RegionOp(**base))
    check("椭圆面积约 π/4", 0.70 < ell_ratio < 0.85, f"{ell_ratio:.2f}")
    check("椭圆小于方形", ell_ratio < rect_ratio)

    round_ratio = filled_ratio(render(RegionOp(**base, fill_shape="rounded",
                                               corner_radius=0.5)),
                               RegionOp(**base))
    check("大圆角面积下降", round_ratio < rect_ratio, f"{round_ratio:.2f}")
    check("大圆角仍接近满", round_ratio > 0.85, f"{round_ratio:.2f}")

    poly = RegionOp(**base, fill_shape="polygon",
                    fill_polygon=[(0.2, 0.2), (0.6, 0.2), (0.6, 0.3),
                                  (0.3, 0.4), (0.2, 0.4)])
    poly_ratio = filled_ratio(render(poly), poly)
    check("多边形有填充", poly_ratio > 0.3, f"{poly_ratio:.2f}")
    check("多边形未填满矩形", poly_ratio < 0.9, f"{poly_ratio:.2f}")

    print("[2] shape_path 计算")
    r = QRectF(160, 200, 320, 200)
    for shape in ("rect", "rounded", "ellipse"):
        op = RegionOp(rect=QRectF(0.2, 0.2, 0.4, 0.2), fill_shape=shape)
        check(f"{shape} 路径非空", not shape_path(op, r).isEmpty())
    empty = RegionOp(rect=QRectF(0.2, 0.2, 0.4, 0.2), fill_shape="none")
    check("none 路径为空", shape_path(empty, r).isEmpty())
    poly2 = RegionOp(rect=QRectF(0.2, 0.2, 0.4, 0.2), fill_shape="polygon",
                     fill_polygon=[(0.2, 0.2), (0.6, 0.2), (0.4, 0.4)])
    check("多边形路径非空", not shape_path(poly2, r).isEmpty())
    bad = RegionOp(rect=QRectF(0.2, 0.2, 0.4, 0.2), fill_shape="polygon",
                   fill_polygon=[(0.2, 0.2)])
    check("少于3点回退方形", not shape_path(bad, r).isEmpty())


def test_strokes() -> None:
    print("[3] 涂鸦笔迹")
    op = RegionOp(rect=QRectF(0.2, 0.2, 0.4, 0.3), fill_color=QColor("#EEEEEE"),
                  text="", fill_shape="rect")
    plain = render(op)
    count_before = int((plain[:, :, :3].mean(axis=2) < 200).sum())

    op.strokes = [{
        "points": [[0.25, 0.25], [0.30, 0.28], [0.35, 0.25]],
        "color": [0, 0, 0, 255],
        "width": 0.01,
    }]
    drawn = render(op)
    count_after = int((drawn[:, :, :3].mean(axis=2) < 200).sum())
    check("涂鸦产生暗像素", count_after > count_before + 100,
          f"{count_before} -> {count_after}")

    # A stroke in the fill colour must be invisible over the fill (that is how
    # users erase leftover text: paint it with the background colour).
    op.fill_color = QColor("#000000")
    op.strokes = [{"points": [[0.25, 0.25], [0.35, 0.25]],
                   "color": [0, 0, 0, 255], "width": 0.01}]
    arr = render(op)
    base = render(RegionOp(rect=op.rect, fill_color=QColor("#000000"),
                           text="", fill_shape="rect"))
    check("同色涂鸦不改变外观",
          int((arr[:, :, :3].mean(axis=2) < 200).sum())
          == int((base[:, :, :3].mean(axis=2) < 200).sum()))

    print("[4] 涂鸦锚定在页面坐标（改选区大小不移位）")
    # Strokes are stored in PAGE coordinates, so enlarging the selection must
    # leave the ink exactly where it was on the page - it should not stretch.
    small = RegionOp(rect=QRectF(0.2, 0.2, 0.2, 0.15), text="",
                     strokes=[{"points": [[0.25, 0.25], [0.30, 0.30]],
                               "color": [0, 0, 0, 255], "width": 0.01}])
    large = RegionOp(rect=QRectF(0.2, 0.2, 0.4, 0.30), text="",
                     strokes=[{"points": [[0.25, 0.25], [0.30, 0.30]],
                               "color": [0, 0, 0, 255], "width": 0.01}])
    s_arr = render(small)[:, :, :3].mean(axis=2) < 200
    l_arr = render(large)[:, :, :3].mean(axis=2) < 200
    s_ys, s_xs = np.nonzero(s_arr)
    l_ys, l_xs = np.nonzero(l_arr)
    check("两种选区下笔迹都存在", len(s_xs) > 100 and len(l_xs) > 100,
          f"{len(s_xs)} / {len(l_xs)}")
    # Ink location only depends on page coordinates, so the extents must match.
    check("笔迹位置不随选区漂移",
          abs(int(s_xs.mean()) - int(l_xs.mean())) <= 2
          and abs(int(s_ys.mean()) - int(l_ys.mean())) <= 2,
          f"({int(s_xs.mean())},{int(s_ys.mean())}) vs "
          f"({int(l_xs.mean())},{int(l_ys.mean())})")


def test_serialization() -> None:
    print("[5] 新字段序列化")
    op = RegionOp(rect=QRectF(0.1, 0.2, 0.5, 0.3), fill_shape="polygon",
                  corner_radius=0.34,
                  fill_polygon=[(0.1, 0.1), (0.5, 0.2), (0.4, 0.6)],
                  strokes=[{"points": [[0.1, 0.1], [0.2, 0.2]],
                            "color": [10, 20, 30, 255], "width": 0.012}])
    back = op_from_dict(op_to_dict(op))
    check("形状保留", back.fill_shape == "polygon", back.fill_shape)
    check("圆角保留", abs(back.corner_radius - 0.34) < 1e-9, str(back.corner_radius))
    check("多边形保留", len(back.fill_polygon) == 3, str(len(back.fill_polygon)))
    check("笔迹保留", len(back.strokes) == 1, str(len(back.strokes)))
    check("笔迹颜色保留", back.strokes[0]["color"] == [10, 20, 30, 255],
          str(back.strokes[0]["color"]))
    check("旧存档兼容", op_from_dict({"rect": [0, 0, 1, 1]}).fill_shape == "rect")
    check("脏笔迹被丢弃",
          len(op_from_dict({"rect": [0, 0, 1, 1],
                            "strokes": [None, 5, {"nope": 1}]}).strokes) == 0)


def test_dialog_controls(app) -> None:
    print("[6] 面板控件")
    images, title = load_input_images(ROOT / "samples" / "sample_manga_ja.zip")
    doc = Document([PageModel(p) for p in images], None, title)
    dlg = RegionDialog(doc, [RegionDraft(0, QRectF(0.1, 0.1, 0.4, 0.3),
                                        doc.original_size(0))],
                       AppConfig(auto_ocr=False), None)
    dlg.show()
    app.processEvents()

    shapes = [dlg.shape_combo.itemData(i) for i in range(dlg.shape_combo.count())]
    check("形状选项齐全",
          shapes == ["rect", "rounded", "ellipse", "polygon", "none"], str(shapes))

    idx = dlg.shape_combo.findData("rounded")
    dlg.shape_combo.setCurrentIndex(idx)
    app.processEvents()
    check("圆角可选", dlg.corner_spin.isEnabled())
    check("op 记录圆角形状", dlg.states[0].op.fill_shape == "rounded")

    idx = dlg.shape_combo.findData("rect")
    dlg.shape_combo.setCurrentIndex(idx)
    app.processEvents()
    check("非圆角时禁用圆角输入", not dlg.corner_spin.isEnabled())

    # Brush mode
    dlg.btn_brush.setChecked(True)
    app.processEvents()
    check("画笔开启进入涂鸦模式", dlg.preview.mode == dlg.preview.MODE_BRUSH,
          dlg.preview.mode)

    dlg.states[0].op.strokes = [{"points": [[0.1, 0.1], [0.2, 0.2]],
                                 "color": [0, 0, 0, 255], "width": 0.01}]
    dlg._clear_strokes()
    app.processEvents()
    check("清空涂鸦", not dlg.states[0].op.strokes)

    dlg.btn_brush.setChecked(False)
    app.processEvents()
    check("关闭画笔回到矩形模式", dlg.preview.mode == dlg.preview.MODE_RECT)

    # Polygon mode follows the shape choice.
    idx = dlg.shape_combo.findData("polygon")
    dlg.shape_combo.setCurrentIndex(idx)
    app.processEvents()
    check("自定义形状进入描边模式",
          dlg.preview.mode == dlg.preview.MODE_POLYGON, dlg.preview.mode)
    dlg.close()


def test_model_badge(app) -> None:
    print("[7] 面板显示当前模型名")
    cfg = AppConfig()
    cfg.provider = "siliconflow"
    cfg.api_model = "Qwen/Qwen3-8B"
    label = lmstudio.active_model_label(cfg)
    check("云端显示平台+模型", "SiliconFlow" in label and "Qwen/Qwen3-8B" in label, label)

    images, title = load_input_images(ROOT / "samples" / "sample_manga_ja.zip")
    doc = Document([PageModel(p) for p in images], None, title)
    local = AppConfig()
    local.auto_ocr = False
    local.lm_model = "index-translate-2b"
    dlg = RegionDialog(doc, [RegionDraft(0, QRectF(0.1, 0.1, 0.4, 0.2),
                                        doc.original_size(0))], local, None)
    dlg.show()
    app.processEvents()
    text = dlg.model_badge.text()
    check("徽章显示模型", "index-translate-2b" in text, text)
    check("按钮提示含模型", "index-translate-2b" in dlg.btn_translate.toolTip(),
          dlg.btn_translate.toolTip())
    dlg.close()


def main() -> int:
    app = QApplication(sys.argv)
    apply_theme(app)
    test_shapes()
    test_strokes()
    test_serialization()
    test_dialog_controls(app)
    test_model_badge(app)
    print()
    if FAILED:
        print(f"失败 {len(FAILED)} 项：" + ", ".join(FAILED))
        return 1
    print("形状/涂鸦/模型名 全部通过")
    return 0


if __name__ == "__main__":
    sys.exit(main())
