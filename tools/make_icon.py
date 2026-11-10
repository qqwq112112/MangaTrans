# -*- coding: utf-8 -*-
"""Generate the application icon.

Design notes
------------
The icon must stay readable at 16x16 (taskbar, file list), so it deliberately
avoids CJK glyphs - at that size Chinese strokes turn to mush. Instead it uses
geometry only: a dark rounded tile with a teal speech bubble and two text lines,
which reads as "comic + text" at any size.

Outputs:
    assets/icon.ico         windows icon, 16..256 px
    assets/icon_256.png     preview / README
    assets/icon.png         1024px master
"""

from __future__ import annotations

import pathlib

from PIL import Image, ImageDraw

ROOT = pathlib.Path(__file__).resolve().parent.parent
OUT = ROOT / "assets"

BG_TOP = (20, 26, 36)
BG_BOTTOM = (12, 16, 23)
TEAL = (45, 212, 191)
TEAL_DARK = (31, 156, 141)
LINE = (222, 240, 238)


def rounded_tile(size: int, radius_ratio: float = 0.22) -> Image.Image:
    """Dark rounded square with a subtle vertical gradient."""
    tile = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    mask = Image.new("L", (size, size), 0)
    ImageDraw.Draw(mask).rounded_rectangle(
        (0, 0, size - 1, size - 1),
        radius=int(size * radius_ratio),
        fill=255,
    )

    grad = Image.new("RGBA", (size, size))
    px = grad.load()
    for y in range(size):
        t = y / max(1, size - 1)
        px_row = tuple(
            int(BG_TOP[i] + (BG_BOTTOM[i] - BG_TOP[i]) * t) for i in range(3)
        ) + (255,)
        for x in range(size):
            px[x, y] = px_row

    tile.paste(grad, (0, 0), mask)
    return tile


def draw_icon(size: int) -> Image.Image:
    """Speech bubble with two text lines, drawn at the target resolution.

    Everything is drawn at the final size (no downscaling of a big master) so
    strokes stay crisp even at 16px.
    """
    img = rounded_tile(size)
    d = ImageDraw.Draw(img)

    # --- speech bubble ----------------------------------------------------
    m = size * 0.16                     # margin
    bw = size - 2 * m                   # bubble width
    bh = bw * 0.74                      # bubble body height
    left, top = m, m * 1.05
    right, bottom = left + bw, top + bh
    stroke = max(1, int(round(size * 0.055)))

    d.rounded_rectangle(
        (left, top, right, bottom),
        radius=int(bh * 0.34),
        outline=TEAL,
        width=stroke,
    )

    # Tail: a small triangle at the lower-left, drawn as a filled teal wedge so
    # it survives 16px rendering.
    tw = bw * 0.20
    th = bh * 0.30
    tail = [
        (left + bw * 0.26, bottom - stroke * 0.5),
        (left + bw * 0.20, bottom + th),
        (left + bw * 0.26 + tw, bottom - stroke * 0.5),
    ]
    d.polygon(tail, fill=TEAL)

    # --- two text lines ---------------------------------------------------
    line_h = max(1, int(round(size * 0.062)))
    gap = bh * 0.26
    lx0 = left + bw * 0.20
    for i, ratio in enumerate((0.58, 0.40)):
        lx1 = lx0 + bw * ratio
        ly = top + bh * 0.34 + i * gap
        r = line_h / 2
        d.rounded_rectangle(
            (lx0, ly - r, lx1, ly + r),
            radius=r,
            fill=LINE,
        )

    # A small accent dot on the last line hints at "translated text".
    dot_r = max(1.0, size * 0.045)
    d.ellipse(
        (lx1 + gap * 0.32, top + bh * 0.34 + gap - dot_r,
         lx1 + gap * 0.32 + dot_r * 2, top + bh * 0.34 + gap + dot_r),
        fill=TEAL_DARK,
    )

    return img


def main() -> int:
    OUT.mkdir(parents=True, exist_ok=True)

    sizes = [16, 20, 24, 32, 40, 48, 64, 128, 256]
    frames = [draw_icon(s) for s in sizes]

    ico = OUT / "icon.ico"
    frames[-1].save(
        ico, format="ICO",
        sizes=[(s, s) for s in sizes],
        append_images=frames[:-1],
    )

    draw_icon(256).save(OUT / "icon_256.png", "PNG")
    draw_icon(1024).save(OUT / "icon.png", "PNG")

    print(f"icon.ico     {ico.stat().st_size/1024:.1f} KB  "
          f"({len(sizes)} 个尺寸: {sizes})")
    print(f"icon_256.png {(OUT/'icon_256.png').stat().st_size/1024:.1f} KB")
    print(f"icon.png     {(OUT/'icon.png').stat().st_size/1024:.1f} KB")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
