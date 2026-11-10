# -*- coding: utf-8 -*-
"""Detect vertical Japanese text columns inside a selected bubble.

manga-ocr reads one text line at a time. Give it a bubble holding three
vertical columns and it silently drops some of them. Splitting the bubble into
columns first and OCR-ing each one is what makes multi-column bubbles work.
"""

from __future__ import annotations

import numpy as np
from PySide6.QtGui import QImage

from PySide6.QtCore import QRectF


def _to_gray(image: QImage) -> np.ndarray:
    gray = image.convertToFormat(QImage.Format_Grayscale8)
    w, h = gray.width(), gray.height()
    ptr = gray.constBits()
    arr = np.frombuffer(ptr, dtype=np.uint8, count=gray.sizeInBytes())
    # Rows are padded to a 4-byte boundary.
    stride = gray.bytesPerLine()
    return arr.reshape(h, stride)[:, :w].copy()


def _ink_mask(gray: np.ndarray) -> np.ndarray:
    """Boolean mask of dark pixels, with a local threshold when possible."""
    try:
        import cv2
        blurred = cv2.GaussianBlur(gray, (3, 3), 0)
        _, mask = cv2.threshold(blurred, 0, 255,
                                cv2.THRESH_BINARY_INV + cv2.THRESH_OTSU)
        return mask > 0
    except Exception:
        return gray < 128


def _components(mask: np.ndarray):
    """Return list of (x, y, w, h) boxes of connected ink components."""
    try:
        import cv2
        n, _labels, stats, _centroids = cv2.connectedComponentsWithStats(
            mask.astype(np.uint8), connectivity=8)
        boxes = []
        for i in range(1, n):
            x, y, w, h, area = stats[i]
            boxes.append((int(x), int(y), int(w), int(h), int(area)))
        return boxes
    except Exception:
        # Fallback: treat the whole ink bbox as one component.
        ys, xs = np.nonzero(mask)
        if len(xs) == 0:
            return []
        return [(int(xs.min()), int(ys.min()),
                 int(xs.max() - xs.min() + 1), int(ys.max() - ys.min() + 1),
                 int(mask.sum()))]


