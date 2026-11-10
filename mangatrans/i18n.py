# -*- coding: utf-8 -*-
"""Minimal runtime translation (i18n).

Why not Qt .ts/.qm files
------------------------
Those need `lupdate`/`lrelease` tooling and a build step just to change a label.
This app's UI strings are few and live in code, so a plain dict keeps the whole
thing editable, reviewable and diff-able. Switching language applies immediately
(no restart) by re-writing the affected labels.

Usage
-----
    from .i18n import tr, set_language, current_language

    label.setText(tr("Open"))          # looks up the active language
    set_language("en")                 # then call apply_* to refresh visible UI

Missing keys fall back to the key itself, so an untranslated string shows the
Chinese (source) text rather than crashing or showing blanks.
"""

from __future__ import annotations

LANGS = (
    ("zh", "简体中文"),
    ("en", "English"),
)

_current = "zh"

# key -> {lang: text}. Key is the Chinese source string, which keeps the code
# readable and makes "no translation" degrade to correct Chinese rather than
# to a raw identifier.
_DICT: dict[str, dict[str, str]] = {}


def _add(zh: str, en: str) -> None:
    _DICT[zh] = {"zh": zh, "en": en}


def current_language() -> str:
    return _current


def set_language(lang: str) -> None:
    global _current
    _current = lang if lang in ("zh", "en") else "zh"


def tr(text: str) -> str:
    """Translate a source (Chinese) string into the active language."""
    entry = _DICT.get(text)
    if entry is None:
        return text
    return entry.get(_current) or text


def trf(text: str, **values) -> str:
    """Translate then substitute {placeholders}."""
    try:
        return tr(text).format(**values)
    except Exception:
        return tr(text)


# ---------------------------------------------------------------- dictionary
# Only user-visible chrome is translated. Long-form text (help / about /
# license bodies) stays bilingual in the dialog itself, because translating
# several paragraphs per language is better handled by the README.

# --- main window: header
_add("打开", "Open")
_add("项目库", "Library")
_add("项目 {count}", "Library {count}")
_add("保存", "Save")
_add("左右翻页", "Page")
_add("上下翻页", "Scroll")
_add("← 上一步", "← Undo")
_add("下一步 →", "Redo →")
_add("视图 ↶", "View ↶")
_add("视图 ↷", "View ↷")
_add("导出页", "Export page")
_add("导出夹", "Export folder")
_add("导出ZIP", "Export ZIP")
_add("设置", "Settings")
_add("未打开文件", "No file")

# --- main window: footer
_add("‹ 上一页", "‹ Prev")
_add("下一页 ›", "Next ›")
_add("待确认选区 {count} 处", "{count} selection(s) pending")
_add("撤销选区", "Undo box")
_add("取消选区", "Clear boxes")
_add("滚轮缩放 · 左键长按框选 · 右击确认",
     "Wheel to zoom · long-press to select · right-click to confirm")
_add("适应窗口", "Fit window")
_add("适应宽度", "Fit width")
_add("原始大小", "Actual size")
_add("页", "p")

# --- menus
_add("文件", "File")
_add("视图", "View")
_add("工具", "Tools")
_add("帮助", "Help")
_add("撤销上一步", "Undo")
_add("快捷键与用法", "Shortcuts & usage")
_add("联系作者", "Contact author")
_add("开源声明（无需登录）", "Open source (no login)")
_add("关于", "About")
_add("设置…", "Settings…")
_add("退出", "Quit")

# --- region dialog: sections
_add("选区翻译", "Region translation")
_add("编辑已有翻译", "Edit existing region")
_add("共 {count} 处选区", "{count} region(s)")
_add("底色", "Fill")
_add("字体", "Font")
_add("字号", "Size")
_add("行距", "Line gap")
_add("边距", "Padding")
_add("加粗", "Bold")
_add("字间距", "Letter gap")
_add("列间距", "Column gap")
_add("旋转", "Rotate")
_add("文字颜色", "Text colour")
_add("原文（OCR / 手动输入）", "Source (OCR / manual)")
_add("译文", "Translation")
_add("识别本选区", "OCR this region")
_add("全部识别", "OCR all")
_add("翻译（LM Studio）", "Translate")
_add("全部翻译", "Translate all")
_add("单独覆写（不改面板，只写文字）", "Overwrite only (keep panel open)")
_add("一键直通：识别 → 翻译 → 覆写", "One-click: OCR → translate → overwrite")
_add("应用到画面", "Apply to page")
_add("取消", "Cancel")
_add("删除此区域", "Delete region")
_add("方形", "Rect")
_add("圆角", "Rounded")
_add("椭圆（圆形气泡）", "Ellipse")
_add("自定义描边", "Custom outline")
_add("不填充（只写字）", "No fill (text only)")
_add("横排 ←", "Horizontal ←")
_add("竖排 ↓", "Vertical ↓")
_add("取主色", "Dominant")
_add("吸管", "Pick")
_add("调色…", "Colour…")
_add("画笔", "Brush")
_add("颜色…", "Colour…")
_add("粗细", "Width")
_add("清空涂鸦", "Clear strokes")
_add("清除自定义描边", "Clear outline")
_add("羽化", "Feather")

# --- settings
_add("翻译模型", "Translation model")
_add("供应商", "Provider")
_add("测试连接", "Test")
_add("目标语言", "Target language")
_add("简体中文（固定）", "Simplified Chinese (fixed)")
_add("识别完成后自动翻译", "Translate automatically after OCR")
_add("接口地址", "Endpoint")
_add("API Key", "API key")
_add("模型", "Model")
_add("温度", "Temperature")
_add("自动保存进度", "Autosave progress")
_add("文字识别（OCR）", "Text recognition (OCR)")
_add("识别引擎", "Engine")
_add("Windows OCR 语言", "Windows OCR language")
_add("打开选区时自动识别原文", "OCR automatically when a region opens")
_add("默认文字样式", "Default text style")
_add("保存", "Save")
_add("浏览…", "Browse…")
_add("显示", "Show")
_add("分钟", "min")
_add("界面语言", "Language")

# --- notifications / common
_add("知道了", "OK")
_add("确定", "OK")
_add("继续", "Continue")
_add("立即下载", "Download now")
_add("以后再说", "Later")
_add("已保存进度", "Progress saved")
_add("没有可撤销的操作", "Nothing to undo")
_add("翻译完成", "Translation done")
_add("识别完成", "OCR done")
_add("已导出", "Exported")
_add("打开失败", "Could not open")
_add("导出失败", "Export failed")
_add("不支持的文件", "Unsupported file")
