# -*- coding: utf-8 -*-
"""Zoomable manga canvas with long-press region selection."""

from __future__ import annotations

from dataclasses import dataclass

from PySide6.QtCore import QPoint, QPointF, QRectF, QSize, Qt, QTimer, Signal
from PySide6.QtGui import QColor, QFont, QPainter, QPen, QPixmap, QTransform
from PySide6.QtWidgets import (
    QGraphicsPixmapItem,
    QGraphicsRectItem,
    QGraphicsScene,
    QGraphicsSimpleTextItem,
    QGraphicsView,
)

from .document import BASE_PAGE_WIDTH, Document, PAGE_GAP
from .fill import color_at

VERTICAL_PIXMAP_WIDTH = 1600
HORIZONTAL_PIXMAP_WIDTH = 2800


@dataclass
class RegionDraft:
    page_index: int
    rect: QRectF        # normalized 0..1
    page_size: QSize    # original pixels


class PageItem(QGraphicsRectItem):
    """Scene item for one page. Coordinate unit = BASE_PAGE_WIDTH."""

    def __init__(self, index: int, page_size: QSize):
        self.index = index
        self.orig_size = QSize(page_size)
        self.base_w = BASE_PAGE_WIDTH
        self.base_h = (
            BASE_PAGE_WIDTH * page_size.height() / page_size.width()
            if page_size.width() > 0 else BASE_PAGE_WIDTH * 1.4
        )
        super().__init__(0, 0, self.base_w, self.base_h)
        self.setPen(QPen(QColor("#2c3444"), 1))
        self.setBrush(QColor("#161b24"))
        self.setAcceptedMouseButtons(Qt.NoButton)
        self.setFlag(QGraphicsRectItem.ItemIsSelectable, False)

        self._pixmap_item = QGraphicsPixmapItem(self)
        self._pixmap_item.setTransformationMode(Qt.SmoothTransformation)
        self._pixmap_item.setAcceptedMouseButtons(Qt.NoButton)
        self._pixmap_item.setZValue(0)

        self._placeholder = QGraphicsSimpleTextItem(f"第 {index + 1} 页", self)
        font = QFont("Microsoft YaHei")
        font.setPixelSize(24)
        self._placeholder.setFont(font)
        self._placeholder.setBrush(QColor("#5a6578"))
        self._placeholder.setZValue(1)
        self._place_placeholder()

        self._loaded = False

    def _place_placeholder(self) -> None:
        br = self._placeholder.boundingRect()
        self._placeholder.setPos(
            (self.base_w - br.width()) / 2.0,
            (self.base_h - br.height()) / 2.0,
        )

    @property
    def loaded(self) -> bool:
        return self._loaded

    def load_pixmap(self, pixmap: QPixmap) -> None:
        if pixmap.isNull() or pixmap.width() <= 0:
            return
        self._pixmap_item.setPixmap(pixmap)
        scale = self.base_w / float(pixmap.width())
        self._pixmap_item.setScale(scale)
        self._pixmap_item.setPos(0, 0)
        self._pixmap_item.show()
        self._placeholder.hide()
        self._loaded = True

    def unload_pixmap(self) -> None:
        self._pixmap_item.setPixmap(QPixmap())
        self._placeholder.show()
        self._loaded = False

    def add_overlay(self, rect: QRectF) -> QGraphicsRectItem:
        item = QGraphicsRectItem(rect, self)
        pen = QPen(QColor("#2dd4bf"), 2)
        pen.setCosmetic(True)
        pen.setStyle(Qt.DashLine)
        item.setPen(pen)
        item.setBrush(QColor(45, 212, 191, 48))
        item.setZValue(20)
        item.setAcceptedMouseButtons(Qt.NoButton)
        return item


