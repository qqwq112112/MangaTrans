# -*- coding: utf-8 -*-
"""Tests for translation providers (local / cloud) and the save toast.

Run: python tools/test_providers.py
"""

from __future__ import annotations

import json
import os
import sys
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from PySide6.QtTest import QTest  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from mangatrans import lmstudio  # noqa: E402
from mangatrans.archive import load_input_images  # noqa: E402
from mangatrans.config import AppConfig  # noqa: E402
from mangatrans.document import Document, PageModel  # noqa: E402
from mangatrans.main_window import MainWindow  # noqa: E402
from mangatrans.settings_dialog import SettingsDialog  # noqa: E402
from mangatrans.theme import apply_theme  # noqa: E402

FAILED: list[str] = []
SEEN_HEADERS: list[dict] = []


def check(name: str, cond: bool, detail: str = "") -> None:
    print(("  PASS  " if cond else "  FAIL  ") + name + (f" {detail}" if detail else ""))
    if not cond:
        FAILED.append(name)


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *args):
        pass

    def _json(self, payload: dict, code: int = 200) -> None:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        SEEN_HEADERS.append(dict(self.headers))
        auth = self.headers.get("Authorization", "")
        if self.path.endswith("/models"):
            if not auth:
                # Emulate a cloud API that rejects anonymous calls.
                self._json({"error": {"message": "missing api key"}}, 401)
                return
            self._json({"data": [{"id": "cloud-model-a"},
                                 {"id": "text-embedding-b"}]})
        else:
            self.send_error(404)

    def do_POST(self):
        SEEN_HEADERS.append(dict(self.headers))
        length = int(self.headers.get("Content-Length", 0))
        payload = json.loads(self.rfile.read(length))
        src = payload["messages"][-1]["content"]
        self._json({"choices": [{"message": {
            "content": "【云】" + src.replace("\n", " ")}}]})


def start_server() -> tuple[HTTPServer, str]:
    server = HTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return server, f"http://127.0.0.1:{server.server_address[1]}/v1"


def test_registry() -> None:
    print("[1] 供应商注册表")
    keys = [p.key for p in lmstudio.PROVIDERS]
    check("含本地运行时", all(k in keys for k in
                              ("lmstudio", "ollama", "llamacpp", "koboldcpp",
                               "mlx", "vllm")), str(keys))
    check("含主流云平台", all(k in keys for k in
                              ("openai", "claude", "deepseek", "kimi", "qwen",
                               "glm", "minimax", "gemini", "siliconflow",
                               "custom")), str(keys))
    check("共 16 个供应商", len(keys) == 16, str(len(keys)))
    local = lmstudio.provider_spec("lmstudio")
    check("本地不需要 key", local.is_local and not local.needs_key)
    check("Claude 用 anthropic 协议",
          lmstudio.provider_spec("claude").api_style == "anthropic")
    sf = lmstudio.provider_spec("siliconflow")
    check("硅基流动需要 key", sf.needs_key and not sf.is_local)
    check("硅基流动默认地址", "siliconflow" in sf.base_url, sf.base_url)
    check("未知 key 回退本地", lmstudio.provider_spec("nope").key == "lmstudio")
    check("旧配置 local 映射到 lmstudio",
          lmstudio.provider_spec("local").key == "lmstudio")

    cfg = AppConfig()
    cfg.provider = "deepseek"
    cfg.provider_profiles = {"deepseek": {"api_key": "sk-x",
                                          "model": "deepseek-chat",
                                          "base_url": "https://api.deepseek.com/v1",
                                          "temperature": 0.3}}
    opts = lmstudio.provider_settings(cfg)
    check("云端解析出 key", opts["api_key"] == "sk-x")
    check("云端非本地", opts["is_local"] is False)

    cfg.provider = "lmstudio"
    opts = lmstudio.provider_settings(cfg)
    check("本地不带 key", opts["api_key"] == "")


def test_missing_key() -> None:
    print("[2] 云端缺 Key 时给出可读错误")
    cfg = AppConfig()
    cfg.provider = "deepseek"
    cfg.provider_profiles = {"deepseek": {"api_key": "", "model": "deepseek-chat",
                                          "base_url": "https://api.deepseek.com/v1"}}
    try:
        lmstudio.translate_with_config("テスト", cfg)
        check("应该报错", False)
    except lmstudio.LMStudioError as exc:
        check("提示缺 Key", "API Key" in str(exc), str(exc)[:60])


def test_cloud_call(server: HTTPServer, base: str) -> None:
    print("[3] 云端调用带 Authorization 头")
    cfg = AppConfig()
    cfg.provider = "deepseek"
    cfg.provider_profiles = {"deepseek": {
        "base_url": base, "api_key": "sk-secret-123",
        "model": "cloud-model-a", "temperature": 0.3}}

    ok, msg, models = lmstudio.test_provider(cfg)
    check("测试连接成功", ok, msg[:60])
    check("拿到模型列表", "cloud-model-a" in models, str(models))
    check("请求带了 Bearer", any(
        h.get("Authorization") == "Bearer sk-secret-123" for h in SEEN_HEADERS),
        str(SEEN_HEADERS[-1].get("Authorization")))

    SEEN_HEADERS.clear()
    out = lmstudio.translate_with_config("今日はいい天気", cfg)
    check("译文返回", out.startswith("【云】"), out)
    check("POST 带 Bearer", any(
        h.get("Authorization") == "Bearer sk-secret-123" for h in SEEN_HEADERS),
        str(SEEN_HEADERS[-1].get("Authorization")) if SEEN_HEADERS else "")

    # Wrong key -> 401 from the server should surface a readable message.
    cfg.provider_profiles["deepseek"]["api_key"] = ""
    ok, msg, _models = lmstudio.test_provider(cfg)
    check("空 Key 被本地拦下", not ok and "API Key" in msg, msg[:50])


