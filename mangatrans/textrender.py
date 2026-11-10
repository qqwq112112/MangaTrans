# -*- coding: utf-8 -*-
"""Region operation model and text rendering onto page images."""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QColor, QFont, QFontMetricsF, QImage, QPainter, QPainterPath, QPen


@dataclass
class RegionOp:
    """A destructive edit described in normalized page coordinates.

    rect:      x/y/w/h in 0..1 of the page.
    font_ratio: font pixel size divided by page width. This keeps text the
                same relative size whether we render a preview or the full page.
    padding:   padding as a fraction of min(rect.width, rect.height).

    Every spacing value is a *ratio* (of the font size, or of the rect for
    padding), never an absolute pixel count. That is what makes the whole text
    block rescale when the selection is resized: the fitted font size changes,
    and letter / line / column spacing follow it proportionally.
    """

    rect: QRectF
    fill_color: QColor = field(default_factory=lambda: QColor("#FFFFFF"))
    text: str = ""
    font_family: str = "Microsoft YaHei"
    font_ratio: float = 0.03
    bold: bool = False
    text_color: QColor = field(default_factory=lambda: QColor("#111111"))
    line_spacing: float = 1.12
    padding: float = 0.06
    auto_fit: bool = True
    # Filling a rectangle over a round bubble leaves visible corners; an
    # ellipse (or a soft-edged rect) blends into the original bubble instead.
    fill_shape: str = "rect"          # rect | rounded | ellipse | polygon | none
    fill_soft: float = 0.0            # feather radius as a ratio of page width
    # rounded corner radius, ratio of min(rect.w, rect.h)
    corner_radius: float = 0.18
    # Custom ("polygon") fill outline: [(x, y), ...] normalized to the PAGE, so
    # it survives resizing the selection. Empty means "fall back to rect".
    fill_polygon: list = field(default_factory=list)
    # Freehand strokes used to redraw artwork or to paint over leftovers that
    # the rectangular fill could not reach. Each entry:
    #   {"points": [[x, y], ...] (page-normalized), "color": [r,g,b,a],
    #    "width": ratio-of-page-width}
    strokes: list = field(default_factory=list)
    # Rotation of the whole region (fill + strokes + text), in degrees,
    # clockwise around the rect centre. Content rotates with the selection.
    rotation: float = 0.0
    # --- typography (all ratios, so they scale with the fitted font size) ---
    letter_spacing: float = 0.0       # 字间距, ratio of font px
    column_gap: float = 0.0           # 列间距, ratio of font px (vertical only)
    vertical: bool = False            # 竖排（縦書き）: columns run right-to-left

    def cloned(self) -> "RegionOp":
        return RegionOp(
            rect=QRectF(self.rect),
            fill_color=QColor(self.fill_color),
            text=self.text,
            font_family=self.font_family,
            font_ratio=self.font_ratio,
            bold=self.bold,
            text_color=QColor(self.text_color),
            line_spacing=self.line_spacing,
            padding=self.padding,
            auto_fit=self.auto_fit,
            fill_shape=self.fill_shape,
            fill_soft=self.fill_soft,
            corner_radius=self.corner_radius,
            fill_polygon=[(float(x), float(y)) for x, y in (self.fill_polygon or [])],
            strokes=[
                {
                    "points": [[float(px), float(py)] for px, py in s.get("points", [])],
                    "color": list(s.get("color", [0, 0, 0, 255])),
                    "width": float(s.get("width", 0.004)),
                }
                for s in (self.strokes or [])
            ],
            rotation=self.rotation,
            letter_spacing=self.letter_spacing,
            column_gap=self.column_gap,
            vertical=self.vertical,
        )


_CJK_PUNCT = set("，。、！？；：…—“”‘’（）《》【】「」『』〈〉·～")
_CLOSING = set("，。、！？；：…,.;:!?）】》」』〉”’")
_OPENING = set("（【《「『〈“‘")
_PUNCT_NORMALIZE = {
    "．": "。",
    "‥": "…",
    "｡": "。",
    "､": "、",
    "〜": "～",
    "~": "～",
}


