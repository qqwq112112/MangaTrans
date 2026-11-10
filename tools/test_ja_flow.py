# -*- coding: utf-8 -*-
"""End-to-end Japanese test: real manga-ocr + real LM Studio model.

Requires LM Studio's local server to be running with a chat model loaded.
Run: python tools/test_ja_flow.py
"""

from __future__ import annotations

import shutil
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from PySide6.QtCore import QRectF  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from mangatrans import lmstudio, ocr  # noqa: E402
from mangatrans.archive import load_input_images  # noqa: E402
from mangatrans.config import AppConfig  # noqa: E402
from mangatrans.document import Document, PageModel  # noqa: E402
from mangatrans.theme import apply_theme  # noqa: E402
from mangatrans.viewer import RegionDraft  # noqa: E402

FAILED: list[str] = []


def check(name: str, cond: bool, detail: str = "") -> None:
    print(("  PASS  " if cond else "  FAIL  ") + name + (f" {detail}" if detail else ""))
    if not cond:
        FAILED.append(name)


def wait_until(app, predicate, timeout=180.0) -> bool:
    end = time.time() + timeout
    while time.time() < end:
        app.processEvents()
        if predicate():
            return True
        time.sleep(0.05)
    return False


def main() -> int:
    app = QApplication(sys.argv)
    apply_theme(app)

    print("[1] LM Studio 连接")
    cfg = AppConfig()
    found = lmstudio.discover_base_url(cfg.lm_base_url)
    check("自动发现服务器端口", bool(found), str(found))
    if not found:
        print("  → 请先在 LM Studio 启动本地服务器")
        return 1
    models = lmstudio.list_models(found)
    check("模型列表非空", bool(models), str(models))
    chat = lmstudio.pick_chat_model(models, cfg.lm_model)
    check("选中对话模型（排除 embedding）", bool(chat) and "embed" not in chat.lower(), chat)
    cfg.lm_base_url = found
    cfg.lm_model = chat

    print("[2] 日文样例 + manga-ocr")
    zip_path = ROOT / "samples" / "sample_manga_ja.zip"
    if not zip_path.exists():
        import subprocess
        subprocess.run([sys.executable, str(ROOT / "tools" / "make_sample_ja.py")], check=True)
    images, title = load_input_images(zip_path)
    check("加载 2 页", len(images) == 2, str(len(images)))
    doc = Document([PageModel(p) for p in images], zip_path, title)

    check("manga-ocr 可用", ocr.manga_ocr_available())
    # Bubble regions in normalized coordinates (match the sample generator).
    bubble_a = QRectF(0.09, 0.06, 0.57, 0.30)
    crop = doc.pages[0].crop_raw(bubble_a)
    t0 = time.time()
    result = ocr.run_ocr(crop, "manga")
    elapsed = time.time() - t0
    check("OCR 成功", result.ok, result.error or "")
    check("识别出日文假名", ocr.looks_japanese(result.text), repr(result.text))
    print(f"      识别内容：{result.text!r}  ({elapsed:.1f}s, {result.backend})")

    print("[3] 翻译（真实模型）")
    cfg.auto_ocr = False
    cfg.auto_translate = True
    t0 = time.time()
    try:
        chinese = lmstudio.translate_text(result.text, cfg.lm_base_url, cfg.lm_model,
                                          cfg.lm_temperature)
    except Exception as exc:
        check("翻译成功", False, str(exc))
        chinese = ""
    else:
        check("翻译成功", bool(chinese.strip()), chinese[:60])
        check("译文是中文", any("\u4e00" <= c <= "\u9fff" for c in chinese), chinese[:40])
        check("译文不再含假名", not ocr.looks_japanese(chinese), chinese[:40])
        print(f"      译文：{chinese!r}  ({time.time() - t0:.1f}s)")

    print("[4] 渲染到画面并导出")
    from mangatrans.region_dialog import RegionDialog

    dlg = RegionDialog(doc, [RegionDraft(0, bubble_a, doc.original_size(0))], cfg, None)
    dlg.show()
    app.processEvents()
    dlg._loading_ui = True
    dlg.source_edit.setPlainText(result.text)
    dlg.translated_edit.setPlainText(chinese)
    dlg._loading_ui = False
    dlg.states[0].source_text = result.text
    dlg.states[0].op.text = chinese
    dlg.states[0].has_translation = True
    dlg._refresh_preview()
    app.processEvents()

    ops = dlg.result_ops()
    check("面板收集到译文", len(ops) == 1 and ops[0][1].text == chinese, str(len(ops)))
    if ops:
        page_index, op = ops[0]
        doc.add_op(page_index, op)
        out = ROOT / "samples" / "ja_out"
        shutil.rmtree(out, ignore_errors=True)
        written = doc.export_all(out)
        check("导出 2 页", len(written) == 2, str(len(written)))
        from PIL import Image
        with Image.open(written[0]) as im:
            w, h = im.size
            box = (int(bubble_a.x() * w) + 10, int(bubble_a.y() * h) + 10,
                   int((bubble_a.x() + bubble_a.width()) * w) - 10,
                   int((bubble_a.y() + bubble_a.height()) * h) - 10)
            crop = im.convert("RGB").crop(box)
            dark = sum(1 for px in crop.getdata() if px[0] < 100)
            check("导出页出现中文字形", dark > 400, f"dark={dark}")
        shutil.copy(written[0], ROOT / "samples" / "shots" / "ja_translated.png")
    dlg.close()

    print()
    if FAILED:
        print("失败：" + ", ".join(FAILED))
        return 1
    print("日文全流程通过")
    return 0


if __name__ == "__main__":
    sys.exit(main())
