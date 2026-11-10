# -*- coding: utf-8 -*-
"""Standalone OCR worker, run as a separate process.

This is the "external module" half of the split architecture: the main
MangaTrans.exe stays small (UI only, ~170 MB) and calls THIS script with a
Python that has manga-ocr installed. Torch / transformers / unidic (~1.9 GB)
never get packed into the exe, and OCR bugs can be fixed by editing this file
without rebuilding anything.

This file is deliberately SELF-CONTAINED: it must run under a plain Python
that only has `manga-ocr` and `pillow` installed, so it cannot import the
`mangatrans` package (which is frozen inside the exe).

Usage (what the app runs for you):

    python tools\\ocr_worker.py --image in.png --out out.json
    python tools\\ocr_worker.py --check          # is this interpreter usable?

Output JSON:
    {"ok": true, "text": "...", "backend": "manga-ocr 分栏", "lines": []}
    {"ok": false, "error": "..."}
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

MODEL_REPO = "manga-ocr-base"
MODEL_OWNER = "kha-white"


# ---------------------------------------------------------------- model cache

def model_cached() -> bool:
    """Is the manga-ocr weight file already on disk?"""
    base = os.environ.get("HF_HOME") or os.path.join(
        os.path.expanduser("~"), ".cache", "huggingface")
    hub = Path(base) / "hub" / f"models--{MODEL_OWNER}--{MODEL_REPO}"
    if not hub.is_dir():
        return False
    for root, _dirs, files in os.walk(hub / "snapshots"):
        if any(f.endswith((".bin", ".safetensors")) for f in files):
            return True
    return False


def _write(path: str, payload: dict) -> None:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8-sig")


def _check() -> int:
    info = {"python": sys.executable, "version": sys.version.split()[0]}
    try:
        import importlib.util
        info["manga_ocr"] = importlib.util.find_spec("manga_ocr") is not None
    except Exception as exc:
        info["manga_ocr"] = False
        info["manga_ocr_error"] = str(exc)
    info["model_cached"] = model_cached()
    print(json.dumps(info, ensure_ascii=False))
    return 0 if info.get("manga_ocr") else 1


# ---------------------------------------------------------------- OCR helpers

_MODEL = None


def _load_model():
    """Load MangaOcr, offline-first when the weights are cached.

    huggingface_hub freezes HF_HUB_OFFLINE at import time, so the flag must be
    set BEFORE importing manga_ocr. Getting this wrong turns a ~9 s load into
    minutes of connect-timeouts.
    """
    global _MODEL
    if _MODEL is not None:
        return _MODEL

    cached = model_cached()
    if cached:
        os.environ["HF_HUB_OFFLINE"] = "1"
        os.environ["TRANSFORMERS_OFFLINE"] = "1"
    try:
        from manga_ocr import MangaOcr
        _MODEL = MangaOcr()
        return _MODEL
    finally:
        if cached:
            os.environ.pop("HF_HUB_OFFLINE", None)
            os.environ.pop("TRANSFORMERS_OFFLINE", None)


_CJK = "\u3000-\u303f\u3040-\u30ff\u3400-\u4dbf\u4e00-\u9fff\uff00-\uffef"


def _clean(text: str) -> str:
    """Drop the spaces Windows-style OCR inserts between CJK glyphs."""
    import re
    text = (text or "").replace("\r\n", "\n").replace("\r", "\n")
    for _ in range(3):
        new = re.sub(rf"(?<=[{_CJK}])[ \t]+(?=[{_CJK}])", "", text)
        if new == text:
            break
        text = new
    return "\n".join(line.strip() for line in text.split("\n")).strip()


def _detect_columns(gray):
    """Split a bubble into vertical text columns, right-to-left.

    Returns a list of (x0, y0, x1, y1) in pixels, or [] when the region does
    not look like multi-column vertical text.
    """
    import numpy as np

    h, w = gray.shape
    if w < 20 or h < 20:
        return []

    try:
        import cv2
        blurred = cv2.GaussianBlur(gray, (3, 3), 0)
        _, mask = cv2.threshold(blurred, 0, 255,
                                cv2.THRESH_BINARY_INV + cv2.THRESH_OTSU)
        mask = mask > 0
        n, _labels, stats, _c = cv2.connectedComponentsWithStats(
            mask.astype(np.uint8), connectivity=8)
        boxes = [(int(stats[i][0]), int(stats[i][1]),
                  int(stats[i][2]), int(stats[i][3]), int(stats[i][4]))
                 for i in range(1, n)]
    except Exception:
        return []

    if len(boxes) < 4:
        return []

    candidates = []
    for x, y, cw, ch, area in boxes:
        if cw >= 0.72 * w and ch >= 0.72 * h:
            continue
        if cw >= 0.85 * w and ch <= 0.06 * h:
            continue
        if ch >= 0.85 * h and cw <= 0.05 * w:
            continue
        if area < max(6, 0.0004 * w * h):
            continue
        if cw > 0.55 * w:
            continue
        candidates.append((x, y, cw, ch, area))
    if len(candidates) < 4:
        return []

    solid = [c for c in candidates
             if c[2] >= 3 and c[3] >= 3
             and c[4] / float(max(1, c[2] * c[3])) >= 0.15]
    if len(solid) < 4:
        return []

    med_w = float(np.median([c[2] for c in solid]))
    med_h = float(np.median([c[3] for c in solid]))
    glyphs = [(x, y, cw, ch) for x, y, cw, ch, _a in solid
              if cw <= max(med_w * 3.0, 0.5 * w)
              and ch <= max(med_h * 3.0, 0.9 * h)]
    if len(glyphs) < 4:
        return []

    keep = np.zeros_like(mask)
    for x, y, cw, ch in glyphs:
        keep[y:y + ch, x:x + cw] = True

    profile = keep.sum(axis=0)
    if profile.max() < 3:
        return []

    min_ink = max(3, int(h * 0.10))
    runs = []
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

    gap = max(1, int(w * 0.006))
    merged = []
    for run in runs:
        if merged and run[0] - merged[-1][1] <= gap:
            merged[-1][1] = run[1]
        else:
            merged.append(run)

    med_run = float(np.median([r[1] - r[0] for r in merged])) if merged else 0.0
    final = []
    for x0, x1 in merged:
        width = x1 - x0
        if med_run and width > med_run * 1.75:
            seg = profile[x0:x1]
            lo = max(1, int(len(seg) * 0.3))
            hi = max(lo + 1, int(len(seg) * 0.7))
            cut = int(np.argmin(seg[lo:hi])) + lo
            if 2 < cut < width - 2:
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

        band = keep[:, x0:x1].any(axis=1)
        band_runs = []
        start = None
        for y in range(h):
            if band[y]:
                if start is None:
                    start = y
            elif start is not None:
                band_runs.append([start, y])
                start = None
        if start is not None:
            band_runs.append([start, h])

        if band_runs:
            main = next((r for r in band_runs if r[0] < y1 and r[1] > y0), None)
            if main is not None:
                y0, y1 = main
                limit = max(4, int(med_h * 2.0))
                changed = True
                while changed:
                    changed = False
                    for r in band_runs:
                        if r[1] <= y0 and y0 - r[1] <= limit:
                            y0 = r[0]
                            changed = True
                        elif r[0] >= y1 and r[0] - y1 <= limit:
                            y1 = r[1]
                            changed = True

        if (y1 - y0) < (x1 - x0) * 1.2:
            continue
        columns.append((x0, y0, x1, y1))

    if len(columns) < 2 or len(columns) > 8:
        return []

    columns.sort(key=lambda c: c[0], reverse=True)   # right to left
    return columns


def _run(image_path: str, out_path: str) -> int:
    try:
        from PIL import Image
        import numpy as np
    except Exception as exc:
        _write(out_path, {"ok": False, "error": f"缺少依赖：{exc}"})
        return 1

    try:
        image = Image.open(image_path).convert("RGB")
    except Exception as exc:
        _write(out_path, {"ok": False, "error": f"无法读取图片：{exc}"})
        return 1

    try:
        model = _load_model()
    except Exception as exc:
        hint = ""
        if not model_cached():
            hint = ("\n模型尚未下载。请设置镜像后重试：\n"
                    "    set HF_ENDPOINT=https://hf-mirror.com\n"
                    "或挂代理运行一次让模型下载完成（约 400 MB）。")
        _write(out_path, {"ok": False, "error": f"manga-ocr 加载失败：{exc}{hint}"})
        return 1

    try:
        gray = np.array(image.convert("L"))
        columns = _detect_columns(gray)
        if len(columns) >= 2:
            parts = []
            for x0, y0, x1, y1 in columns:
                pad = max(2, int(min(gray.shape) * 0.02))
                box = (max(0, x0 - pad), max(0, y0 - pad),
                       min(image.width, x1 + pad), min(image.height, y1 + pad))
                if box[2] - box[0] < 2 or box[3] - box[1] < 2:
                    continue
                text = (model(image.crop(box)) or "").strip()
                if text:
                    parts.append(text)
            if parts:
                _write(out_path, {"ok": True, "text": _clean("\n".join(parts)),
                                  "backend": "manga-ocr 分栏", "lines": []})
                return 0

        text = _clean((model(image) or "").strip())
        _write(out_path, {"ok": bool(text), "text": text,
                          "backend": "manga-ocr", "lines": [],
                          "error": "" if text else "识别结果为空"})
        return 0 if text else 1
    except Exception as exc:
        _write(out_path, {"ok": False, "error": f"识别失败：{exc}"})
        return 1


def main() -> int:
    parser = argparse.ArgumentParser(description="MangaTrans OCR worker")
    parser.add_argument("--image")
    parser.add_argument("--out")
    parser.add_argument("--check", action="store_true",
                        help="print capabilities as JSON and exit")
    args = parser.parse_args()

    if args.check:
        return _check()
    if not args.image or not args.out:
        parser.error("--image and --out are required (or use --check)")
    return _run(args.image, args.out)


if __name__ == "__main__":
    sys.exit(main())
