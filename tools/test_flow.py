# -*- coding: utf-8 -*-
"""Full workflow test: extract -> select -> OCR -> translate -> apply -> export.

Runs against a fake LM Studio server so no model is needed.
Run: python tools/test_flow.py
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

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QRectF  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from mangatrans import ocr  # noqa: E402
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
        source = payload["messages"][-1]["content"]
        # Marker is a bracket, not a "译文：" prefix: the client strips those.
        reply = "【中】" + source.replace("\n", " ")
        body = json.dumps({"choices": [{"message": {"content": reply}}]},
                          ensure_ascii=False).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


def wait_until(app, predicate, timeout=15.0) -> bool:
    end = time.time() + timeout
    while time.time() < end:
        app.processEvents()
        if predicate():
            return True
        time.sleep(0.02)
    return False


def main() -> int:
    server = HTTPServer(("127.0.0.1", 0), Handler)
    port = server.server_address[1]
    threading.Thread(target=server.serve_forever, daemon=True).start()

    app = QApplication(sys.argv)
    apply_theme(app)

    print("[1] 解压载入")
    zip_path = ROOT / "samples" / "sample_manga.zip"
    images, title = load_input_images(zip_path)
    doc = Document([PageModel(p) for p in images], zip_path, title)
    check("页数", doc.page_count == 3, str(doc.page_count))

    print("[2] 框选 → 对话框")
    cfg = AppConfig()
    cfg.lm_base_url = f"http://127.0.0.1:{port}/v1"
    cfg.lm_model = "fake-model"
    cfg.auto_ocr = False
    cfg.auto_translate = True
    rect = QRectF(0.16, 0.11, 0.70, 0.20)
    drafts = [RegionDraft(0, rect, doc.original_size(0))]
    dlg = RegionDialog(doc, drafts, cfg, None)
    dlg.show()
    app.processEvents()
    check("对话框打开", dlg.isVisible(), "")
    check("初始无译文", not dlg.result_ops(), str(len(dlg.result_ops())))

    print("[3] 真实 OCR（Windows OCR）")
    check("Windows OCR 可用", ocr.windows_ocr_available())
    dlg._ocr_current()
    ok = wait_until(app, lambda: dlg.states[0].ocr_state in ("done", "failed"), 30)
    check("OCR 完成", ok and dlg.states[0].ocr_state == "done",
          f"state={dlg.states[0].ocr_state} err={dlg.status.text()[:80]}")
    text = dlg.states[0].source_text
    check("OCR 识别出中文", "天气" in text, repr(text[:40]))

    print("[4] 自动翻译（假服务器）")
    ok = wait_until(app, lambda: dlg.states[0].translate_state == "done", 30)
    check("翻译完成", ok, f"state={dlg.states[0].translate_state} {dlg.status.text()[:60]}")
    check("译文进入区域", dlg.states[0].op.text.startswith("【中】"), dlg.states[0].op.text[:30])

    print("[5] 应用并导出")
    ops = dlg.result_ops()
    check("结果非空", len(ops) == 1, str(len(ops)))
    if ops:
        page_index, op = ops[0]
        doc.add_op(page_index, op)
        out_dir = ROOT / "samples" / "flow_out"
        shutil.rmtree(out_dir, ignore_errors=True)
        written = doc.export_all(out_dir)
        check("导出文件", len(written) == 3, str(len(written)))

        from PIL import Image
        with Image.open(written[0]) as im:
            w, h = im.size
            box = (int(rect.x() * w) + 6, int(rect.y() * h) + 6,
                   int((rect.x() + rect.width()) * w) - 6,
                   int((rect.y() + rect.height()) * h) - 6)
            crop = im.convert("RGB").crop(box)
            dark = sum(1 for px in crop.getdata() if px[0] < 100)
            check("导出页含新文字像素", dark > 500, f"dark={dark}")
        # The same page re-rendered from cache must be stable.
        doc.export_page(0, out_dir / "again.png")
        check("重复导出不报错", (out_dir / "again.png").exists())

    dlg.close()
    server.shutdown()

    print()
    if FAILED:
        print("失败：" + ", ".join(FAILED))
        return 1
    print("完整流程通过")
    return 0


if __name__ == "__main__":
    sys.exit(main())