def test_cloud_without_port_discovery(server: HTTPServer) -> None:
    print("[4] 云端失败时不会偷偷回退到 localhost")
    cfg = AppConfig()
    cfg.provider = "custom"
    cfg.provider_profiles = {"custom": {
        "base_url": "http://127.0.0.1:9/v1", "api_key": "sk-x", "model": "m"}}
    ok, msg, _models = lmstudio.test_provider(cfg)
    check("失败但不误连本地", not ok, msg[:60])
    check("错误信息可读", "连不上" in msg or "超时" in msg, msg[:60])


def test_settings_ui(app) -> None:
    print("[5] 设置界面：供应商切换")
    cfg = AppConfig()
    dlg = SettingsDialog(cfg)
    dlg.show()
    app.processEvents()

    keys = [dlg.provider_combo.itemData(i) for i in range(dlg.provider_combo.count())]
    for expected in ("lmstudio", "ollama", "llamacpp", "koboldcpp", "mlx",
                     "openai", "claude", "deepseek", "kimi", "qwen",
                     "glm", "minimax", "gemini", "siliconflow", "custom"):
        check(f"含供应商 {expected}", expected in keys, str(keys[:4]))

    check("默认 LM Studio", dlg._current_provider().key == "lmstudio",
          dlg._current_provider().key)
    check("本地隐藏 Key", not dlg.key_host.isVisible())
    check("本地有默认地址", "127.0.0.1" in dlg.base_url_edit.text(),
          dlg.base_url_edit.text())

    for key, expect_host in (
            ("openai", "api.openai.com"),
            ("claude", "api.anthropic.com"),
            ("deepseek", "api.deepseek.com"),
            ("kimi", "api.moonshot.cn"),
            ("qwen", "dashscope.aliyuncs.com"),
            ("glm", "open.bigmodel.cn"),
            ("minimax", "api.minimax.chat"),
            ("gemini", "generativelanguage.googleapis.com"),
    ):
        idx = dlg.provider_combo.findData(key)
        dlg.provider_combo.setCurrentIndex(idx)
        app.processEvents()
        check(f"{key} 自动填地址", expect_host in dlg.base_url_edit.text(),
              dlg.base_url_edit.text())
        check(f"{key} 显示 Key 输入", dlg.key_host.isVisible())
        check(f"{key} 有默认模型", bool(dlg.model_combo.currentText().strip()),
              dlg.model_combo.currentText())

    # Each provider keeps its own values.
    idx = dlg.provider_combo.findData("deepseek")
    dlg.provider_combo.setCurrentIndex(idx)
    app.processEvents()
    dlg.api_key_edit.setText("sk-deepseek")
    dlg.apply_to_config()
    check("保存 provider", cfg.provider == "deepseek", cfg.provider)
    check("保存 key", cfg.provider_profiles["deepseek"]["api_key"] == "sk-deepseek",
          str(cfg.provider_profiles.get("deepseek", {}).get("api_key")))

    idx = dlg.provider_combo.findData("openai")
    dlg.provider_combo.setCurrentIndex(idx)
    app.processEvents()
    check("切到 openai 不带入 deepseek 的 key", dlg.api_key_edit.text() == "",
          dlg.api_key_edit.text())

    from PySide6.QtWidgets import QLineEdit
    check("Key 默认隐藏",
          dlg.api_key_edit.echoMode() == QLineEdit.Password,
          str(dlg.api_key_edit.echoMode()))
    dlg.close()


def test_save_toast(app) -> None:
    print("[6] 保存进度弹窗 1 秒")
    images, title = load_input_images(ROOT / "samples" / "sample_manga_ja.zip")
    doc = Document([PageModel(p) for p in images], None, title)
    win = MainWindow()
    win.resize(1100, 800)
    win.show()
    win.doc = doc
    win.canvas.set_document(doc)
    project = win.store.touch(ROOT / "samples" / "sample_manga_ja.zip",
                              title, "archive", doc.page_count)
    win.project_id = project.id
    QTest.qWait(120)

    win.save_progress(silent=False)
    app.processEvents()
    check("弹窗出现", win._toast.isVisible())
    check("弹窗有内容", "已保存" in win._toast.text(), win._toast.text())
    check("定时 1000ms", win._toast_timer.interval() == 1000,
          str(win._toast_timer.interval()))

    QTest.qWait(1300)
    check("1 秒后自动消失", not win._toast.isVisible())

    # Silent autosave must not pop up at all.
    win.save_progress(silent=True)
    app.processEvents()
    check("自动保存不弹窗", not win._toast.isVisible())
    win.close()


def main() -> int:
    server, base = start_server()
    app = QApplication(sys.argv)
    apply_theme(app)
    try:
        test_registry()
        test_missing_key()
        test_cloud_call(server, base)
        test_cloud_without_port_discovery(server)
        test_settings_ui(app)
        test_save_toast(app)
    finally:
        server.shutdown()

    print()
    if FAILED:
        print(f"失败 {len(FAILED)} 项：" + ", ".join(FAILED))
        return 1
    print("供应商与保存提示 全部通过")
    return 0


if __name__ == "__main__":
    sys.exit(main())