def _strip_cjk_spaces(text: str) -> str:
    """Drop spaces that sit between two CJK characters.

    The model sometimes returns "うるさい！ あっち行けよ！", whose space is an
    artifact. Spaces next to Latin words are preserved.
    """
    chars = list(text)
    out: list[str] = []
    for i, ch in enumerate(chars):
        if ch == " ":
            prev = next((c for c in reversed(out) if c != " "), "")
            nxt = next((c for c in chars[i + 1:] if c != " "), "")
            if prev and nxt and _is_cjk(prev) and _is_cjk(nxt):
                continue
        out.append(ch)
    return "".join(out)


def normalize_punctuation(text: str) -> str:
    """Convert stray Japanese/Latin punctuation into Chinese typography.

    Applied to model output, which sometimes keeps a Japanese full stop or
    repeats dots differently from Chinese convention.
    """
    if not text:
        return text
    out = "".join(_PUNCT_NORMALIZE.get(ch, ch) for ch in text)
    out = out.replace("...", "…").replace("。。。", "…")
    out = out.replace("!?", "！？").replace("?!", "？！")
    out = _strip_cjk_spaces(out)
    # Collapse repeated sentence enders ("。 。", "。。", "!!") but keep one.
    out = re.sub(r"([。！？，、])\s*\1+", r"\1", out)
    # No spaces around Chinese punctuation.
    for mark in "，。、！？；：）】》」』":
        out = out.replace(f" {mark}", mark)
    for mark in "（【《「『":
        out = out.replace(f"{mark} ", mark)
    return out


def _is_cjk(ch: str) -> bool:
    o = ord(ch)
    return (
        0x2E80 <= o <= 0x9FFF
        or 0xAC00 <= o <= 0xD7AF
        or 0xF900 <= o <= 0xFAFF
        or 0xFF00 <= o <= 0xFFEF
        or 0x3000 <= o <= 0x303F
    )


def _tokenize(paragraph: str) -> list[str]:
    tokens: list[str] = []
    buf = ""
    for ch in paragraph:
        if ch.isspace():
            if buf:
                tokens.append(buf)
                buf = ""
            tokens.append(" ")
        elif _is_cjk(ch) or ch in _CJK_PUNCT:
            if buf:
                tokens.append(buf)
                buf = ""
            tokens.append(ch)
        else:
            buf += ch
    if buf:
        tokens.append(buf)
    return tokens


def _wrap_paragraph(paragraph: str, fm: QFontMetricsF, max_w: float) -> list[str]:
    if not paragraph:
        return [""]
    lines: list[str] = []
    cur = ""
    for token in _tokenize(paragraph):
        if token == " " and not cur:
            continue
        if token != " " and fm.horizontalAdvance(token) > max_w:
            # Very long latin token: split per character.
            if cur:
                lines.append(cur.rstrip())
                cur = ""
            piece = ""
            for ch in token:
                if fm.horizontalAdvance(piece + ch) > max_w and piece:
                    lines.append(piece)
                    piece = ch
                else:
                    piece += ch
            cur = piece
            continue

        trial = cur + token
        if fm.horizontalAdvance(trial) <= max_w or not cur:
            cur = trial
        else:
            if token in _CLOSING:
                # Avoid orphan punctuation at the start of a line.
                lines.append((cur + token).rstrip())
                cur = ""
            else:
                lines.append(cur.rstrip())
                cur = "" if token == " " else token
    if cur.strip():
        lines.append(cur.rstrip())
    return lines or [""]


def _make_font(family: str, bold: bool, size: int, letter_spacing: float) -> QFont:
    font = QFont(family)
    font.setPixelSize(max(1, int(size)))
    font.setBold(bool(bold))
    if letter_spacing > 0:
        # AbsoluteSpacing is in pixels; expressing it as a ratio of the font
        # size is what makes it rescale with the selection.
        font.setLetterSpacing(QFont.AbsoluteSpacing, size * letter_spacing)
    return font


