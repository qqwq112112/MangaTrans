# -*- coding: utf-8 -*-
"""Font discovery and preset resolution."""

from __future__ import annotations

from functools import lru_cache

from PySide6.QtGui import QFontDatabase

from .constants import (
    DEFAULT_FONT_CANDIDATES,
    FONT_PRESETS,
    FONT_PRESETS_EXTRA,
)


@lru_cache(maxsize=1)
def installed_families() -> set[str]:
    return set(QFontDatabase.families())


def default_font_family() -> str:
    fams = installed_families()
    for candidate in DEFAULT_FONT_CANDIDATES:
        if candidate in fams:
            return candidate
    return "Microsoft YaHei" if "Microsoft YaHei" in fams else "SimSun"


def _installed(presets) -> list[tuple[str, str]]:
    fams = installed_families()
    return [(family, label) for family, label in presets if family in fams]


def available_presets() -> list[tuple[str, str]]:
    """[(family, display label)] of Chinese manga fonts installed here."""
    result = _installed(FONT_PRESETS)
    if not result:
        result.append((default_font_family(), default_font_family()))
    return result


def available_presets_extra() -> list[tuple[str, str]]:
    """Japanese / Latin families installed here."""
    return _installed(FONT_PRESETS_EXTRA)


def label_for_family(family: str) -> str:
    for fam, label in FONT_PRESETS + FONT_PRESETS_EXTRA:
        if fam == family:
            return label
    return family
