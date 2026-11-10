# -*- coding: utf-8 -*-
"""Shared constants for MangaTrans."""

APP_NAME = "MangaTrans"
APP_VERSION = "1.0.0"
APP_TITLE = "MangaTrans · 漫画汉化工作台"

# Image formats Qt can decode out of the box on Windows.
IMAGE_EXTS = {
    ".jpg", ".jpeg", ".jpe", ".png", ".webp", ".bmp",
    ".gif", ".tif", ".tiff", ".avif", ".ico",
}

ARCHIVE_EXTS = {".zip", ".cbz"}

# Fill palettes offered in the region editor.
FILL_PRESETS = [
    ("纯白", "#FFFFFF"),
    ("米白", "#FAF6EC"),
    ("奶油", "#FFF3D6"),
    ("浅灰", "#EAEAEA"),
    ("中灰", "#BDBDBD"),
    ("深灰", "#555555"),
    ("纯黑", "#111111"),
    ("淡粉", "#FFE9EE"),
    ("淡蓝", "#E7F1FF"),
    ("淡绿", "#E9F7EC"),
]

TEXT_COLORS = [
    ("近黑", "#111111"),
    ("纯白", "#FFFFFF"),
    ("深灰", "#3A3A3A"),
    ("赭红", "#B93A32"),
]

# "Manga friendly" Chinese fonts. The label is what users see.
FONT_PRESETS = [
    ("Noto Sans SC", "思源黑体"),
    ("Microsoft YaHei", "微软雅黑"),
    ("Microsoft YaHei UI", "微软雅黑 UI"),
    ("SimHei", "黑体"),
    ("DengXian", "等线"),
    ("SimSun", "宋体"),
    ("NSimSun", "新宋体"),
    ("KaiTi", "楷体"),
    ("STKaiti", "华文楷体"),
    ("FangSong", "仿宋"),
    ("STFangsong", "华文仿宋"),
    ("YouYuan", "幼圆"),
    ("方正姚体", "方正姚体"),
    ("方正舒体", "方正舒体"),
]

# Japanese / Latin families. Useful for sound effects and for previewing the
# original text while proof-reading.
FONT_PRESETS_EXTRA = [
    ("Yu Gothic", "游哥特（日）"),
    ("Yu Gothic UI", "游哥特 UI（日）"),
    ("Yu Mincho", "游明朝（日）"),
    ("MS Gothic", "MS 哥特（日）"),
    ("MS PGothic", "MS PGothic（日）"),
    ("Meiryo", "明利（日）"),
    ("Noto Sans JP", "思源黑体（日）"),
    ("Noto Serif JP", "思源宋体（日）"),
    ("Segoe UI", "Segoe UI"),
    ("Arial", "Arial"),
]

DEFAULT_FONT_CANDIDATES = [
    "Noto Sans SC", "Microsoft YaHei UI", "Microsoft YaHei", "SimHei", "SimSun",
]

OCR_LANGUAGES = [
    ("zh-Hans-CN", "中文（简体）"),
    ("ja-JP", "日本語（需系统语言包）"),
    ("en-US", "English"),
]
