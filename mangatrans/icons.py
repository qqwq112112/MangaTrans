# -*- coding: utf-8 -*-
"""Application icon loading.

The icon lives in `assets/icon.ico` both in the source tree and inside the
PyInstaller bundle (`sys._MEIPASS`). Loading is defensive: a missing or corrupt
icon must never prevent the app from starting.
"""

from __future__ import annotations

import sys
from functools import lru_cache
from pathlib import Path

from PySide6.QtGui import QIcon, QPixmap


def asset_path(name: str) -> Path:
    """Resolve a bundled asset both from source and from a frozen build."""
    base = getattr(sys, "_MEIPASS", None)
    root = Path(base) if base else Path(__file__).resolve().parent.parent
    return root / "assets" / name


@lru_cache(maxsize=2)
def app_icon() -> QIcon:
    """Window / taskbar icon. Returns an empty QIcon if nothing is found."""
    for name in ("icon.ico", "icon_256.png", "icon.png"):
        path = asset_path(name)
        if path.exists():
            icon = QIcon(str(path))
            if not icon.isNull():
                return icon
    return QIcon()


@lru_cache(maxsize=1)
def app_pixmap(size: int = 256) -> QPixmap:
    """Square pixmap for splash screens or about dialogs."""
    for name in ("icon_256.png", "icon.png", "icon.ico"):
        path = asset_path(name)
        if path.exists():
            pix = QPixmap(str(path))
            if not pix.isNull():
                return pix.scaled(size, size)
    return QPixmap()
