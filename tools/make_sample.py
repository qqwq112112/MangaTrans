# -*- coding: utf-8 -*-
"""Generate sample manga-like pages and a zip for testing."""

from __future__ import annotations

import io
import sys
import zipfile
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

ROOT = Path(__file__).resolve().parent.parent
SAMPLES = ROOT / "samples"

FONT_PATH = r"C:\Windows\Fonts\msyh.ttc"


def _font(size: int):
    try:
        return ImageFont.truetype(FONT_PATH, size)
    except Exception:
        return ImageFont.load_default()


def make_page(index: int, title: str, lines: list[str], color: str) -> Image.Image:
    img = Image.new("RGB", (1000, 1450), color)
    d = ImageDraw.Draw(img)
    # Panel borders
    d.rectangle((40, 40, 960, 700), outline="black", width=6)
    d.rectangle((40, 730, 470, 1410), outline="black", width=6)
    d.rectangle((510, 730, 960, 1410), outline="black", width=6)

    # Speech bubble with vertical-ish text block
    d.ellipse((120, 110, 880, 470), fill="white", outline="black", width=5)
    f = _font(56)
    y = 180
    for line in lines:
        d.text((180, y), line, font=f, fill="black")
        y += 96
    d.text((60, 600), title, font=_font(34), fill="#444444")
    d.text((70, 760), f"page {index}", font=_font(30), fill="#666666")
    return img


def build() -> Path:
    SAMPLES.mkdir(parents=True, exist_ok=True)
    pages = [
        ("第1页", ["今天天气真不错。", "要不要一起出去？"], "#f2ede2"),
        ("第2页", ["等等，那个声音是……", "你听见了吗？"], "#eef1f6"),
        ("第3页", ["原来你一直在这里。", "太好了，终于找到了。"], "#f5efe9"),
    ]
    zip_path = SAMPLES / "sample_manga.zip"
    with zipfile.ZipFile(zip_path, "w") as zf:
        for i, (title, lines, color) in enumerate(pages, start=1):
            img = make_page(i, title, lines, color)
            buf = io.BytesIO()
            img.save(buf, "JPEG", quality=92)
            # Intentionally non-UTF8-safe order names, plus a nested folder.
            zf.writestr(f"chapter01/page{i}_分镜.jpg", buf.getvalue())
    print(zip_path)
    return zip_path


if __name__ == "__main__":
    sys.exit(0 if build() else 1)
