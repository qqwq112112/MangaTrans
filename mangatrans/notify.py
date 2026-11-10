# -*- coding: utf-8 -*-
"""Theme-consistent, silent notifications.

The application used QMessageBox everywhere, which has three problems:
  * it looks like a Windows dialog, not like the rest of the app;
  * some platforms play a system beep ("ding") for every alert;
  * routine confirmations block the UI and steal keyboard focus.

This module replaces it with two things:
  * `toast()`  - a small floating banner that fades out on its own, never takes
                 focus, never makes a sound. Used for anything informational.
  * `alert()` / `confirm()` - real but restyled QDialogs for the few cases that
                 genuinely need an answer (destructive actions, fatal errors).
"""

from __future__ import annotations

from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QTextBrowser,
    QVBoxLayout,
    QWidget,
)

# Palette mirrors mangatrans/theme.py so notifications never look foreign.
_STYLES = {
    "info": ("#14312e", "#9ff3e8", "#1f9c8d"),      # teal
    "success": ("#14312e", "#9ff3e8", "#1f9c8d"),
    "warning": ("#3a2f1c", "#ffd79a", "#8a6a2a"),   # amber
    "error": ("#3a1d22", "#ffb3bd", "#8a3b48"),     # red
}

_DIALOG_QSS = """
QDialog { background: #0f1319; }
QFrame#NoticePanel {
    background: #151b24;
    border: 1px solid #28313f;
    border-radius: 12px;
}
QLabel#NoticeTitle { font-size: 14px; font-weight: 600; }
QLabel#NoticeBody { color: #b9c4d2; font-size: 13px; }
"""

# Rich-text rules applied to the notice body. Qt honours line-height and
# paragraph margins here, which is what makes Chinese text readable: without
# it, wrapped lines sat ~3px apart while paragraphs had ~30px, so the block
# looked both cramped and unevenly spaced.
_BODY_CSS = """
p { margin-top: 0px; margin-bottom: 9px; line-height: 168%; }
p.tight { margin-bottom: 4px; }
h4 { margin-top: 2px; margin-bottom: 4px; font-size: 13px; }
ul, ol { margin-top: 0px; margin-bottom: 9px; margin-left: 14px; }
li { margin-bottom: 3px; line-height: 168%; }
"""


class ToastLabel(QLabel):
    """Frameless, click-through banner pinned to the bottom of its parent."""

    def __init__(self, parent: QWidget):
        super().__init__(parent)
        self.setAlignment(Qt.AlignCenter)
        self.setAttribute(Qt.WA_TransparentForMouseEvents, True)
        self.setWordWrap(False)
        self.hide()
        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.timeout.connect(self.hide)

    def flash(self, message: str, kind: str = "info", msec: int = 2400,
              above: int = 0) -> None:
        bg, fg, border = _STYLES.get(kind, _STYLES["info"])
        self.setStyleSheet(
            f"QLabel{{background:{bg}; color:{fg}; border:1px solid {border};"
            "border-radius:10px; padding:8px 18px; font-size:13px;}")
        self.setText(message)
        self.adjustSize()
        parent = self.parentWidget()
        if parent is not None:
            x = (parent.width() - self.width()) // 2
            y = parent.height() - self.height() - 22 - max(0, above)
            self.move(max(6, x), max(6, y))
        self.show()
        self.raise_()
        self._timer.start(int(msec))


def _toast_for(parent: QWidget) -> ToastLabel:
    toast = getattr(parent, "_notice_toast", None)
    if toast is None or not isinstance(toast, ToastLabel):
        toast = ToastLabel(parent)
        parent._notice_toast = toast          # keep a strong reference
    return toast


def toast(parent: QWidget | None, message: str, kind: str = "info",
          msec: int = 2400, above: int = 0) -> None:
    """Show a non-blocking, silent banner. Safe to call with parent=None."""
    if parent is None:
        return
    _toast_for(parent).flash(message, kind, msec, above)


