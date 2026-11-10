# -*- coding: utf-8 -*-
"""Reusable small widgets: colour swatch button, region preview."""

from __future__ import annotations

from PySide6.QtCore import QPointF, QRectF, QSize, Qt, Signal
from PySide6.QtGui import QColor, QPainter, QPainterPath, QPen, QPixmap
from PySide6.QtWidgets import QPushButton, QSizePolicy, QWidget

from .textrender import RegionOp, draw_region

# Handle hit radius (px) and the drawn handle size.
HIT = 10.0
HANDLE = 3.1
MIN_SIZE = 0.012


class SwatchButton(QPushButton):
    """Small clickable colour chip."""

    picked = Signal(QColor)

    def __init__(self, color: QColor | str, tooltip: str = "", parent=None):
        super().__init__(parent)
        self._color = QColor(color)
        self.setFixedSize(QSize(26, 26))
        self.setCursor(Qt.PointingHandCursor)
        self.setToolTip(tooltip)
        self.setStyleSheet("border: none; background: transparent;")
        self.clicked.connect(lambda: self.picked.emit(QColor(self._color)))

    def set_color(self, color: QColor | str) -> None:
        self._color = QColor(color)
        self.update()

    def paintEvent(self, event) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing, True)
        rect = QRectF(1.5, 1.5, self.width() - 3, self.height() - 3)
        painter.setBrush(self._color)
        lum = 0.299 * self._color.red() + 0.587 * self._color.green() + 0.114 * self._color.blue()
        painter.setPen(QPen(QColor("#3b475a") if lum < 60 else QColor("#2a3240"), 1))
        painter.drawRoundedRect(rect, 7, 7)


class ColorWell(QWidget):
    """Read-only colour preview with hex label."""

    def __init__(self, color: QColor | str = "#FFFFFF", parent=None):
        super().__init__(parent)
        self._color = QColor(color)
        self.setFixedHeight(30)
        self.setMinimumWidth(96)

    def set_color(self, color: QColor | str) -> None:
        self._color = QColor(color)
        self.update()

    def color(self) -> QColor:
        return QColor(self._color)

    def paintEvent(self, event) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing, True)
        rect = QRectF(1, 1, self.width() - 2, self.height() - 2)
        painter.setBrush(self._color)
        painter.setPen(QPen(QColor("#2a3240"), 1))
        painter.drawRoundedRect(rect, 7, 7)
        lum = 0.299 * self._color.red() + 0.587 * self._color.green() + 0.114 * self._color.blue()
        painter.setPen(QColor("#111111") if lum > 150 else QColor("#FFFFFF"))
        painter.drawText(rect, Qt.AlignCenter, self._color.name().upper())