def detect_vertical_columns(image: QImage, max_columns: int = 8) -> list[QRectF]:
    """Return normalized column boxes, ordered right-to-left.

    Returns an empty list when the region does not look like multi-column
    vertical text, so callers can just OCR the whole crop.
    """
    if image is None or image.isNull():
        return []
    w, h = image.width(), image.height()
    if w < 20 or h < 20:
        return []

    gray = _to_gray(image)
    mask = _ink_mask(gray)
    if mask.sum() < 20:
        return []

    boxes = _components(mask)
    if not boxes:
        return []

    # First pass: drop obvious non-glyphs (big curves, rules, specks).
    candidates = []
    for x, y, cw, ch, area in boxes:
        if cw >= 0.72 * w and ch >= 0.72 * h:
            continue                      # bubble outline spanning the region
        if cw >= 0.85 * w and ch <= 0.06 * h:
            continue                      # horizontal rule
        if ch >= 0.85 * h and cw <= 0.05 * w:
            continue                      # vertical rule
        if area < max(6, 0.0004 * w * h):
            continue                      # specks
        if cw > 0.55 * w:
            continue                      # too wide to be a single glyph
        candidates.append((x, y, cw, ch, area))

    if len(candidates) < 4:
        return []

    # Second pass: when the selection clips the speech bubble, the arc survives
    # as a long thin component and would be read as a text column. Real glyphs
    # fill a good share of their bounding box; an arc limb does not.
    solid = []
    for x, y, cw, ch, area in candidates:
        if cw < 3 or ch < 3:
            continue
        if area / float(max(1, cw * ch)) < 0.15:
            continue                      # hollow arc / outline, not a glyph
        solid.append((x, y, cw, ch))

    if len(solid) < 4:
        return []

    # Glyphs share a similar size; punctuation ("、", "！") is smaller but still
    # solid and must survive so it is not cut off from its column.
    med_w = float(np.median([c[2] for c in solid]))
    med_h = float(np.median([c[3] for c in solid]))
    glyphs = []
    for x, y, cw, ch in solid:
        if cw > max(med_w * 3.0, 0.5 * w):
            continue
        if ch > max(med_h * 3.0, 0.9 * h):
            continue
        glyphs.append((x, y, cw, ch))

    if len(glyphs) < 4:
        return []

    # Project the glyph mask onto the x-axis. Each vertical column becomes one
    # contiguous ink run.
    keep = np.zeros_like(mask)
    for x, y, cw, ch in glyphs:
        keep[y:y + ch, x:x + cw] = True

    profile = keep.sum(axis=0)
    if profile.max() < 3:
        return []

    # A column must be at least this tall to count as text.
    min_ink = max(3, int(h * 0.10))
    runs: list[list[int]] = []
    start = None
    for x in range(w):
        if profile[x] >= min_ink:
            if start is None:
                start = x
        elif start is not None:
            runs.append([start, x])
            start = None
    if start is not None:
        runs.append([start, w])

    # Merge runs separated by a hairline gap (glyph rendering noise).
    min_gap = max(1, int(w * 0.006))
    merged: list[list[int]] = []
    for run in runs:
        if merged and run[0] - merged[-1][1] <= min_gap:
            merged[-1][1] = run[1]
        else:
            merged.append(run)

    median_w = float(np.median([r[1] - r[0] for r in merged])) if merged else 0.0
    # Split any run that is clearly two fused columns, at its thinnest point.
    final: list[list[int]] = []
    for x0, x1 in merged:
        width = x1 - x0
        if median_w and width > median_w * 1.75:
            seg = profile[x0:x1]
            cut = int(np.argmin(seg[max(1, int(len(seg) * 0.3)):
                                    max(2, int(len(seg) * 0.7))]))
            cut += max(1, int(len(seg) * 0.3))
            if cut > 2 and cut < width - 2:
                final.append([x0, x0 + cut])
                final.append([x0 + cut, x1])
                continue
        final.append([x0, x1])

    columns = []
    for x0, x1 in final:
        sub = keep[:, x0:x1]
        rows = np.nonzero(sub.any(axis=1))[0]
        if len(rows) == 0:
            continue
        y0, y1 = int(rows.min()), int(rows.max()) + 1

        # Include neighbouring ink in the same x band that the size filter
        # dropped: vertical punctuation ("！", "？", "…") is a small standalone
        # glyph at the column edge. Merge row runs separated by less than one
        # glyph height, so the bubble outline further away is still excluded.
        # Extend over neighbouring glyph ink in the same x band. Vertical
        # punctuation ("、", "！", "…") occupies a mostly empty cell, so the gap
        # to the previous character can be a full line pitch - allow that, but
        # stay short of anything further away (bubble edge, next line).
        band = keep[:, x0:x1].any(axis=1)
        runs: list[list[int]] = []
        start = None
        for y in range(h):
            if band[y]:
                if start is None:
                    start = y
            elif start is not None:
                runs.append([start, y])
                start = None
        if start is not None:
            runs.append([start, h])

        if runs:
            main = next((r for r in runs if r[0] < y1 and r[1] > y0), None)
            if main is not None:
                y0, y1 = main
                gap_limit = max(4, int(med_h * 2.0))
                changed = True
                while changed:
                    changed = False
                    for run in runs:
                        if run[1] <= y0 and y0 - run[1] <= gap_limit:
                            y0 = run[0]
                            changed = True
                        elif run[0] >= y1 and run[0] - y1 <= gap_limit:
                            y1 = run[1]
                            changed = True

        if (y1 - y0) < (x1 - x0) * 1.2:
            continue                      # too square to be a vertical column
        columns.append((x0, y0, x1, y1))

    if len(columns) < 2 or len(columns) > max_columns:
        return []

    columns.sort(key=lambda c: c[0], reverse=True)   # Japanese reads right-to-left
    pad = max(2, int(min(w, h) * 0.02))
    result = []
    for x0, y0, x1, y1 in columns:
        bx = max(0, x0 - pad)
        by = max(0, y0 - pad)
        bw = min(w, x1 + pad) - bx
        bh = min(h, y1 + pad) - by
        result.append(QRectF(bx / w, by / h, bw / w, bh / h))
    return result


def crop_normalized(image: QImage, rect: QRectF) -> QImage:
    w, h = image.width(), image.height()
    x0 = max(0, min(w - 2, int(rect.x() * w)))
    y0 = max(0, min(h - 2, int(rect.y() * h)))
    x1 = max(x0 + 1, min(w, int((rect.x() + rect.width()) * w)))
    y1 = max(y0 + 1, min(h, int((rect.y() + rect.height()) * h)))
    return image.copy(x0, y0, x1 - x0, y1 - y0)