class NoticeOverlay(QWidget):
    """Modal-looking notice drawn INSIDE the parent window.

    Why not a QDialog: creating and activating a new top-level window makes
    Windows play its "window opened / focus changed" system sound on some
    sound schemes, which is exactly what we are trying to avoid. Painting an
    overlay on the existing window produces no window event at all, keeps the
    app palette, and looks consistent with the rest of the UI.

    Body rendering uses QTextBrowser rather than QLabel: a wrapping QLabel
    reports a height hint that the layout does not always honour, which clipped
    the last lines of longer messages ("联系作者" lost its GitHub/email rows).
    QTextBrowser measures its document against a known width, so the card is
    always tall enough, and it scrolls if the text exceeds the window.
    """

    MIN_W = 420
    MAX_W = 640
    SIDE_MARGIN = 60

    def __init__(self, parent: QWidget, title: str, body: str, kind: str,
                 buttons: list[tuple[str, int, str]]):
        super().__init__(parent)
        self._result = 0
        self._buttons = buttons
        self.setObjectName("NoticeOverlay")
        self.setAttribute(Qt.WA_StyledBackground, True)
        self.setStyleSheet(
            "QWidget#NoticeOverlay{background:rgba(6,9,13,190);}")

        outer = QVBoxLayout(self)
        outer.setContentsMargins(self.SIDE_MARGIN, 36, self.SIDE_MARGIN, 36)
        outer.addStretch(1)

        self._card = QFrame()
        self._card.setObjectName("NoticePanel")
        self._card.setStyleSheet(_DIALOG_QSS)
        outer.addWidget(self._card, 0, Qt.AlignHCenter)
        outer.addStretch(1)

        lay = QVBoxLayout(self._card)
        lay.setContentsMargins(22, 18, 22, 16)
        lay.setSpacing(12)

        _bg, fg, _border = _STYLES.get(kind, _STYLES["info"])
        self._head = QLabel(title)
        self._head.setObjectName("NoticeTitle")
        self._head.setWordWrap(True)
        self._head.setStyleSheet(f"color:{fg};")
        lay.addWidget(self._head)

        self._body = QTextBrowser()
        self._body.setObjectName("NoticeBody")
        self._body.document().setDefaultStyleSheet(_BODY_CSS)
        self._body.setHtml(body)
        self._body.setOpenExternalLinks(True)
        self._body.setFrameShape(QFrame.NoFrame)
        self._body.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        self._body.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self._body.setStyleSheet(
            "QTextBrowser{background:transparent;border:none;"
            "color:#b9c4d2;font-size:13px;}")
        lay.addWidget(self._body)

        row = QHBoxLayout()
        row.addStretch(1)
        for label, result_id, role in buttons:
            btn = QPushButton(label)
            if role == "primary":
                btn.setObjectName("Primary")
            elif role == "danger":
                btn.setObjectName("Danger")
            btn.setMinimumWidth(92)
            btn.clicked.connect(lambda _c=False, r=result_id: self._finish(r))
            row.addWidget(btn)
        lay.addLayout(row)

        self._relayout()

    # ------------------------------------------------------------------ layout

    def _card_width(self) -> int:
        parent = self.parentWidget()
        avail = (parent.width() if parent else 900) - self.SIDE_MARGIN * 2
        return max(self.MIN_W, min(self.MAX_W, avail))

    def _relayout(self) -> None:
        """Size the card and body from the actual text height."""
        parent = self.parentWidget()
        parent_h = parent.height() if parent else 700

        width = self._card_width()
        self._card.setFixedWidth(width)

        # Measure against a DETERMINISTIC text width. Reading
        # viewport().width() before the widget is shown returns a value that
        # does not match the final layout, so the document wrapped differently
        # than it rendered and the last line was clipped (the email row of the
        # About dialog). Deriving the width from the card keeps both passes equal.
        layout_margins = 22 + 22            # card contentsMargins left+right
        doc_margin = 4 * 2                  # QTextDocument default margins
        text_w = max(120, width - layout_margins - doc_margin)
        doc = self._body.document()
        doc.setDocumentMargin(4)
        doc.setTextWidth(text_w)
        doc_h = int(doc.size().height())

        # Reserve room for the title, buttons and paddings, then cap the body so
        # the card always stays inside the window; only excess text scrolls.
        chrome = 116
        max_body = max(80, parent_h - chrome - 80)
        body_h = min(max(doc_h + 4, 40), max_body)
        self._body.setFixedHeight(body_h)
        self._body.setFixedWidth(text_w + doc_margin)
        # Exact height => no scrollbar; a capped height => scrollbar appears.
        self._body.setVerticalScrollBarPolicy(
            Qt.ScrollBarAlwaysOff if doc_h + 4 <= body_h else Qt.ScrollBarAsNeeded)

        self._card.adjustSize()

    def show_over(self) -> int:
        """Cover the parent and block until a button is pressed."""
        from PySide6.QtCore import QEventLoop
        parent = self.parentWidget()
        if parent is not None:
            self.setGeometry(parent.rect())
        self._relayout()
        loop = QEventLoop(self)
        self._loop = loop
        self.show()
        self.raise_()
        self.setFocus(Qt.OtherFocusReason)
        # Force a layout pass so heights are final before the screenshot/read.
        self._relayout()
        loop.exec()
        self.hide()
        self.deleteLater()
        return self._result

    def _finish(self, result_id: int) -> None:
        self._result = result_id
        self.close()

    def chosen(self) -> int:
        """Id of the pressed button (0 when dismissed without choosing)."""
        return self._result

    def closeEvent(self, event) -> None:
        loop = getattr(self, "_loop", None)
        if loop is not None and loop.isRunning():
            loop.quit()
        super().closeEvent(event)

    def resizeEvent(self, event) -> None:
        parent = self.parentWidget()
        if parent is not None:
            self.setGeometry(parent.rect())
        self._relayout()
        super().resizeEvent(event)


def _run_notice(parent, title, body, kind, buttons) -> int:
    """Show the overlay on the parent's window and return the chosen id."""
    host = parent
    if host is None:
        return 0
    # Cover the whole top-level window, not just the calling widget.
    top = host.window()
    overlay = NoticeOverlay(top, title, body, kind, buttons)
    return overlay.show_over()


def alert(parent: QWidget | None, title: str, body: str,
          kind: str = "warning", ok_text: str = "知道了") -> None:
    """Themed, silent replacement for QMessageBox.warning/information."""
    _run_notice(parent, title, body, kind, [(ok_text, 1, "primary")])


def confirm(parent: QWidget | None, title: str, body: str,
            kind: str = "warning", yes_text: str = "确定",
            no_text: str = "取消", danger: bool = False) -> bool:
    """Themed yes/no question. Returns True when the user confirms."""
    result = _run_notice(parent, title, body, kind, [
        (no_text, 0, "ghost"),
        (yes_text, 1, "danger" if danger else "primary"),
    ])
    return result == 1
