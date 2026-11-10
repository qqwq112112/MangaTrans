# -*- coding: utf-8 -*-
"""Colour sampling: dominant colour of a region, pixel picking."""

from __future__ import annotations

from collections import defaultdict

from PySide6.QtCore import QRectF
from PySide6.QtGui import QColor, QImage

DEFAULT_FALLBACK = QColor("#FFFFFF")


def _region_pixels(image: QImage, rect: QRectF) -> tuple[int, int, int, int]:
    w, h = image.width(), image.height()
    x0 = max(0, min(w - 1, int(rect.x() * w)))
    y0 = max(0, min(h - 1, int(rect.y() * h)))
    x1 = max(x0 + 1, min(w, int((rect.x() + rect.width()) * w)))
    y1 = max(y0 + 1, min(h, int((rect.y() + rect.height()) * h)))
    return x0, y0, x1, y1


def dominant_color(image: QImage, rect: QRectF, max_samples: int = 7000) -> QColor:
    """Most common colour inside rect (normalized coordinates).

    Colours are quantized to 4 bits per channel, then the average of the
    winning bucket is returned, which avoids returning a noisy pixel.
    """
    if image is None or image.isNull():
        return QColor(DEFAULT_FALLBACK)

    x0, y0, x1, y1 = _region_pixels(image, rect)
    area = max(1, (x1 - x0) * (y1 - y0))
    step = max(1, int((area / max_samples) ** 0.5))

    buckets: dict[tuple[int, int, int], list[int]] = defaultdict(lambda: [0, 0, 0, 0])
    for y in range(y0, y1, step):
        for x in range(x0, x1, step):
            c = image.pixelColor(x, y)
            key = (c.red() >> 4, c.green() >> 4, c.blue() >> 4)
            b = buckets[key]
            b[0] += c.red()
            b[1] += c.green()
            b[2] += c.blue()
            b[3] += 1

    if not buckets:
        return QColor(DEFAULT_FALLBACK)

    best = max(buckets.values(), key=lambda b: b[3])
    n = max(1, best[3])
    return QColor(best[0] // n, best[1] // n, best[2] // n)


def color_at(image: QImage, nx: float, ny: float) -> QColor:
    """Colour at normalized position."""
    if image is None or image.isNull():
        return QColor(DEFAULT_FALLBACK)
    x = max(0, min(image.width() - 1, int(nx * image.width())))
    y = max(0, min(image.height() - 1, int(ny * image.height())))
    return image.pixelColor(x, y)


def contrast_text_color(background: QColor) -> QColor:
    """Black or white, whichever reads better on the given background."""
    # Relative luminance approximation.
    lum = 0.299 * background.red() + 0.587 * background.green() + 0.114 * background.blue()
    return QColor("#111111") if lum > 150 else QColor("#FFFFFF")
