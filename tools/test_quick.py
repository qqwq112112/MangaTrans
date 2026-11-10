# -*- coding: utf-8 -*-
"""Test the one-click chain (需求1): OCR -> translate -> fill -> apply.

Uses the real manga-ocr engine and a fake OpenAI server, so no LM Studio needed.
Run: python tools/test_quick.py
"""

from __future__ import annotations

import json
import os
import shutil
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from PySide6.QtCore import QRectF  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from mangatrans.archive import load_input_images  # noqa: E402
from mangatrans.config import AppConfig  # noqa: E402
from mangatrans.document import Document, PageModel  # noqa: E402
from mangatrans.region_dialog import RegionDialog  # noqa: E402
from mangatrans.theme import apply_theme  # noqa: E402
from mangatrans.viewer import RegionDraft  # noqa: E402

FAILED: list[str] = []


def check(name: str, cond: bool, detail: str = "") -> None:
    print(("  PASS  " if cond else "  FAIL  ") + name + (f" {detail}" if detail else ""))
    if not cond:
        FAILED.append(name)


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *args):
        pass

    def do_GET(self):
        body = json.dumps({"data": [{"id": "fake-model"}]}).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_POST(self):
        payload = json.loads(self.rfile.read(int(self.headers.get("Content-Length", 0))))
        src = payload["messages"][-1]["content"]
        reply = "【译】" + src.replace("\n", " ")
        body = json.dumps({"choices": [{"message": {"content": reply}}]},
                          ensure_ascii=False).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


def wait_until(app, predicate, timeout=180.0) -> bool:
    end = time.time() + timeout
    while time.time() < end:
        app.processEvents()
        if predicate():
            return True
        time.sleep(0.03)
    return False


def test_quick_chain(app, port: int) -> None:
    print("[1] 一键直通：识别 → 翻译 → 取主色 → 写入")
    images, title = load_input_images(ROOT / "samples" / "sample_manga_ja.zip")
    doc = Document([PageModel(p) for p in images], None, title)

    cfg = AppConfig()
    cfg.auto_ocr = False
    cfg.lm_base_url = f"http://127.0.0.1:{port}/v1"
    cfg.lm_model = "fake-model"

    draft = RegionDraft(0, QRectF(0.09, 0.06, 0.57, 0.30), doc.original_size(0))
    dlg = RegionDialog(doc, [draft], cfg, None)
    dlg.show()
    app.processEvents()

    check("初始无译文", not dlg.result_ops())
    dlg._quick_apply()
    accepted = wait_until(app, lambda: dlg.result() == RegionDialog.Accepted
                          or (not dlg._quick_active and dlg.status.text().startswith("一键直通失败")),
                          timeout=240)

    check("链路结束", accepted, dlg.status.text()[:60])
    st = dlg.states[0]
    check("已识别原文", bool(st.source_text.strip()), repr(st.source_text[:30]))
    check("识别出日文", any("\u3040" <= c <= "\u30ff" for c in st.source_text),
          repr(st.source_text[:20]))
    check("已翻译", st.has_translation, st.op.text[:30])
    check("译文非空", bool(st.op.text.strip()), st.op.text[:30])
    check("底色已自动取", st.op.fill_color.name().upper() not in ("#000000",),
          st.op.fill_color.name())
    check("对话框自动确认", dlg.result() == RegionDialog.Accepted,
          str(dlg.result()))

    ops = dlg.result_ops()
    check("产出可应用区域", len(ops) == 1, str(len(ops)))
    return doc, ops, dlg


def test_quick_result_renders(app, doc, ops) -> None:
    print("[2] 一键结果写入画面并导出")
    if not ops:
        check("可导出", False, "无产出")
        return
    page_index, op = ops[0]
    doc.add_op(page_index, op)
    out = ROOT / "samples" / "_quick_out"
    shutil.rmtree(out, ignore_errors=True)
    written = doc.export_all(out)
    check("导出成功", len(written) == 2, str(len(written)))

    from PIL import Image
    with Image.open(written[0]) as im:
        w, h = im.size
        r = op.rect
        box = (int(r.x() * w) + 8, int(r.y() * h) + 8,
               int((r.x() + r.width()) * w) - 8,
               int((r.y() + r.height()) * h) - 8)
        crop = im.convert("RGB").crop(box)
        dark = sum(1 for px in crop.getdata() if px[0] < 100)
        check("画面出现译文", dark > 500, f"dark={dark}")
        # Background must have been covered: the original bubble had dark text
        # all over; after fill most of the area should be near-uniform.
        px = im.convert("RGB").getpixel((int((r.x() + 0.08) * w),
                                         int((r.y() + 0.5) * h)))
        check("底色已覆盖", max(px) > 200, str(px))
    shutil.rmtree(out, ignore_errors=True)


def test_quick_falls_back_without_ocr(app) -> None:
    print("[3] 无 OCR 引擎时优雅失败")
    import mangatrans.region_dialog as rd

    images, title = load_input_images(ROOT / "samples" / "sample_manga_ja.zip")
    doc = Document([PageModel(p) for p in images], None, title)
    cfg = AppConfig()
    cfg.auto_ocr = False
    cfg.ocr_backend = "manual"

    draft = RegionDraft(0, QRectF(0.1, 0.1, 0.4, 0.2), doc.original_size(0))
    dlg = RegionDialog(doc, [draft], cfg, None)
    dlg.show()
    app.processEvents()

    original = rd.ocr.available_backends
    rd.ocr.available_backends = lambda: []
    try:
        dlg._quick_apply()
        app.processEvents()
        check("未崩溃", True)
        check("给出提示", "手动" in dlg.status.text() or "OCR" in dlg.status.text(),
              dlg.status.text()[:50])
        check("按钮恢复可用", dlg.btn_quick.isEnabled())
    finally:
        rd.ocr.available_backends = original
        dlg.close()


def main() -> int:
    server = HTTPServer(("127.0.0.1", 0), Handler)
    port = server.server_address[1]
    threading.Thread(target=server.serve_forever, daemon=True).start()

    app = QApplication(sys.argv)
    apply_theme(app)
    try:
        doc, ops, dlg = test_quick_chain(app, port)
        test_quick_result_renders(app, doc, ops)
        test_quick_falls_back_without_ocr(app)
        dlg.close()
    finally:
        server.shutdown()

    print()
    if FAILED:
        print(f"失败 {len(FAILED)} 项：" + ", ".join(FAILED))
        return 1
    print("一键直通全部通过")
    return 0


if __name__ == "__main__":
    sys.exit(main())