class CanvasView(QGraphicsView):
    regionsConfirmed = Signal(list)     # list[RegionDraft]
    pageActivated = Signal(int)
    zoomChanged = Signal(int)           # percent relative to fit-width
    statusMessage = Signal(str)
    appliedOpContext = Signal(object)   # (page_index, op_index) under the cursor
    pendingChanged = Signal(int)        # number of un-confirmed selections

    LONG_PRESS_MS = 260

    def __init__(self, parent=None):
        super().__init__(parent)
        self._scene = QGraphicsScene(self)
        self.setScene(self._scene)
        self.setBackgroundBrush(QColor("#0e1116"))
        self._scene.setBackgroundBrush(QColor("#0e1116"))
        self.setRenderHints(
            QPainter.Antialiasing | QPainter.SmoothPixmapTransform | QPainter.TextAntialiasing
        )
        self.setDragMode(QGraphicsView.NoDrag)
        self.setTransformationAnchor(QGraphicsView.AnchorUnderMouse)
        self.setResizeAnchor(QGraphicsView.AnchorViewCenter)
        self.setViewportUpdateMode(QGraphicsView.SmartViewportUpdate)
        self.setFrameShape(QGraphicsView.NoFrame)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        self.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        self.setFocusPolicy(Qt.StrongFocus)

        self.doc: Document | None = None
        self.mode = "horizontal"
        self.current = 0
        self._items: list[PageItem] = []
        self._fit_mode: str | None = "width"

        # Long press / selection state
        self._long_press = QTimer(self)
        self._long_press.setSingleShot(True)
        self._long_press.setInterval(self.LONG_PRESS_MS)
        self._long_press.timeout.connect(self._start_selection)

        self._mouse_down = False
        self._maybe_select = False
        self._selecting = False
        self._panning = False
        self._press_screen = QPoint()
        self._press_scene = QPointF()
        # Pan state: float accumulator in scene units + last widget position.
        self._pan_widget = QPointF()
        self._pan_accum = QPointF()
        self._anchor = QPointF()
        self._sel_item: QGraphicsRectItem | None = None
        self._sel_page: PageItem | None = None

        self._pending: list[tuple[int, QGraphicsRectItem, RegionDraft]] = []
        self._dialog_open = False

        self._pick_mode = False
        self._pick_cb = None

        self._visible_timer = QTimer(self)
        self._visible_timer.setSingleShot(True)
        self._visible_timer.setInterval(50)
        self._visible_timer.timeout.connect(self._update_visible_and_current)

        self.verticalScrollBar().valueChanged.connect(self._schedule_visible)
        self.horizontalScrollBar().valueChanged.connect(self._schedule_visible)

    # ------------------------------------------------------------------ document

    def set_document(self, doc: Document) -> None:
        self.clear_pending()
        self.doc = doc
        self.current = 0
        self._scene.clear()
        self._items = []
        for i in range(doc.page_count):
            item = PageItem(i, doc.original_size(i))
            self._scene.addItem(item)
            self._items.append(item)
        self._layout_items()
        # On open, fill the window so the page appears as large as possible
        # without stretching. "page" = contain (uniform scale); vertical mode
        # overrides this to width-fit internally.
        self._fit_mode = "page"
        self._apply_fit()
        self._load_current()
        self.pageActivated.emit(0)
        self._schedule_visible()

    def set_mode(self, mode: str) -> None:
        if mode not in ("horizontal", "vertical") or mode == self.mode:
            return
        self.mode = mode
        self.clear_pending()
        self._layout_items()
        self._fit_mode = "width" if mode == "vertical" else "page"
        self._apply_fit()
        if mode == "vertical":
            self.go_to_page(self.current)
        else:
            self._load_current()
        self.pageActivated.emit(self.current)

    def _layout_items(self) -> None:
        if not self._items:
            return
        if self.mode == "vertical":
            y = 0.0
            for item in self._items:
                item.setVisible(True)
                item.setPos(0, y)
                y += item.base_h + PAGE_GAP
            self.setSceneRect(-30, -20, BASE_PAGE_WIDTH + 60, y + PAGE_GAP)
        else:
            for i, item in enumerate(self._items):
                item.setPos(0, 0)
                item.setVisible(i == self.current)
            item = self._items[self.current]
            self.setSceneRect(-30, -20, BASE_PAGE_WIDTH + 60, item.base_h + 40)

    # ------------------------------------------------------------------ zoom / fit

    def _fit_scale(self) -> float | None:
        """Uniform scale that makes the page fill the viewport as much as possible.

        "Fill" here means *contain*: the largest scale where the whole page is
        still visible. Scaling x and y by the same factor is what keeps the
        page's aspect ratio intact - a non-uniform scale would stretch the
        artwork. This only touches the view transform; PageModel geometry and
        the export path are never modified.
        """
        vw = max(100, self.viewport().width())
        vh = max(100, self.viewport().height())
        margin = 24.0

        if self.mode == "vertical":
            # Continuous scrolling: width-fit is the only sane choice, because
            # fitting the whole (very tall) strip into the viewport would make
            # the text unreadably small.
            return (vw - margin) / BASE_PAGE_WIDTH
        if not self._items:
            return None

        item = self._items[self.current]
        if self._fit_mode == "width":
            return (vw - margin) / BASE_PAGE_WIDTH
        if self._fit_mode == "page":
            scale_x = (vw - margin) / BASE_PAGE_WIDTH
            scale_y = (vh - margin) / max(1.0, item.base_h)
            return min(scale_x, scale_y)
        return None

    def _apply_fit(self) -> None:
        scale = self._fit_scale()
        if scale is None:
            return
        self._set_scale(max(0.02, scale))

    def fit_width(self) -> None:
        self._fit_mode = "width"
        self._apply_fit()
        if self.mode == "vertical":
            self.go_to_page(self.current)
        else:
            self.centerOn(self._items[self.current])

    def fit_page(self) -> None:
        """Fit the whole page in the window (contain, uniform scale)."""
        if self.mode != "horizontal":
            self.fit_width()
            return
        self._fit_mode = "page"
        self._apply_fit()
        self.centerOn(self._items[self.current])

    def actual_size(self) -> None:
        """Display the page at its original pixel size (1 image pixel = 1 screen px)."""
        if not self.doc:
            return
        self._fit_mode = None
        orig_w = self.doc.original_size(self.current).width() or int(BASE_PAGE_WIDTH)
        self._set_scale(max(0.02, orig_w / BASE_PAGE_WIDTH))
        self.centerOn(self._items[self.current])

    def _set_scale(self, scale: float) -> None:
        self.setTransformationAnchor(QGraphicsView.AnchorViewCenter)
        self.setTransform(QTransform().scale(scale, scale))
        self.setTransformationAnchor(QGraphicsView.AnchorUnderMouse)
        self._emit_zoom()
        self._schedule_visible()

    def _emit_zoom(self) -> None:
        baseline = max(1.0, (max(100, self.viewport().width()) - 40.0) / BASE_PAGE_WIDTH)
        percent = int(round(self.transform().m11() / baseline * 100))
        self.zoomChanged.emit(percent)

    def wheelEvent(self, event) -> None:
        delta = event.angleDelta().y()
        if delta == 0:
            return
        if event.modifiers() & Qt.ShiftModifier:
            self.verticalScrollBar().setValue(self.verticalScrollBar().value() - delta)
            event.accept()
            return
        factor = 1.0018 ** delta
        new_scale = self.transform().m11() * factor
        if 0.02 <= new_scale <= 16.0:
            self._fit_mode = None
            self.setTransformationAnchor(QGraphicsView.AnchorUnderMouse)
            self.scale(factor, factor)
            self._emit_zoom()
            self._schedule_visible()
        event.accept()

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        if self._fit_mode in ("width", "page"):
            self._apply_fit()
        else:
            self._emit_zoom()
        self._schedule_visible()

    # ------------------------------------------------------------------ page nav

    def go_to_page(self, index: int) -> None:
        if not self._items:
            return
        index = max(0, min(len(self._items) - 1, int(index)))
        changed = index != self.current
        self.current = index
        if self.mode == "horizontal":
            if changed:
                self.clear_pending()
            self._layout_items()
            self._load_current()
            if self._fit_mode:
                self._apply_fit()
            self.centerOn(self._items[index])
        else:
            item = self._items[index]
            self._load_item(item)
            self.scroll_to_page_top(item)
            # Vertical mode derives "current page" from the scroll position, so
            # pin it and cancel any pending recompute that could fight us.
            self.current = index
        if changed:
            self.pageActivated.emit(index)
        self._schedule_visible()

    def scroll_to_page_top(self, item: "PageItem") -> None:
        """Scroll so the page's top edge sits at the viewport top.

        Scrollbar values are VIEWPORT PIXELS while item.pos() is in SCENE units.
        Assigning one to the other only worked at 100% zoom; at any other scale
        the view landed on the wrong page (or nowhere at all), which is what
        made page navigation feel broken in vertical mode.
        """
        vbar = self.verticalScrollBar()
        top_scene = item.sceneBoundingRect().top()
        # Where that scene point currently sits in the viewport, in pixels.
        offset = self.mapFromScene(QPointF(0.0, top_scene)).y()
        vbar.setValue(vbar.value() + int(round(offset)))

    def next_page(self) -> None:
        self.go_to_page(self.current + 1)

    def prev_page(self) -> None:
        self.go_to_page(self.current - 1)

    def _load_current(self) -> None:
        if self._items:
            self._load_item(self._items[self.current])

    def _load_item(self, item: PageItem) -> None:
        if item.loaded or not self.doc:
            return
        width = VERTICAL_PIXMAP_WIDTH if self.mode == "vertical" else HORIZONTAL_PIXMAP_WIDTH
        try:
            item.load_pixmap(self.doc.page_pixmap(item.index, width))
        except Exception:
            pass

    def refresh_page(self, index: int) -> None:
        if not self._items or index < 0 or index >= len(self._items):
            return
        item = self._items[index]
        item.unload_pixmap()
        self.doc.pages[index].invalidate()
        self._load_item(item)

    def _schedule_visible(self) -> None:
        if self.doc:
            self._visible_timer.start()

    def _update_visible_and_current(self) -> None:
        if not self.doc or not self._items:
            return
        vp = self.mapToScene(self.viewport().rect()).boundingRect()

        if self.mode == "horizontal":
            self._load_item(self._items[self.current])
            return

        margin = vp.adjusted(0, -vp.height() * 0.75, 0, vp.height() * 0.75)
        pending_pages = {idx for idx, _o, _d in self._pending}
        for item in self._items:
            sr = item.sceneBoundingRect()
            if sr.intersects(margin):
                self._load_item(item)
            elif item.loaded and item.index not in pending_pages:
                far = vp.adjusted(0, -vp.height(), 0, vp.height())
                if not sr.intersects(far):
                    item.unload_pixmap()
                    self.doc.pages[item.index].invalidate()

        # In horizontal (single-page) mode the current page is whatever the user
        # navigated to - only one page is visible, so deriving it from the
        # viewport is redundant and actively harmful: it silently reverts page
        # changes made during a history restore.
        if self.mode == "horizontal":
            return

        # Vertical mode scrolls continuously, so the current page really is
        # "the first page still visible at the top".
        top = vp.top()
        current = self.current
        for item in self._items:
            if item.sceneBoundingRect().bottom() > top:
                current = item.index
                break
        if current != self.current:
            self.current = current
            self.pageActivated.emit(current)

    # ------------------------------------------------------------------ selection

    def _page_item_at(self, scene_pos: QPointF) -> PageItem | None:
        for it in self._scene.items(scene_pos):
            node = it
            while node is not None:
                if isinstance(node, PageItem):
                    return node
                node = node.parentItem()
        return None

    def mousePressEvent(self, event) -> None:
        if event.button() == Qt.LeftButton and self._pick_mode:
            self._do_pick(event.position().toPoint())
            event.accept()
            return
        if event.button() == Qt.MiddleButton:
            self._begin_pan(event.position().toPoint())
            self.viewport().setCursor(Qt.ClosedHandCursor)
            event.accept()
            return
        if event.button() == Qt.LeftButton:
            self._press_screen = event.position().toPoint()
            self._press_scene = self.mapToScene(self._press_screen)
            self._mouse_down = True
            self._maybe_select = True
            self._panning = False
            self._long_press.start()
            event.accept()
            return
        super().mousePressEvent(event)

    def _begin_pan(self, pos: QPoint) -> None:
        """Start panning from a widget-space position.

        The scroll offset is tracked as a float accumulator. Setting the
        scrollbars directly from a delta and letting them truncate to int
        loses up to one scene unit per move event; at 400% zoom that is 4-8
        screen pixels *per move*, which is exactly the jitter this replaces.
        """
        self._panning = True
        self._pan_widget = QPointF(pos)
        self._pan_accum = QPointF(self.horizontalScrollBar().value(),
                                  self.verticalScrollBar().value())

    def mouseMoveEvent(self, event) -> None:
        pos = event.position().toPoint()
        if self._selecting and self._sel_item is not None and self._sel_page is not None:
            local = self._sel_page.mapFromScene(self.mapToScene(pos))
            x = max(0.0, min(self._sel_page.base_w, local.x()))
            y = max(0.0, min(self._sel_page.base_h, local.y()))
            rect = QRectF(self._anchor, QPointF(x, y)).normalized()
            self._sel_item.setRect(rect)
            event.accept()
            return

        if self._maybe_select and (pos - self._press_screen).manhattanLength() > 8:
            self._long_press.stop()
            self._maybe_select = False
            self._begin_pan(pos)
            self.viewport().setCursor(Qt.ClosedHandCursor)

        if self._panning:
            self._pan_to(pos)
            event.accept()
            return

        super().mouseMoveEvent(event)

    def _pan_to(self, pos: QPoint) -> None:
        """Move the view so the grabbed point stays under the cursor."""
        scale = max(0.0001, self.transform().m11())
        delta = QPointF(pos) - self._pan_widget
        self._pan_widget = QPointF(pos)

        # Widget pixels -> scene units, accumulated without truncation.
        self._pan_accum = QPointF(
            self._pan_accum.x() - delta.x() / scale,
            self._pan_accum.y() - delta.y() / scale,
        )

        hbar = self.horizontalScrollBar()
        vbar = self.verticalScrollBar()
        new_x = int(round(self._pan_accum.x()))
        new_y = int(round(self._pan_accum.y()))
        hbar.setValue(new_x)
        vbar.setValue(new_y)

        # A scrollbar clamps at its ends. Without resyncing the accumulator the
        # next move would compare against a position the view never reached,
        # producing a visible jump when the user reverses direction.
        if hbar.value() != new_x:
            self._pan_accum.setX(float(hbar.value()))
        if vbar.value() != new_y:
            self._pan_accum.setY(float(vbar.value()))

    def mouseReleaseEvent(self, event) -> None:
        if event.button() == Qt.LeftButton:
            self._long_press.stop()
            if self._selecting:
                self._finish_selection()
            self._selecting = False
            self._maybe_select = False
            self._panning = False
            self._mouse_down = False
            if not self._pick_mode:
                self.viewport().unsetCursor()
            event.accept()
            return
        if event.button() == Qt.MiddleButton:
            self._panning = False
            self.viewport().unsetCursor()
            event.accept()
            return
        super().mouseReleaseEvent(event)

    def _start_selection(self) -> None:
        if not self._mouse_down or not self._maybe_select or not self.doc:
            return
        item = self._page_item_at(self._press_scene)
        if item is None:
            return
        self._maybe_select = False
        self._selecting = True
        self._sel_page = item
        local = item.mapFromScene(self._press_scene)
        self._anchor = QPointF(
            max(0.0, min(item.base_w, local.x())),
            max(0.0, min(item.base_h, local.y())),
        )
        self._sel_item = item.add_overlay(QRectF(self._anchor, self._anchor))
        self.viewport().setCursor(Qt.CrossCursor)
        self.statusMessage.emit("拖动框选文字区域，松开后右击确认")

    def _finish_selection(self) -> None:
        if self._sel_item is None or self._sel_page is None:
            return
        rect = QRectF(self._sel_item.rect())
        item = self._sel_page
        if rect.width() < 6 or rect.height() < 6:
            self._scene.removeItem(self._sel_item)
        else:
            draft = RegionDraft(
                page_index=item.index,
                rect=QRectF(
                    rect.x() / item.base_w,
                    rect.y() / item.base_h,
                    rect.width() / item.base_w,
                    rect.height() / item.base_h,
                ),
                page_size=QSize(item.orig_size),
            )
            self._pending.append((item.index, self._sel_item, draft))
            self.pendingChanged.emit(len(self._pending))
            self.statusMessage.emit(
                f"已框选 {len(self._pending)} 处 · 可继续长按框选 · "
                f"右击确认 · Esc 取消"
            )
        self._sel_item = None
        self._sel_page = None
        self.viewport().unsetCursor()

    def clear_pending(self) -> None:
        for _idx, overlay, _draft in self._pending:
            try:
                self._scene.removeItem(overlay)
            except Exception:
                pass
        self._pending.clear()
        if self._sel_item is not None:
            try:
                self._scene.removeItem(self._sel_item)
            except Exception:
                pass
            self._sel_item = None
            self._sel_page = None
        self._selecting = False
        self.pendingChanged.emit(0)
        self.statusMessage.emit("已清除选区")

    def undo_last_pending(self) -> bool:
        """Remove the most recently drawn selection box."""
        if not self._pending:
            return False
        _index, overlay, _draft = self._pending.pop()
        try:
            self._scene.removeItem(overlay)
        except Exception:
            pass
        self.pendingChanged.emit(len(self._pending))
        self.statusMessage.emit(
            f"已移除最后一处选区 · 剩余 {len(self._pending)} 处")
        return True

    def end_selection_session(self, accepted: bool) -> None:
        self._dialog_open = False
        if accepted:
            self.clear_pending()

    def contextMenuEvent(self, event) -> None:
        if self._selecting:
            event.accept()
            return
        if self._pending and not self._dialog_open:
            self._dialog_open = True
            self.regionsConfirmed.emit([d for _i, _o, d in self._pending])
            event.accept()
            return
        if not self._pending:
            hit = self._op_at(self.mapToScene(event.pos()))
            if hit is not None:
                self.appliedOpContext.emit(hit)
                event.accept()
                return
            self.statusMessage.emit("请先用左键长按并拖动框选文字区域，再右击确认")
        event.accept()

    def _op_at(self, scene_pos: QPointF):
        """Return (page_index, op_index) of an applied region under the cursor."""
        if not self.doc:
            return None
        item = self._page_item_at(scene_pos)
        if item is None:
            return None
        local = item.mapFromScene(scene_pos)
        nx = local.x() / item.base_w
        ny = local.y() / item.base_h
        # Later ops are painted last, so walk backwards.
        for op_index in range(len(self.doc.pages[item.index].ops) - 1, -1, -1):
            r = self.doc.pages[item.index].ops[op_index].rect
            if r.contains(QPointF(nx, ny)):
                return (item.index, op_index)
        return None

    # ------------------------------------------------------------------ eyedropper

    def begin_color_pick(self, callback) -> None:
        self._pick_mode = True
        self._pick_cb = callback
        self.viewport().setCursor(Qt.CrossCursor)
        self.statusMessage.emit("吸管模式：点击画布吸取颜色，Esc 取消")

    def cancel_color_pick(self) -> None:
        if not self._pick_mode:
            return
        cb = self._pick_cb
        self._pick_mode = False
        self._pick_cb = None
        self.viewport().unsetCursor()
        if cb is not None:
            cb(None)

    def _clear_pick_state(self) -> None:
        self._pick_mode = False
        self._pick_cb = None
        self.viewport().unsetCursor()

    def _do_pick(self, view_pos: QPoint) -> None:
        scene_pos = self.mapToScene(view_pos)
        item = self._page_item_at(scene_pos)
        if item is None:
            return
        local = item.mapFromScene(scene_pos)
        nx = max(0.0, min(0.999999, local.x() / item.base_w))
        ny = max(0.0, min(0.999999, local.y() / item.base_h))
        try:
            pixmap = self.doc.page_pixmap(item.index, HORIZONTAL_PIXMAP_WIDTH)
            color = color_at(pixmap.toImage(), nx, ny)
        except Exception:
            color = QColor("#FFFFFF")
        cb = self._pick_cb
        self._clear_pick_state()
        if cb is not None:
            cb(color)

    # ------------------------------------------------------------------ keyboard

    def keyPressEvent(self, event) -> None:
        key = event.key()
        if key == Qt.Key_Escape:
            if self._pick_mode:
                self.cancel_color_pick()
                self.statusMessage.emit("已取消吸管")
                return
            if self._pending:
                self.clear_pending()
                return
        elif key in (Qt.Key_Left, Qt.Key_Right):
            if self.mode == "horizontal":
                self.prev_page() if key == Qt.Key_Left else self.next_page()
                return
        elif key == Qt.Key_PageUp:
            self.prev_page()
            return
        elif key == Qt.Key_PageDown:
            self.next_page()
            return
        elif key in (Qt.Key_Plus, Qt.Key_Equal):
            self._zoom_by(1.2)
            return
        elif key == Qt.Key_Minus:
            self._zoom_by(1 / 1.2)
            return
        elif key == Qt.Key_0:
            self.fit_width()
            return
        super().keyPressEvent(event)

    def _zoom_by(self, factor: float) -> None:
        s = self.transform().m11() * factor
        if 0.02 <= s <= 16.0:
            self._fit_mode = None
            self.setTransformationAnchor(QGraphicsView.AnchorViewCenter)
            self.scale(factor, factor)
            self.setTransformationAnchor(QGraphicsView.AnchorUnderMouse)
            self._emit_zoom()
            self._schedule_visible()

    # ------------------------------------------------------------------ misc

    @property
    def pending_count(self) -> int:
        return len(self._pending)
