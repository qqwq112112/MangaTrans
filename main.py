# -*- coding: utf-8 -*-
"""Entry point: python main.py [path]"""

from __future__ import annotations

import os
import sys

from PySide6.QtGui import QFont
from PySide6.QtWidgets import QApplication

from mangatrans.constants import APP_NAME, APP_TITLE
from mangatrans.main_window import MainWindow
from mangatrans.theme import apply_theme


def _selfcheck_ocr() -> int:
    """Headless diagnostic: run OCR on a page and report what came back.

    Packaged builds are windowed, so stdout is discarded; the report is also
    written to a file so a user can send it back:
        MangaTrans.exe --selfcheck-ocr [image-or-zip]
    """
    from pathlib import Path

    from mangatrans import ocr
    from mangatrans.archive import load_input_images
    from mangatrans.config import cache_dir
    from mangatrans.document import PageModel

    lines: list[str] = []

    def emit(text: str = "") -> None:
        lines.append(text)
        try:
            print(text)
        except Exception:
            pass          # windowed build has no usable stdout

    app = QApplication.instance() or QApplication([])   # QImage needs an app

    emit(f"OCR 后端：{ocr.describe_backends()}")
    emit(f"manga-ocr 可用：{ocr.manga_ocr_available()}")
    emit(f"Windows OCR 可用：{ocr.windows_ocr_available()}")

    target = None
    for arg in sys.argv[1:]:
        if not arg.startswith("-"):
            candidate = Path(arg)
            if candidate.exists():
                target = candidate
                break
    if target is None:
        emit("未指定图片或压缩包，跳过识别测试。")
        code = 0 if ocr.available_backends() else 2
    else:
        # Report the manga-ocr load error explicitly: auto mode silently falls
        # back to Windows OCR, which makes a broken bundle look "kind of ok".
        if ocr.manga_ocr_available():
            emit("—— manga-ocr 加载测试 ——")
            try:
                ocr._load_manga_model()
                emit("manga-ocr 模型加载成功")
            except Exception as exc:
                emit(f"manga-ocr 模型加载失败：{type(exc).__name__}: {exc}")

        try:
            images, _title = load_input_images(target)
        except Exception as exc:
            emit(f"打开失败：{exc}")
            images, code = [], 1
        else:
            page = PageModel(images[0])
            try:
                result = ocr.run_ocr(page.raw_image(), "auto")
            except Exception as exc:
                # Never let a diagnostic run die with a traceback dialog; the
                # whole point is to report failures readably.
                emit(f"识别过程异常：{type(exc).__name__}: {exc}")
                import traceback
                emit(traceback.format_exc())
                code = 1
            else:
                emit(f"识别成功：{result.ok}")
                emit(f"使用引擎：{result.backend}")
                if result.error:
                    emit(f"错误：{result.error}")
                emit("识别结果：")
                emit(result.text)
                code = 0 if result.ok else 1

    try:
        log = cache_dir() / "selfcheck_ocr.txt"
        log.write_text("\n".join(lines) + "\n", encoding="utf-8-sig")
        emit(f"（报告已写入 {log}）")
    except Exception:
        pass

    del app
    return code


def _install_excepthook() -> None:
    """Replace the default traceback dialog with something actionable.

    A windowed exe shows an unhandled exception as a bare traceback box, which
    tells the user nothing and looks like a crash. Log the full detail to a file
    and show a short message instead.
    """
    import traceback

    from mangatrans.config import cache_dir

    def hook(exc_type, exc_value, exc_tb) -> None:
        detail = "".join(traceback.format_exception(exc_type, exc_value, exc_tb))
        log_path = ""
        try:
            log = cache_dir() / "last_error.txt"
            log.write_text(detail, encoding="utf-8-sig")
            log_path = str(log)
        except Exception:
            pass

        # Console / self-test runs must never block on a modal dialog: that
        # would hang a headless run waiting for a click nobody can make.
        if not sys.stdout or not sys.stdout.isatty():
            try:
                print(detail, file=sys.stderr)
            except Exception:
                pass
            return

        try:
            from PySide6.QtWidgets import QMessageBox
            box = QMessageBox()
            box.setIcon(QMessageBox.Critical)
            box.setWindowTitle("MangaTrans 遇到错误")
            box.setText(f"{exc_type.__name__}: {exc_value}")
            box.setInformativeText(
                "程序没有退出，可以继续操作。\n"
                + (f"详细信息已写入：\n{log_path}" if log_path
                   else "详细信息：\n" + detail[-800:]))
            box.exec()
        except Exception:
            pass

    sys.excepthook = hook


def _selfcheck_notify() -> int:
    """Open every notice style once, then quit.

    Used to verify objectively that no system sound is produced: the caller
    measures the default audio device's peak meter while this runs.
    """
    from PySide6.QtCore import QTimer

    from mangatrans.notify import NoticeOverlay

    app = QApplication(sys.argv)
    app.setApplicationName(APP_NAME)
    app.setApplicationDisplayName(APP_TITLE)
    apply_theme(app)

    window = MainWindow()
    window.resize(1100, 760)
    window.show()

    steps = [
        lambda: window.show_help(),
        lambda: window.show_license(),
        lambda: window.show_contact(),
        lambda: window.show_about(),
    ]
    state = {"i": 0}

    def close_top() -> None:
        for ov in window.findChildren(NoticeOverlay):
            if ov.isVisible():
                ov._finish(1)

    def next_step() -> None:
        close_top()
        if state["i"] >= len(steps):
            print("NOTIFY_OK windows=%d" % len(
                [w for w in app.topLevelWidgets() if w.isVisible()]))
            app.quit()
            return
        steps[state["i"]]()
        state["i"] += 1
        QTimer.singleShot(900, next_step)

    QTimer.singleShot(900, next_step)
    return app.exec()


def main() -> int:
    if "--selfcheck-ocr" in sys.argv:
        return _selfcheck_ocr()
    if "--selfcheck-notify" in sys.argv:
        return _selfcheck_notify()

    # Qt 6 enables high-DPI scaling and pixmaps unconditionally; the Qt 5
    # attributes are deprecated warnings in Qt 6, so nothing to set here.
    app = QApplication(sys.argv)
    _install_excepthook()
    app.setApplicationName(APP_NAME)
    app.setApplicationDisplayName(APP_TITLE)
    app.setFont(QFont("Microsoft YaHei UI", 9))
    apply_theme(app)

    # Apply the saved UI language before any window is built.
    from mangatrans import i18n
    from mangatrans.config import AppConfig as _Cfg
    i18n.set_language(_Cfg.load().language)

    window = MainWindow()
    window.show()

    args = [a for a in sys.argv[1:] if not a.startswith("-")]
    if args:
        from pathlib import Path
        path = Path(args[0])
        if path.exists():
            window.open_path(path)

    return app.exec()


if __name__ == "__main__":
    os.environ.setdefault("QT_ENABLE_HIGHDPI_SCALING", "1")
    sys.exit(main())
