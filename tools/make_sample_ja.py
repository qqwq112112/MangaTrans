# -*- coding: utf-8 -*-
"""Build a realistic vertical-text Japanese manga page for end-to-end tests.

Text is laid out right-to-left in vertical columns, the way real manga does it,
and sized so every column stays inside its speech bubble.
"""

from __future__ import annotations

import io
import sys
import zipfile
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

ROOT = Path(__file__).resolve().parent.parent
SAMPLES = ROOT / "samples"

FONT_CANDIDATES = [
    r"C:\Windows\Fonts\YuGothM.ttc",
    r"C:\Windows\Fonts\msgothic.ttc",
    r"C:\Windows\Fonts\msyh.ttc",
]

# Each bubble: bounding box + columns listed right-to-left.
PAGES = [
    {
        "bg": "#f4f1ea",
        "bubbles": [
            {"box": (80, 80, 660, 500),
             "columns": ["ちょっと待って、", "その声は……", "まさか、お前か？"]},
            {"box": (600, 620, 960, 1000),
             "columns": ["うるさい！", "あっち行けよ！"]},
        ],
    },
    {
        "bg": "#eef2f7",
        "bubbles": [
            {"box": (70, 90, 580, 470),
             "columns": ["ずっと、", "ここにいたのか。"]},
            {"box": (600, 560, 950, 1000),
             "columns": ["もう、", "遅すぎるよ。"]},
        ],
    },
]

FONT_SIZE = 38
CHAR_GAP = 4


def _font(size: int):
    for path in FONT_CANDIDATES:
        try:
            return ImageFont.truetype(path, size)
        except Exception:
            continue
    return ImageFont.load_default()


def _draw_bubble(draw, box, columns, font) -> None:
    draw.ellipse(box, fill="white", outline="black", width=4)
    x0, y0, x1, y1 = box
    cx = (x0 + x1) / 2.0
    cy = (y0 + y1) / 2.0

    step = font.size * 1.16
    total_w = step * (len(columns) - 1)
    left = cx + total_w / 2.0 - step * 0.35

    for i, text in enumerate(columns):
        col_h = len(text) * (font.size + CHAR_GAP)
        x = left - i * step
        y = cy - col_h / 2.0
        for ch in text:
            draw.text((x, y), ch, font=font, fill="black")
            y += font.size + CHAR_GAP


def build_page(spec: dict, index: int) -> Image.Image:
    img = Image.new("RGB", (1000, 1400), spec["bg"])
    draw = ImageDraw.Draw(img)
    draw.rectangle((20, 20, 980, 1380), outline="black", width=5)
    font = _font(FONT_SIZE)
    for bubble in spec["bubbles"]:
        _draw_bubble(draw, bubble["box"], bubble["columns"], font)
    draw.text((40, 1320), f"- {index} -", font=_font(26), fill="#555555")
    return img


def build() -> Path:
    SAMPLES.mkdir(parents=True, exist_ok=True)
    zip_path = SAMPLES / "sample_manga_ja.zip"
    with zipfile.ZipFile(zip_path, "w") as zf:
        for i, spec in enumerate(PAGES, start=1):
            buf = io.BytesIO()
            build_page(spec, i).save(buf, "JPEG", quality=94)
            # GBK-style names like older Japanese/Chinese scanlation packs.
            zf.writestr(f"第01話/page{i:02d}.jpg", buf.getvalue())
    print(zip_path)
    return zip_path


if __name__ == "__main__":
    sys.exit(0 if build() else 1)