class RegionPreview(QWidget):
    """Shows the page context around a region with the operation applied live.

    The dashed box is interactive: drag inside to move the region, drag an
    edge or corner to resize it. This is what makes the selection adjustable
    both before and after the translation has been written to the page.
    """

    CONTEXT = 0.42   # extra margin around the region, relative to region size

    rectChanged = Signal(QRectF)      # normalized, emitted while dragging
    rectCommitted = Signal(QRectF)    # normalized, emitted on mouse release
    strokesChanged = Signal()         # freehand strokes were added/cleared
    polygonChanged = Signal()         # custom fill outline was traced

    # Interaction modes.
    MODE_RECT = "rect"
    MODE_BRUSH = "brush"
    MODE_POLYGON = "polygon"

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setMinimumSize(QSize(360, 380))
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self.setMouseTracking(True)
        self._pixmap = QPixmap()
        self._op: RegionOp | None = None
        self._handle: str | None = None
        self._press_pos = QPointF()
        self._press_rect = QRectF()
        self._hover: str | None = None

        # Freehand editing
        self._mode = self.MODE_RECT
        self._brush_color = QColor("#FFFFFF")
        self._brush_width = 0.006        # ratio of page width
        self._drawing_points: list[tuple[float, float]] = []
        self._polygon_points: list[tuple[float, float]] = []

    # ------------------------------------------------------------------ state

    def set_scene(self, pixmap: QPixmap, op: RegionOp | None) -> None:
        self._pixmap = pixmap
        self._op = op
        self.update()

    def set_op(self, op: RegionOp | None) -> None:
        self._op = op
        self.update()

    # ------------------------------------------------------------------ modes

    def set_mode(self, mode: str) -> None:
        self._mode = mode
        self._drawing_points = []
        self._polygon_points = []
        self.setCursor(Qt.CrossCursor if mode != self.MODE_RECT else Qt.ArrowCursor)
        self.update()

    @property
    def mode(self) -> str:
        return self._mode

    def set_brush(self, color: QColor, width_ratio: float) -> None:
        self._brush_color = QColor(color)
        self._brush_width = max(0.0005, float(width_ratio))

    def clear_strokes(self) -> None:
        if self._op is not None and self._op.strokes:
            self._op.strokes.clear()
            self.strokesChanged.emit()
            self.update()

    def clear_polygon(self) -> None:
        if self._op is not None:
            self._op.fill_polygon = []
            self.polygonChanged.emit()
            self.update()

    @property
    def editable(self) -> bool:
        return self._op is not None and not self._pixmap.isNull()

    # ------------------------------------------------------------------ geometry

    def _geometry(self):
        """Return (inner, view, scale) in widget coords, or None."""
        if self._pixmap.isNull() or self._op is None:
            return None
        pw, ph = self._pixmap.width(), self._pixmap.height()
        r = self._op.rect
        region = QRectF(r.x() * pw, r.y() * ph, r.width() * pw, r.height() * ph)

        mx = region.width() * self.CONTEXT + 8
        my = region.height() * self.CONTEXT + 8
        view = region.adjusted(-mx, -my, mx, my).intersected(QRectF(0, 0, pw, ph))
        if view.width() <= 0 or view.height() <= 0:
            return None

        outer = QRectF(self.rect()).adjusted(1, 1, -1, -1)
        inner = outer.adjusted(8, 8, -8, -8)
        if inner.width() <= 4 or inner.height() <= 4:
            return None

        # Expand the view to the preview's aspect ratio so the panel is fully used.
        target_ratio = inner.width() / max(1.0, inner.height())
        cx, cy = view.center().x(), view.center().y()
        vw, vh = view.width(), view.height()
        if vw / vh < target_ratio:
            vw = vh * target_ratio
        else:
            vh = vw / target_ratio
        view = QRectF(cx - vw / 2.0, cy - vh / 2.0, vw, vh)

        if view.width() > pw:
            view.setLeft(0)
            view.setWidth(pw)
        elif view.left() < 0:
            view.moveLeft(0)
        elif view.right() > pw:
            view.moveRight(pw)
        if view.height() > ph:
            view.setTop(0)
            view.setHeight(ph)
        elif view.top() < 0:
            view.moveTop(0)
        elif view.bottom() > ph:
            view.moveBottom(ph)

        scale = min(inner.width() / view.width(), inner.height() / view.height())
        return inner, view, scale

    def _box(self, inner, view, scale) -> QRectF:
        """The region box in widget coordinates."""
        pw, ph = self._pixmap.width(), self._pixmap.height()
        r = self._op.rect
        region = QRectF(r.x() * pw, r.y() * ph, r.width() * pw, r.height() * ph)
        ox = inner.center().x() - (view.width() * scale) / 2.0
        oy = inner.center().y() - (view.height() * scale) / 2.0
        return QRectF(
            ox + (region.x() - view.x()) * scale,
            oy + (region.y() - view.y()) * scale,
            region.width() * scale,
            region.height() * scale,
        )

    def _hit(self, box: QRectF, pos: QPointF) -> str | None:
        """Which part of the box the cursor is over."""
        if not box.adjusted(-HIT, -HIT, HIT, HIT).contains(pos):
            return None
        left = abs(pos.x() - box.left()) <= HIT
        right = abs(pos.x() - box.right()) <= HIT
        top = abs(pos.y() - box.top()) <= HIT
        bottom = abs(pos.y() - box.bottom()) <= HIT

        if top and left:
            return "tl"
        if top and right:
            return "tr"
        if bottom and left:
            return "bl"
        if bottom and right:
            return "br"
        if top:
            return "t"
        if bottom:
            return "b"
        if left:
            return "l"
        if right:
            return "r"
        if box.contains(pos):
            return "move"
        return None

    _CURSORS = {
        "tl": Qt.SizeFDiagCursor, "br": Qt.SizeFDiagCursor,
        "tr": Qt.SizeBDiagCursor, "bl": Qt.SizeBDiagCursor,
        "t": Qt.SizeVerCursor, "b": Qt.SizeVerCursor,
        "l": Qt.SizeHorCursor, "r": Qt.SizeHorCursor,
        "move": Qt.SizeAllCursor,
    }

    # ------------------------------------------------------------------ interaction

    def _to_page(self, pos: QPointF) -> tuple[float, float] | None:
        """Widget coordinates -> page-normalized (0..1) coordinates."""
        geo = self._geometry()
        if geo is None or self._op is None:
            return None
        inner, view, scale = geo
        ox = inner.center().x() - (view.width() * scale) / 2.0
        oy = inner.center().y() - (view.height() * scale) / 2.0
        px = (pos.x() - ox) / max(1e-9, scale) + view.x()
        py = (pos.y() - oy) / max(1e-9, scale) + view.y()
        nx = px / max(1, self._pixmap.width())
        ny = py / max(1, self._pixmap.height())
        return (min(1.0, max(0.0, nx)), min(1.0, max(0.0, ny)))

    def mousePressEvent(self, event) -> None:
        if event.button() != Qt.LeftButton or not self.editable:
            super().mousePressEvent(event)
            return

        # --- freehand modes take over the mouse entirely ---
        if self._mode in (self.MODE_BRUSH, self.MODE_POLYGON):
            if event.button() == Qt.RightButton:
                return
            point = self._to_page(event.position())
            if point is None:
                return
            if self._mode == self.MODE_BRUSH:
                self._drawing_points = [point]
            else:
                # Right-click finishes the outline; left-click adds a vertex.
                self._polygon_points.append(point)
                if len(self._polygon_points) >= 3:
                    self._op.fill_polygon = list(self._polygon_points)
                    self._op.fill_shape = "polygon"
                self.polygonChanged.emit()
            self.update()
            event.accept()
            return

        geo = self._geometry()
        if geo is None:
            return
        box = self._box(*geo)
        handle = self._hit(box, event.position())
        if handle is None:
            return
        self._handle = handle
        self._press_pos = event.position()
        self._press_rect = QRectF(self._op.rect)
        self.setCursor(self._CURSORS.get(handle, Qt.ArrowCursor))
        event.accept()

    def mouseMoveEvent(self, event) -> None:
        if self._op is None or self._pixmap.isNull():
            return

        if self._mode == self.MODE_BRUSH and event.buttons() & Qt.LeftButton:
            point = self._to_page(event.position())
            if point is not None:
                self._drawing_points.append(point)
                self.update()
            event.accept()
            return
        geo = self._geometry()
        if geo is None:
            return
        inner, view, scale = geo

        if self._handle is None:
            hover = self._hit(self._box(inner, view, scale), event.position())
            if hover != self._hover:
                self._hover = hover
                self.setCursor(self._CURSORS.get(hover, Qt.ArrowCursor))
            return

        delta = event.position() - self._press_pos
        # Widget pixels -> normalized fractions of the page.
        dx = delta.x() / max(1e-6, scale) / self._pixmap.width()
        dy = delta.y() / max(1e-6, scale) / self._pixmap.height()
        rect = self._apply_drag(self._press_rect, dx, dy, self._handle)
        self._op.rect = rect
        self.rectChanged.emit(QRectF(rect))
        self.update()
        event.accept()

    def mouseReleaseEvent(self, event) -> None:
        if self._mode == self.MODE_BRUSH and self._drawing_points:
            if len(self._drawing_points) >= 2:
                self._op.strokes.append({
                    "points": [[x, y] for x, y in self._drawing_points],
                    "color": [self._brush_color.red(), self._brush_color.green(),
                              self._brush_color.blue(), self._brush_color.alpha()],
                    "width": self._brush_width,
                })
                self.strokesChanged.emit()
            self._drawing_points = []
            self.update()
            event.accept()
            return

        if self._handle is None:
            super().mouseReleaseEvent(event)
            return
        handle, self._handle = self._handle, None
        self.setCursor(self._CURSORS.get(handle, Qt.ArrowCursor))
        if self._op is not None:
            self.rectCommitted.emit(QRectF(self._op.rect))
        event.accept()

    @staticmethod
    def _apply_drag(base: QRectF, dx: float, dy: float, handle: str) -> QRectF:
        """Move or resize a normalized rect, clamped to the page."""
        x, y, w, h = base.x(), base.y(), base.width(), base.height()
        if handle == "move":
            x = min(max(0.0, x + dx), 1.0 - w)
            y = min(max(0.0, y + dy), 1.0 - h)
            return QRectF(x, y, w, h)

        right, bottom = x + w, y + h
        if "l" in handle:
            x = min(max(0.0, x + dx), right - MIN_SIZE)
        if "r" in handle:
            right = max(min(1.0, right + dx), x + MIN_SIZE)
        if "t" in handle:
            y = min(max(0.0, y + dy), bottom - MIN_SIZE)
        if "b" in handle:
            bottom = max(min(1.0, bottom + dy), y + MIN_SIZE)
        return QRectF(x, y, right - x, bottom - y)

    # ------------------------------------------------------------------ painting

    def paintEvent(self, event) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing, True)
        painter.setRenderHint(QPainter.SmoothPixmapTransform, True)
        painter.setRenderHint(QPainter.TextAntialiasing, True)

        outer = QRectF(self.rect()).adjusted(1, 1, -1, -1)
        painter.setBrush(QColor("#0b0f15"))
        painter.setPen(QPen(QColor("#28313f"), 1))
        painter.drawRoundedRect(outer, 10, 10)

        geo = self._geometry()
        if geo is None:
            painter.setPen(QColor("#6b7789"))
            painter.drawText(outer, Qt.AlignCenter, "无选区")
            return
        inner, view, scale = geo
        pw, ph = self._pixmap.width(), self._pixmap.height()

        painter.save()
        painter.setClipRect(inner)
        painter.translate(
            inner.center().x() - (view.width() * scale) / 2.0,
            inner.center().y() - (view.height() * scale) / 2.0,
        )
        painter.scale(scale, scale)
        painter.translate(-view.x(), -view.y())
        painter.drawPixmap(0, 0, self._pixmap)
        draw_region(painter, pw, ph, self._op)
        painter.restore()

        box = self._box(inner, view, scale)
        pen = QPen(QColor(45, 212, 191, 190), 1.2)
        pen.setStyle(Qt.DashLine)
        painter.setPen(pen)
        painter.setBrush(Qt.NoBrush)

        # The content is drawn rotated inside draw_region; mirror that on the
        # outline so users can see the tilt. The resize handles stay axis
        # aligned because dragging them edits the unrotated rect.
        angle = float(getattr(self._op, "rotation", 0.0) or 0.0)
        if abs(angle) > 0.01:
            painter.save()
            painter.translate(box.center())
            painter.rotate(angle)
            painter.translate(-box.center())
            painter.drawRect(box)
            painter.restore()
        else:
            painter.drawRect(box)

        # Handles: corners plus edge midpoints, so every direction is grabbable.
        if self.editable:
            painter.setPen(QPen(QColor("#0b0f15"), 1))
            painter.setBrush(QColor("#2dd4bf"))
            for cx, cy in (
                (box.left(), box.top()), (box.center().x(), box.top()), (box.right(), box.top()),
                (box.left(), box.center().y()), (box.right(), box.center().y()),
                (box.left(), box.bottom()), (box.center().x(), box.bottom()),
                (box.right(), box.bottom()),
            ):
                painter.drawRect(QRectF(cx - HANDLE, cy - HANDLE, HANDLE * 2, HANDLE * 2))

        self._paint_freehand(painter, inner, view, scale)

    def _paint_freehand(self, painter: QPainter, inner: QRectF,
                        view: QRectF, scale: float) -> None:
        """Show the stroke being drawn and the polygon vertices in progress."""
        if not (self._drawing_points or self._polygon_points):
            return
        ox = inner.center().x() - (view.width() * scale) / 2.0
        oy = inner.center().y() - (view.height() * scale) / 2.0
        pw, ph = self._pixmap.width(), self._pixmap.height()

        def to_widget(pt):
            return QPointF(ox + (pt[0] * pw - view.x()) * scale,
                           oy + (pt[1] * ph - view.y()) * scale)

        painter.save()
        painter.setClipRect(inner)

        if len(self._drawing_points) >= 2:
            pen = QPen(self._brush_color, max(1.0, self._brush_width * pw * scale))
            pen.setCapStyle(Qt.RoundCap)
            pen.setJoinStyle(Qt.RoundJoin)
            painter.setPen(pen)
            painter.setBrush(Qt.NoBrush)
            path = QPainterPath(to_widget(self._drawing_points[0]))
            for pt in self._drawing_points[1:]:
                path.lineTo(to_widget(pt))
            painter.drawPath(path)

        if self._polygon_points:
            pen = QPen(QColor(255, 196, 0, 220), 1.4)
            pen.setStyle(Qt.DashLine)
            painter.setPen(pen)
            painter.setBrush(Qt.NoBrush)
            path = QPainterPath(to_widget(self._polygon_points[0]))
            for pt in self._polygon_points[1:]:
                path.lineTo(to_widget(pt))
            painter.drawPath(path)
            painter.setBrush(QColor("#ffc400"))
            painter.setPen(Qt.NoPen)
            for pt in self._polygon_points:
                c = to_widget(pt)
                painter.drawEllipse(c, 3.2, 3.2)
        painter.restore()
