# -*- coding: utf-8 -*-
"""Persistent user configuration (%APPDATA%/MangaTrans/config.json)."""

from __future__ import annotations

import json
import os
from dataclasses import asdict, dataclass, field, fields
from pathlib import Path


def portable_root() -> Path | None:
    """Return the folder beside the exe when running in portable mode.

    A `portable.txt` marker next to the executable (or main.py) switches all
    data - settings, project progress, cache - into a `data` folder there, so
    the whole thing can be copied to a USB stick and moved between machines.
    """
    if os.environ.get("MANGATRANS_PORTABLE") == "1":
        marker_dir = Path(os.environ.get("MANGATRANS_HOME", "."))
        return Path(marker_dir).resolve()
    import sys
    base = getattr(sys, "_MEIPASS", None)
    candidate = Path(sys.executable).resolve().parent if base else         Path(__file__).resolve().parent.parent
    if (candidate / "portable.txt").exists():
        return candidate
    return None


def app_data_dir() -> Path:
    root = portable_root()
    if root is not None:
        path = root / "data"
        path.mkdir(parents=True, exist_ok=True)
        return path
    base = os.environ.get("APPDATA") or str(Path.home())
    path = Path(base) / "MangaTrans"
    path.mkdir(parents=True, exist_ok=True)
    return path


def cache_dir() -> Path:
    root = portable_root()
    if root is not None:
        path = root / "data" / "cache"
        path.mkdir(parents=True, exist_ok=True)
        return path
    base = os.environ.get("LOCALAPPDATA") or os.environ.get("TEMP") or str(Path.home())
    path = Path(base) / "MangaTrans" / "cache"
    path.mkdir(parents=True, exist_ok=True)
    return path


CONFIG_PATH = app_data_dir() / "config.json"


@dataclass
class AppConfig:
    # --- files / reading ---
    language: str = "zh"                # zh | en
    last_dir: str = ""
    reading_mode: str = "horizontal"      # horizontal | vertical
    last_width: int = 1360
    last_height: int = 880

    # --- translation model provider ---
    # Keys live in lmstudio.PROVIDERS (lmstudio/ollama/llamacpp/... for local,
    # openai/claude/deepseek/kimi/qwen/glm/minimax/gemini/siliconflow/custom).
    provider: str = "lmstudio"
    auto_translate: bool = False
    # Per-provider settings: {provider_key: {base_url, model, api_key, temperature}}
    provider_profiles: dict = field(default_factory=dict)
    # Autosave translation progress every N seconds (user asked for 10 minutes).
    autosave_seconds: int = 600

    # local provider: LM Studio
    lm_base_url: str = "http://127.0.0.1:1234/v1"
    lm_model: str = ""
    lm_temperature: float = 0.2

    # cloud provider: external OpenAI-compatible service
    api_base_url: str = "https://api.siliconflow.cn/v1"
    api_key: str = ""
    api_model: str = "Qwen/Qwen2.5-7B-Instruct"
    api_temperature: float = 0.3

    # --- OCR ---
    ocr_backend: str = "auto"             # auto | manga | windows | manual
    auto_ocr: bool = True
    ocr_language: str = "zh-Hans-CN"
    # Python interpreter that has manga-ocr installed. Empty = auto-detect.
    ocr_python: str = ""

    # --- default region style ---
    font_family: str = "Noto Sans SC"
    font_size_px: int = 0                 # 0 => auto fit
    bold: bool = False
    line_spacing: float = 1.12
    padding: float = 0.06
    rotation: float = 0.0
    letter_spacing: float = 0.0
    column_gap: float = 0.0
    vertical_text: bool = False
    fill_mode: str = "dominant"           # dominant | custom
    fill_color: str = "#FFFFFF"
    fill_shape: str = "rect"              # rect | ellipse
    fill_soft: int = 0                    # edge feather in page pixels
    text_color: str = "#111111"

    @classmethod
    def load(cls, path: Path | None = None) -> "AppConfig":
        path = path or CONFIG_PATH
        try:
            raw = path.read_text(encoding="utf-8-sig")
            data = json.loads(raw)
            known = {f.name for f in fields(cls)}
            clean = {k: v for k, v in data.items() if k in known}
            return cls(**clean)
        except Exception:
            return cls()

    def save(self, path: Path | None = None) -> None:
        path = path or CONFIG_PATH
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            payload = json.dumps(asdict(self), ensure_ascii=False, indent=2)
            path.write_text(payload, encoding="utf-8-sig")
        except Exception:
            pass