def _layout_text(text: str, family: str, bold: bool, size: int,
                 max_w: float, line_spacing: float, letter_spacing: float = 0.0):
    """Horizontal layout: wrap into lines, eager-fitting to max_w."""
    font = _make_font(family, bold, size, letter_spacing)
    fm = QFontMetricsF(font)
    lines: list[str] = []
    for para in text.split("\n"):
        lines.extend(_wrap_paragraph(para, fm, max_w))
    line_h = fm.height() * line_spacing
    total_h = line_h * len(lines)
    max_line_w = max((fm.horizontalAdvance(line) for line in lines), default=0.0)
    return font, fm, lines, total_h, max_line_w


def _layout_vertical(text: str, family: str, bold: bool, size: int,
                     max_h: float, line_spacing: float,
                     letter_spacing: float, column_gap: float):
    """Vertical layout (縦書き): characters stack in columns, right to left.

    Returns (font, fm, columns, total_w, total_h) where columns is a list of
    strings, ordered right-to-left as they must be drawn.

    line_spacing controls the vertical pitch inside a column, letter_spacing the
    extra gap between characters, column_gap the gap between columns.
    """
    font = _make_font(family, bold, size, 0.0)
    fm = QFontMetricsF(font)

    char_h = fm.height() * line_spacing + size * letter_spacing
    char_h = max(1.0, char_h)
    per_column = max(1, int(max_h // char_h))
    gap_px = size * column_gap

    columns: list[str] = []
    for para in text.split("\n"):
        chars = list(para)
        if not chars:
            columns.append("")
            continue
        for start in range(0, len(chars), per_column):
            columns.append("".join(chars[start:start + per_column]))
    if not columns:
        columns = [""]

    # Column width = widest glyph advance in that column.
    widths = []
    for column in columns:
        if column:
            widths.append(max(fm.horizontalAdvance(ch) for ch in column))
        else:
            widths.append(fm.horizontalAdvance("字"))
    total_w = sum(widths) + gap_px * max(0, len(widths) - 1)
    total_h = char_h * max(len(c) for c in columns) if columns else 0.0
    return font, fm, columns, total_w, total_h, widths, gap_px, char_h


def _fit_size(text: str, family: str, bold: bool, max_w: float, max_h: float,
              line_spacing: float, ceiling: int = 240,
              letter_spacing: float = 0.0) -> int:
    """Largest horizontal font size that fits the box."""
    lo, hi = 5, max(6, min(ceiling, int(max(max_w, 1)), int(max(max_h, 1))))
    best = lo
    while lo <= hi:
        mid = (lo + hi) // 2
        _font, _fm, _lines, total_h, max_line_w = _layout_text(
            text, family, bold, mid, max_w, line_spacing, letter_spacing)
        if total_h <= max_h + 0.5 and max_line_w <= max_w + 0.5:
            best = mid
            lo = mid + 1
        else:
            hi = mid - 1
    return max(5, best)


def _fit_size_vertical(text: str, family: str, bold: bool, max_w: float,
                       max_h: float, line_spacing: float,
                       letter_spacing: float, column_gap: float,
                       ceiling: int = 240) -> int:
    """Largest vertical font size whose columns fit the box."""
    lo, hi = 5, max(6, min(ceiling, int(max(max_w, 1)), int(max(max_h, 1))))
    best = lo
    while lo <= hi:
        mid = (lo + hi) // 2
        _f, _fm, _cols, total_w, total_h, _w, _g, _ch = _layout_vertical(
            text, family, bold, mid, max_h, line_spacing,
            letter_spacing, column_gap)
        if total_w <= max_w + 0.5 and total_h <= max_h + 0.5:
            best = mid
            lo = mid + 1
        else:
            hi = mid - 1
    return max(5, best)


def fit_font_size(op: "RegionOp", inner: QRectF) -> int:
    """Fitted font size for the op's layout mode; shared by render and UI."""
    if op.vertical:
        return _fit_size_vertical(
            op.text, op.font_family, op.bold, inner.width(), inner.height(),
            op.line_spacing, op.letter_spacing, op.column_gap)
    return _fit_size(
        op.text, op.font_family, op.bold, inner.width(), inner.height(),
        op.line_spacing, letter_spacing=op.letter_spacing)


def typing_metrics(op: "RegionOp", size: int, inner: QRectF | None = None) -> dict:
    """Pixel measurements of the current layout, for UI read-out and tests.

    Every value here is derived from `size`, which is derived from the box, so
    all of them change when the selection is resized. `inner` must be the real
    text area: the vertical layout splits into columns based on its height, so
    passing a bogus value would report the wrong column count.
    """
    if inner is None:
        inner = QRectF(0, 0, 1000, 1000)

    if op.vertical:
        _f, _fm, cols, total_w, _th, widths, gap_px, char_h = _layout_vertical(
            op.text, op.font_family, op.bold, size, inner.height(),
            op.line_spacing, op.letter_spacing, op.column_gap)
        return {
            "size": size,
            "columns": len(cols),
            "column_gap_px": gap_px,
            "char_pitch_px": char_h,
            "letter_px": size * op.letter_spacing,
            "total_w": total_w,
            "total_h": char_h * max((len(c) for c in cols), default=0),
        }
    _f, fm, lines, total_h, max_line_w = _layout_text(
        op.text, op.font_family, op.bold, size, inner.width(),
        op.line_spacing, op.letter_spacing)
    return {
        "size": size,
        "lines": len(lines),
        "line_pitch_px": fm.height() * op.line_spacing,
        "letter_px": size * op.letter_spacing,
        "total_w": max_line_w,
        "total_h": total_h,
    }


def shape_path(op: "RegionOp", r: QRectF) -> QPainterPath:
    """Build the fill outline in device coordinates.

    Shapes are all described relative to the page so they stay put when the
    selection is resized. `polygon` uses the stored page-normalized points (the
    custom shape the user traced); everything else is derived from `r`.
    """
    path = QPainterPath()
    shape = op.fill_shape or "rect"

    if shape == "polygon" and len(op.fill_polygon or []) >= 3:
        # Points are page-normalized; convert with the same scale as the rect.
        pts = [(float(x), float(y)) for x, y in op.fill_polygon]
        # Recover page size from the rect: op.rect maps to r, so 1 page unit is
        # r.width() / op.rect.width() in device pixels.
        pw = r.width() / max(1e-9, op.rect.width())
        ph = r.height() / max(1e-9, op.rect.height())
        ox = r.x() - op.rect.x() * pw
        oy = r.y() - op.rect.y() * ph
        path.moveTo(ox + pts[0][0] * pw, oy + pts[0][1] * ph)
        for x, y in pts[1:]:
            path.lineTo(ox + x * pw, oy + y * ph)
        path.closeSubpath()
        return path

    if shape == "ellipse":
        path.addEllipse(r)
    elif shape == "rounded":
        radius = max(0.0, min(0.5, op.corner_radius)) * min(r.width(), r.height())
        path.addRoundedRect(r, radius, radius)
    elif shape == "none":
        return path                      # empty: nothing gets painted
    else:
        path.addRect(r)
    return path


def _paint_fill(painter: QPainter, r: QRectF, op: RegionOp) -> None:
    """Cover the region with the fill colour.

    A hard rectangle over a round speech bubble leaves four visible corners,
    which reads as a pasted box. The shape options (rounded / ellipse / traced
    polygon) keep the original bubble outline intact instead.
    """
    if (op.fill_shape or "rect") == "none":
        return

    painter.save()
    painter.setPen(Qt.NoPen)
    painter.setBrush(op.fill_color)

    if op.fill_soft > 0 and (op.fill_shape or "rect") != "polygon":
        soft_px = max(1.0, op.fill_soft * r.width())
        steps = max(1, int(min(40, round(soft_px))))
        base = shape_path(op, r)
        for i in range(steps):
            alpha = int(255 * (i + 1) / steps)
            color = QColor(op.fill_color)
            color.setAlpha(alpha)
            painter.setBrush(color)
            grow = soft_px * (steps - i) / steps
            # Feather by drawing the same shape progressively larger.
            painter.setPen(QPen(color, grow * 2))
            painter.drawPath(base)
        painter.setPen(Qt.NoPen)
    else:
        path = shape_path(op, r)
        if not path.isEmpty():
            painter.drawPath(path)
    painter.restore()


def _paint_strokes(painter: QPainter, r: QRectF, op: RegionOp) -> None:
    """Draw the freehand strokes.

    Used both to redraw artwork that the fill erased and to paint over bits of
    the original text the rectangle could not cover (draw with the fill colour
    for that). Strokes are page-normalized so they follow selection resizing.
    """
    if not op.strokes:
        return
    pw = r.width() / max(1e-9, op.rect.width())
    ph = r.height() / max(1e-9, op.rect.height())
    ox = r.x() - op.rect.x() * pw
    oy = r.y() - op.rect.y() * ph

    painter.save()
    painter.setBrush(Qt.NoBrush)
    for stroke in op.strokes:
        pts = stroke.get("points") or []
        if len(pts) < 2:
            continue
        color = QColor(*[int(c) for c in (stroke.get("color") or [0, 0, 0, 255])[:4]])
        width = max(0.5, float(stroke.get("width", 0.004)) * pw)
        pen = QPen(color, width)
        pen.setCapStyle(Qt.RoundCap)
        pen.setJoinStyle(Qt.RoundJoin)
        painter.setPen(pen)

        path = QPainterPath()
        path.moveTo(ox + float(pts[0][0]) * pw, oy + float(pts[0][1]) * ph)
        for x, y in pts[1:]:
            path.lineTo(ox + float(x) * pw, oy + float(y) * ph)
        painter.drawPath(path)
    painter.restore()


def text_bounds(r: QRectF, op: "RegionOp") -> QRectF:
    """Available text area inside the fill.

    An inscribed rectangle inside an ellipse is only ~70% of the bounding box,
    so text laid out to the full rect spills over the bubble outline. Shrink
    the text area to match the ellipse's usable interior.
    """
    pad = max(1.0, min(r.width(), r.height()) * max(0.0, op.padding))
    inner = r.adjusted(pad, pad, -pad, -pad)
    if inner.width() < 2 or inner.height() < 2:
        inner = QRectF(r)

    shape = op.fill_shape or "rect"
    if shape == "ellipse":
        # Half-side of a rectangle inscribed in an ellipse is r / sqrt(2).
        shrink_x = inner.width() * (1.0 - 1.0 / 2 ** 0.5) / 2.0
        shrink_y = inner.height() * (1.0 - 1.0 / 2 ** 0.5) / 2.0
        inner = inner.adjusted(shrink_x, shrink_y, -shrink_x, -shrink_y)
    elif shape == "rounded":
        # Corners are cut, but the middle band keeps full width; a modest
        # inset avoids text touching the arcs.
        radius = max(0.0, min(0.5, op.corner_radius)) * min(r.width(), r.height())
        inset = radius * 0.35
        inner = inner.adjusted(inset, inset * 0.5, -inset, -inset * 0.5)
    elif shape == "polygon" and len(op.fill_polygon or []) >= 3:
        # Use the polygon's own bounding box, which is where the fill actually
        # covers; tracing tightly around a bubble would otherwise clip text.
        pw = r.width() / max(1e-9, op.rect.width())
        ph = r.height() / max(1e-9, op.rect.height())
        ox = r.x() - op.rect.x() * pw
        oy = r.y() - op.rect.y() * ph
        xs = [float(x) * pw + ox for x, _y in op.fill_polygon]
        ys = [float(y) * ph + oy for _x, y in op.fill_polygon]
        poly_box = QRectF(min(xs), min(ys), max(xs) - min(xs), max(ys) - min(ys))
        inner = inner.intersected(poly_box)
    if inner.width() < 2 or inner.height() < 2:
        inner = QRectF(r)
    return inner


def draw_region(painter: QPainter, width: int, height: int, op: RegionOp) -> None:
    """Paint one RegionOp onto a painter whose device is width x height."""
    r = QRectF(
        op.rect.x() * width,
        op.rect.y() * height,
        op.rect.width() * width,
        op.rect.height() * height,
    )
    if r.width() < 1 or r.height() < 1:
        return

    painter.save()
    # Rotation applies to the whole region (fill, strokes and text together),
    # so the artwork and the new text stay aligned as one unit.
    rotated = abs(op.rotation or 0.0) > 0.01
    if rotated:
        painter.translate(r.center())
        painter.rotate(float(op.rotation))
        painter.translate(-r.center())

    _paint_fill(painter, r, op)
    _paint_strokes(painter, r, op)

    text = (op.text or "").strip()
    if text:
        inner = text_bounds(r, op)

        if op.auto_fit:
            size = fit_font_size(op, inner)
        else:
            # font_ratio is relative to page width, so text keeps its size
            # between the on-screen preview and the full-resolution export.
            size = max(5, int(round(op.font_ratio * width)))

        painter.setPen(op.text_color)
        painter.setClipRect(inner)

        if op.vertical:
            _draw_vertical(painter, inner, op, text, size)
        else:
            _draw_horizontal(painter, inner, op, text, size)
    painter.restore()


def _draw_horizontal(painter: QPainter, inner: QRectF, op: "RegionOp",
                     text: str, size: int) -> None:
    font, fm, lines, total_h, _max_w = _layout_text(
        text, op.font_family, op.bold, size, inner.width(),
        op.line_spacing, op.letter_spacing)
    painter.setFont(font)

    y = inner.top() + max(0.0, (inner.height() - total_h) / 2.0) + fm.ascent()
    for line in lines:
        line_w = fm.horizontalAdvance(line)
        x = inner.center().x() - line_w / 2.0
        painter.drawText(QPointF(x, y), line)
        y += fm.height() * op.line_spacing


def _draw_vertical(painter: QPainter, inner: QRectF, op: "RegionOp",
                   text: str, size: int) -> None:
    """Draw columns right-to-left, characters top-to-bottom."""
    font, fm, columns, total_w, _total_h, widths, gap_px, char_h = _layout_vertical(
        text, op.font_family, op.bold, size, inner.height(),
        op.line_spacing, op.letter_spacing, op.column_gap)
    painter.setFont(font)

    x_right = inner.center().x() + total_w / 2.0
    for column, col_w in zip(columns, widths):
        x = x_right - col_w
        col_h = char_h * len(column)
        y = inner.top() + max(0.0, (inner.height() - col_h) / 2.0)

        for ch in column:
            # Centre each glyph inside its cell so mixed-width punctuation
            # (、。ー) still lines up on the column axis.
            adv = fm.horizontalAdvance(ch)
            painter.drawText(QPointF(x + (col_w - adv) / 2.0,
                                     y + fm.ascent()), ch)
            y += char_h
        x_right = x - gap_px


def measure_text_bounds(text: str, family: str, bold: bool, size: int,
                        max_w: float, line_spacing: float) -> tuple[float, float]:
    """Return (width, height) the text needs, used by the size spinner."""
    _font, fm, lines, total_h, max_line_w = _layout_text(
        text, family, bold, size, max_w, line_spacing)
    return max_line_w, total_h


def paint_ops(image: QImage, ops: list[RegionOp]) -> QImage:
    """Paint operations in place on the given image and return it."""
    if not ops:
        return image
    painter = QPainter(image)
    painter.setRenderHint(QPainter.Antialiasing, True)
    painter.setRenderHint(QPainter.TextAntialiasing, True)
    painter.setRenderHint(QPainter.SmoothPixmapTransform, True)
    for op in ops:
        draw_region(painter, image.width(), image.height(), op)
    painter.end()
    return image
