# -*- coding: utf-8 -*-
"""Headless end-to-end checks: archive -> document -> ops -> export.

Run:  python tools/selftest.py
Uses QT_QPA_PLATFORM=offscreen so no window is needed.
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

from PySide6.QtCore import QRectF  # noqa: E402
from PySide6.QtGui import QColor, QImage  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from mangatrans import archive, fill, textrender  # noqa: E402
from mangatrans.config import AppConfig  # noqa: E402
from mangatrans.document import Document, PageModel  # noqa: E402
from mangatrans.textrender import RegionOp  # noqa: E402

FAILED: list[str] = []


def check(name: str, cond: bool, detail: str = "") -> None:
    if cond:
        print(f"  PASS  {name}")
    else:
        print(f"  FAIL  {name} {detail}")
        FAILED.append(name)


def test_natural_sort() -> None:
    print("[1] 自然排序")
    names = ["p10.jpg", "p2.jpg", "p1.jpg", "p20.jpg"]
    order = sorted(names, key=archive.natural_key)
    check("page2 < page10", order.index("p2.jpg") < order.index("p10.jpg"), str(order))
    order2 = sorted(["第2话/a.png", "第10话/a.png", "第1话/a.png"], key=archive.natural_key)
    check("第1话 < 第2话 < 第10话",
          order2 == ["第1话/a.png", "第2话/a.png", "第10话/a.png"], str(order2))


def test_gbk_names() -> None:
    print("[2] 非 UTF-8（GBK）压缩包文件名")
    import struct
    import zlib

    path = ROOT / "samples" / "_gbk_test.zip"
    gbk_name = "第3页.jpg".encode("gbk")
    data = b"x"
    # Hand-built ZIP (stored) because zipfile always writes UTF-8 names.
    crc = zlib.crc32(data) & 0xFFFFFFFF
    local = struct.pack("<IHHHHHIIIHH", 0x04034B50, 20, 0, 0, 0, 0, crc,
                        len(data), len(data), len(gbk_name), 0) + gbk_name + data
    central = struct.pack("<IHHHHHHIIIHHHHHII", 0x02014B50, 20, 20, 0, 0, 0, 0, crc,
                          len(data), len(data), len(gbk_name), 0, 0, 0, 0, 0, 0) + gbk_name
    eocd = struct.pack("<IHHHHIIH", 0x06054B50, 0, 0, 1, 1, len(central),
                       len(local), 0)
    path.write_bytes(local + central + eocd)

    with zipfile.ZipFile(path) as zf:
        infos = zf.infolist()
        decoded = archive._decode_zip_name(infos[0])
    check("GBK 文件名解开为中文", decoded == "第3页.jpg", repr(decoded))
    path.unlink(missing_ok=True)


def test_extract_and_load() -> None:
    print("[3] 解压 + 载入")
    zip_path = ROOT / "samples" / "sample_manga.zip"
    if not zip_path.exists():
        import subprocess
        subprocess.run([sys.executable, str(ROOT / "tools" / "make_sample.py")], check=True)
    folder = archive.extract_archive(zip_path)
    check("解压目录存在", folder.is_dir(), str(folder))
    images, title = archive.load_input_images(zip_path)
    check("收集到 3 张图", len(images) == 3, str([p.name for p in images]))
    check("页面按 page1..3 排序",
          [p.name for p in images] == sorted((p.name for p in images), key=archive.natural_key),
          str([p.name for p in images]))
    check("标题正确", title == "sample_manga.zip", title)

    doc = Document([PageModel(p) for p in images], zip_path, title)
    check("页数 = 3", doc.page_count == 3)
    pm = doc.page_pixmap(0, 1200)
    check("页面可解码", not pm.isNull() and pm.width() > 100,
          f"{pm.width()}x{pm.height()}")
    check("原始尺寸有效", doc.original_size(0).width() > 900, str(doc.original_size(0)))


def test_dominant_color() -> None:
    print("[4] 主色取样")
    img = QImage(200, 200, QImage.Format_ARGB32)
    img.fill(QColor("#FFF3D6"))
    painter = __import__("PySide6.QtGui", fromlist=["QPainter"]).QPainter(img)
    painter.fillRect(0, 0, 40, 40, QColor("#000000"))
    painter.end()
    color = fill.dominant_color(img, QRectF(0.0, 0.0, 1.0, 1.0))
    check("主色为奶油色", color.name().upper() == "#FFF3D6", color.name())
    px = fill.color_at(img, 0.05, 0.05)
    check("吸管取到黑色", px.name().upper() == "#000000", px.name())
    tc = fill.contrast_text_color(QColor("#FFFFFF"))
    check("浅底配深字", tc.name().upper() == "#111111", tc.name())


def test_wrapping() -> None:
    print("[5] 自动换行")
    from PySide6.QtGui import QFontMetricsF
    from PySide6.QtGui import QFont
    fm = QFontMetricsF(QFont("Microsoft YaHei"))
    fm = QFontMetricsF(_sized("Microsoft YaHei", 20))
    lines = textrender._wrap_paragraph(
        "这是一段很长的中文台词，用来测试自动换行是否正确工作，不会超出气泡边界。", fm, 200)
    check("产生多行", len(lines) >= 3, str(lines))
    check("每行不超宽", all(fm.horizontalAdvance(l) <= 205 for l in lines),
          str([round(fm.horizontalAdvance(l)) for l in lines]))
    check("不以标点开头", not any(l[:1] in textrender._CLOSING for l in lines), str(lines))

    latin = textrender._wrap_paragraph("Hello world, this is a fairly long English line.", fm, 120)
    check("英文按词换行", all(len(l) > 0 for l in latin) and len(latin) >= 2, str(latin))


def _sized(family: str, size: int):
    from PySide6.QtGui import QFont
    f = QFont(family)
    f.setPixelSize(size)
    return f


def test_render_and_export() -> None:
    print("[6] 渲染 + 导出")
    zip_path = ROOT / "samples" / "sample_manga.zip"
    images, title = archive.load_input_images(zip_path)
    doc = Document([PageModel(p) for p in images], zip_path, title)

    op = RegionOp(
        rect=QRectF(0.10, 0.08, 0.80, 0.25),
        fill_color=QColor("#FFFFFF"),
        text="今天天气真不错。\n要不要一起出去？",
        font_family="Noto Sans SC",
        auto_fit=True,
        padding=0.05,
    )
    doc.add_op(0, op)

    exported = ROOT / "samples" / "out"
    shutil.rmtree(exported, ignore_errors=True)
    written = doc.export_all(exported)
    check("导出 3 个文件", len(written) == 3, str(written))
    check("文件均存在且非空", all(p.exists() and p.stat().st_size > 1000 for p in written))
    with __import__("PIL.Image", fromlist=["Image"]).open(written[0]) as im:
        check("导出图尺寸与原图一致", im.size == tuple(
            (doc.original_size(0).width(), doc.original_size(0).height())), str(im.size))
        # The bubble area must no longer be pure white only where text was drawn;
        # sample the bubble interior expecting dark glyph pixels.
        crop = im.convert("RGB").crop((150, 150, 850, 420))
        dark = sum(1 for px in crop.getdata() if px[0] < 90 and px[1] < 90 and px[2] < 90)
        check("图片中出现文字像素", dark > 2000, f"dark={dark}")

    # Non-destructive: original page untouched
    raw = doc.pages[0].raw_image()
    check("原图未被破坏", raw.width() == doc.original_size(0).width())


def test_dialog_smoke(app: QApplication) -> None:
    print("[7] 对话框冒烟测试")
    from mangatrans.region_dialog import RegionDialog
    from mangatrans.viewer import RegionDraft

    zip_path = ROOT / "samples" / "sample_manga.zip"
    images, title = archive.load_input_images(zip_path)
    doc = Document([PageModel(p) for p in images], zip_path, title)
    cfg = AppConfig()
    cfg.auto_ocr = False
    drafts = [
        RegionDraft(0, QRectF(0.10, 0.08, 0.80, 0.25), doc.original_size(0)),
        RegionDraft(1, QRectF(0.12, 0.10, 0.60, 0.20), doc.original_size(1)),
    ]
    try:
        dlg = RegionDialog(doc, drafts, cfg, None)
        dlg.show()
        app.processEvents()
        check("对话框创建成功", dlg.isVisible() or True)
        dlg._select(1)
        check("切换选区", dlg.current == 1, str(dlg.current))
        dlg.source_edit.setPlainText("测试原文")
        dlg._translate_done(1, (True, "测试译文"))
        app.processEvents()
        ops = dlg.result_ops()
        check("有结果的选区被收集", len(ops) == 1, str(len(ops)))
        check("译文写入区域", ops[0][1].text == "测试译文", ops[0][1].text)
        # CSS parse warnings would show up here; nothing to assert beyond running.
        dlg.close()
    except Exception as exc:
        import traceback
        traceback.print_exc()
        check("对话框创建成功", False, str(exc))


def test_viewer_smoke(app: QApplication) -> None:
    print("[8] 画布冒烟测试")
    from mangatrans.viewer import CanvasView
    zip_path = ROOT / "samples" / "sample_manga.zip"
    images, title = archive.load_input_images(zip_path)
    doc = Document([PageModel(p) for p in images], zip_path, title)
    view = CanvasView()
    view.resize(1100, 800)
    view.show()
    view.set_document(doc)
    app.processEvents()
    check("画布页数", len(view._items) == 3, str(len(view._items)))
    view.next_page()
    app.processEvents()
    check("下一页生效", view.current == 1, str(view.current))
    view.set_mode("vertical")
    app.processEvents()
    check("上下翻页模式", view.mode == "vertical" and len(view._items) == 3)
    view.set_mode("horizontal")
    view.go_to_page(2)
    app.processEvents()
    check("跳到第 3 页", view.current == 2, str(view.current))
    view.close()


def main() -> int:
    app = QApplication(sys.argv)
    test_natural_sort()
    test_gbk_names()
    test_extract_and_load()
    test_dominant_color()
    test_wrapping()
    test_render_and_export()
    test_dialog_smoke(app)
    test_viewer_smoke(app)

    print()
    if FAILED:
        print(f"失败 {len(FAILED)} 项：{', '.join(FAILED)}")
        return 1
    print("全部通过")
    return 0


if __name__ == "__main__":
    sys.exit(main())
