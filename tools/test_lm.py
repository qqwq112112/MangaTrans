# -*- coding: utf-8 -*-
"""End-to-end translation test against a fake OpenAI-compatible server.

Validates the LM Studio client + dialog wiring without needing LM Studio
running. Run: python tools/test_lm.py
"""

from __future__ import annotations

import json
import sys
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

received: list[dict] = []


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *args):
        pass

    def _send(self, payload: dict, code: int = 200) -> None:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        if self.path.endswith("/models"):
            self._send({"object": "list", "data": [
                {"id": "fake-qwen-0.8b", "object": "model"},
            ]})
        else:
            self.send_error(404)

    def do_POST(self):
        length = int(self.headers.get("Content-Length", 0))
        raw = self.rfile.read(length)
        try:
            payload = json.loads(raw)
        except Exception:
            self.send_error(400)
            return
        received.append(payload)
        user_text = ""
        for msg in payload.get("messages", []):
            if msg.get("role") == "user":
                user_text = msg.get("content", "")
        self._send({
            "id": "chatcmpl-test",
            "object": "chat.completion",
            "choices": [{
                "index": 0,
                "message": {"role": "assistant", "content": f"「译」{user_text}"},
                "finish_reason": "stop",
            }],
            "usage": {"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15},
        })


def main() -> int:
    from mangatrans import lmstudio

    server = HTTPServer(("127.0.0.1", 0), Handler)
    port = server.server_address[1]
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    base = f"http://127.0.0.1:{port}/v1"
    failures: list[str] = []

    def check(name, cond, detail=""):
        print(("PASS  " if cond else "FAIL  ") + name + (" " + str(detail) if detail else ""))
        if not cond:
            failures.append(name)

    ok, msg, models = lmstudio.test_connection(base)
    check("测试连接成功", ok and models == ["fake-qwen-0.8b"], f"{ok} {msg} {models}")

    chosen = lmstudio.ensure_model(base)
    check("自动选择模型", chosen == "fake-qwen-0.8b", chosen)

    out = lmstudio.translate_text("今日はいい天気ですね。", base, chosen, 0.2)
    check("翻译返回内容", out == "「译」今日はいい天気ですね。", out)
    sent = received[-1]
    check("请求带系统提示", sent["messages"][0]["role"] == "system"
          and "简体中文" in sent["messages"][0]["content"])
    check("语言固定为简体中文", "繁体字" in sent["messages"][0]["content"])
    check("请求温度为 0.2", abs(sent["temperature"] - 0.2) < 1e-9, sent["temperature"])
    # translate_text() is the simple one-shot helper: no streaming flags.
    # translate_full() is what the UI uses when it wants live metrics.
    check("一次性接口不带 stream", "stream" not in sent,
          str(sent.get("stream")))

    # Cleaning of model noise
    check("清理「译文：」前缀", lmstudio._clean_translation("译文：你好") == "你好")
    check("去掉外层引号", lmstudio._clean_translation("「你好」") == "你好")

    # Connection error path
    try:
        lmstudio.translate_text("x", "http://127.0.0.1:1/v1", "m")
        check("连不上时报错", False)
    except lmstudio.LMStudioError as exc:
        check("连不上时报错", "LM Studio" in str(exc), str(exc)[:40])

    check("URL 归一化", lmstudio.normalize_base_url("127.0.0.1:1234") == "http://127.0.0.1:1234/v1")

    # --- forced Simplified Chinese -------------------------------------
    check("繁体转简体", lmstudio.to_simplified("這是一個測試") == "这是一个测试",
          lmstudio.to_simplified("這是一個測試"))
    check("简体不变", lmstudio.to_simplified("这是一个测试") == "这是一个测试")
    check("日文不被破坏",
          lmstudio.to_simplified("ちょっと待って") == "ちょっと待って")
    check("清理时也转简体",
          "个" in lmstudio._clean_translation("譯文：這個測試")
          and "這" not in lmstudio._clean_translation("譯文：這個測試"),
          lmstudio._clean_translation("譯文：這個測試"))

    server.shutdown()
    print()
    if failures:
        print("失败：" + ", ".join(failures))
        return 1
    print("LM Studio 客户端全部通过")
    return 0


if __name__ == "__main__":
    sys.exit(main())
