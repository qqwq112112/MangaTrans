# -*- coding: utf-8 -*-
"""Tests for silent themed notifications, the OCR model prompt, and the
panel's widened scrollbar.

Run: python tools/test_notify.py
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from PySide6.QtCore import QRectF, Qt, QPoint  # noqa: E402
from PySide6.QtWidgets import QApplication, QLabel, QWidget  # noqa: E402

from mangatrans import notify, ocr  # noqa: E402
from mangatrans.archive import load_input_images  # noqa: E402
from mangatrans.config import AppConfig  # noqa: E402
from mangatrans.document import Document, PageModel  # noqa: E402
from mangatrans.notify import NoticeOverlay, ToastLabel  # noqa: E402
from mangatrans.region_dialog import RegionDialog  # noqa: E402
from mangatrans.theme import apply_theme  # noqa: E402
from mangatrans.viewer import RegionDraft  # noqa: E402

FAILED: list[str] = []


def check(name: str, cond: bool, detail: str = "") -> None:
    print(("  PASS  " if cond else "  FAIL  ") + name + (f" {detail}" if detail else ""))
    if not cond:
        FAILED.append(name)


def test_toast(app) -> None:
    print("[1] 浮动提示（静音、主题色、自动消失）")
    host = QWidget()
    host.resize(600, 400)
    host.show()
    app.processEvents()

    notify.toast(host, "已保存进度", "success", 400)
    app.processEvents()
    toast = host._notice_toast
    check("提示已创建", isinstance(toast, ToastLabel))
    check("提示可见", toast.isVisible())
    check("文字正确", toast.text() == "已保存进度", toast.text())

    qss = toast.styleSheet()
    check("使用主题青绿配色", "#14312e" in qss and "#2dd4bf" not in qss or "#9ff3e8" in qss,
          qss[:60])
    check("圆角边框", "border-radius" in qss)

    # Click-through: never steals the mouse.
    check("鼠标穿透", toast.testAttribute(Qt.WA_TransparentForMouseEvents))
    # Non-blocking: it is a child label, not a dialog.
    check("不是模态窗口", not isinstance(toast, NoticeOverlay))

    # Korean/Chinese text must not be clipped at narrow widths either.
    notify.toast(host, "很长的提示文字" * 6, "warning", 300)
    app.processEvents()
    check("可显示长文本", toast.width() > 200, str(toast.width()))

    # Variants use distinct colours.
    notify.toast(host, "错误", "error", 300)
    app.processEvents()
    check("错误用红色系", "#3a1d22" in toast.styleSheet(), toast.styleSheet()[:40])
    host.close()


def test_notice_overlay(app) -> None:
    print("[2] 窗口内覆盖层（不创建新窗口 → 不触发系统提示音）")
    host = QWidget()
    host.resize(800, 560)
    host.show()
    app.processEvents()

    ov = NoticeOverlay(host, "标题", "内容", "info",
                       [("取消", 0, "ghost"), ("确定", 1, "primary")])
    check("是同窗口的子控件", ov.parentWidget() is host)
    check("不是顶层窗口", not ov.isWindow())

    ov._finish(1)
    check("确认返回 1", ov.chosen() == 1, str(ov.chosen()))

    ov2 = NoticeOverlay(host, "标题", "内容", "error", [("知道了", 1, "danger")])
    ov2._finish(1)
    check("危险按钮可用", ov2.chosen() == 1)

    check("有 confirm 接口", callable(notify.confirm))
    check("有 alert 接口", callable(notify.alert))
    host.close()


def test_notice_content_fits(app) -> None:
    """Every help notice must render all of its text without clipping."""
    print("[2b] 弹窗内容完整显示（不裁切、无多余滚动条）")
    from PySide6.QtWidgets import QFrame, QTextBrowser

    from mangatrans.main_window import MainWindow

    win = MainWindow()
    win.resize(1200, 800)
    win.show()
    app.processEvents()

    cases = [("show_help", "快捷键"), ("show_license", "开源声明"),
             ("show_contact", "联系作者"), ("show_about", "关于")]
    for func_name, label in cases:
        holder: dict = {}

        def inspect(_label=label, _holder=holder) -> None:
            for ov in win.findChildren(NoticeOverlay):
                if not ov.isVisible():
                    continue
                body = ov.findChild(QTextBrowser, "NoticeBody")
                card = ov.findChild(QFrame, "NoticePanel")
                doc = body.document()
                doc.setTextWidth(body.width() - 8)
                _holder["need"] = int(doc.size().height())
                _holder["have"] = body.height()
                _holder["scroll"] = body.verticalScrollBar().isVisible()
                _holder["card_w"] = card.width()
                ov._finish(1)

        from PySide6.QtCore import QTimer
        QTimer.singleShot(420, inspect)
        getattr(win, func_name)()
        app.processEvents()

        need = holder.get("need")
        have = holder.get("have")
        check(f"{label} 文本完整渲染",
              need is not None and have is not None and need <= have,
              f"需要={need} 实际={have}")
        check(f"{label} 无多余滚动条", holder.get("scroll") is False,
              str(holder.get("scroll")))
        check(f"{label} 卡片宽度合理", (holder.get("card_w") or 0) >= 400,
              str(holder.get("card_w")))

    win.close()


def test_no_qmessagebox() -> None:
    print("[3] 项目内已无 QMessageBox 调用")
    import ast
    offenders = []
    for path in (ROOT / "mangatrans").glob("*.py"):
        source = path.read_text(encoding="utf-8")
        tree = ast.parse(source)
        # Walk the AST so docstrings/comments never count as real calls.
        for node in ast.walk(tree):
            if isinstance(node, ast.Attribute) and node.attr in (
                    "warning", "information", "question", "critical", "about"):
                base = node.value
                if isinstance(base, ast.Name) and base.id == "QMessageBox":
                    offenders.append(f"{path.name}:{node.lineno}")
    check("无 QMessageBox 调用", not offenders, str(offenders[:5]))


def test_ocr_model_status() -> None:
    print("[4] OCR 模型状态检测")
    status = ocr.model_status()
    for key in ("library", "model_cached", "ready", "needs_download"):
        check(f"含字段 {key}", key in status, str(list(status)))
    check("状态互斥", not (status["ready"] and status["needs_download"]),
          str(status))
    check("缓存路径可读", bool(ocr.endpoint_hint()), ocr.endpoint_hint())
    check("模型大小常量合理", 100 <= ocr.MANGA_MODEL_SIZE_MB <= 2000,
          str(ocr.MANGA_MODEL_SIZE_MB))
    # download_model must be importable/callable (not executed here: network).
    check("有下载接口", callable(ocr.download_model))


def test_startup_prompt_guard() -> None:
    print("[5] 启动检测不会在无引擎时打扰用户")
    from mangatrans.main_window import MainWindow

    src = (ROOT / "mangatrans" / "main_window.py").read_text(encoding="utf-8")
    check("存在 check_ocr_model", "def check_ocr_model" in src)
    check("无引擎时直接返回", "if not status[\"library\"]:" in src)
    check("已缓存时不提示", "if status[\"model_cached\"]:" in src)
    check("提供立即下载选项", "立即下载" in src)
    check("可跳过", "以后再说" in src)
    del MainWindow


def test_dialog_scrollbar(app) -> None:
    print("[6] 选区面板右侧滚动条加粗可用")
    images, title = load_input_images(ROOT / "samples" / "sample_manga_ja.zip")
    doc = Document([PageModel(p) for p in images], None, title)
    dlg = RegionDialog(doc, [RegionDraft(0, QRectF(0.1, 0.1, 0.4, 0.2),
                                        doc.original_size(0))],
                       AppConfig(auto_ocr=False), None)
    dlg.resize(1200, 700)
    dlg.show()
    app.processEvents()

    scroll = dlg._settings_scroll
    bar = scroll.verticalScrollBar()
    check("滚动条始终可见", scroll.verticalScrollBarPolicy() == Qt.ScrollBarAlwaysOn,
          str(scroll.verticalScrollBarPolicy()))
    check("宽度 >= 16px（易抓取）", bar.width() >= 16, f"{bar.width()}px")
    check("内容可滚动", bar.maximum() > 0, f"max={bar.maximum()}")

    # Wheel over an inert label must scroll the column.
    before = bar.value()
    label = next((w for w in dlg.findChildren(QLabel) if w.isVisible()), None)
    if label is not None:
        from PySide6.QtGui import QWheelEvent
        from PySide6.QtCore import QPointF
        ev = QWheelEvent(QPointF(10, 10), QPointF(10, 10), QPoint(0, 0),
                         QPoint(0, -120), Qt.NoButton, Qt.NoModifier,
                         Qt.NoScrollPhase, False)
        dlg.eventFilter(label, ev)
        app.processEvents()
        check("滚轮可滚动面板", bar.value() != before,
              f"{before} -> {bar.value()}")
    dlg.close()


def main() -> int:
    app = QApplication(sys.argv)
    apply_theme(app)
    test_toast(app)
    test_notice_overlay(app)
    test_notice_content_fits(app)
    test_no_qmessagebox()
    test_ocr_model_status()
    test_startup_prompt_guard()
    test_dialog_scrollbar(app)
    print()
    if FAILED:
        print(f"失败 {len(FAILED)} 项：" + ", ".join(FAILED))
        return 1
    print("通知/OCR提示/滚动条 全部通过")
    return 0


if __name__ == "__main__":
    sys.exit(main())
