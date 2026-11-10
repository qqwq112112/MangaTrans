# -*- coding: utf-8 -*-
"""External OCR worker: run manga-ocr in a *separate* Python process.

Why this exists
---------------
Bundling torch + transformers + unidic into the exe costs ~1.9 GB and a
5-minute rebuild for every OCR tweak. Instead the main exe stays a light UI
shell and shells out to `tools/ocr_worker.py`, which runs under any Python
that has manga-ocr installed. Fixing OCR is then just editing a .py file.

The worker protocol is a small JSON file, so a crashed/misbehaving worker can
never take the UI down with it.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path


def app_root() -> Path:
    """Directory holding tools/ - works frozen and from source."""
    base = getattr(sys, "_MEIPASS", None)
    if base:
        return Path(base)
    return Path(__file__).resolve().parent.parent


def worker_script() -> Path:
    return app_root() / "tools" / "ocr_worker.py"


def _python_candidates() -> list[str]:
    """Interpreters worth probing, most specific first."""
    found: list[str] = []

    def add(value: str | None) -> None:
        if value and value not in found:
            found.append(value)

    # 1) Explicit setting saved by the user in 设置.
    try:
        from .config import AppConfig
        add(AppConfig.load().ocr_python or None)
    except Exception:
        pass

    # 2) Source mode: the interpreter running us is the best candidate.
    if not getattr(sys, "frozen", False):
        add(sys.executable)

    # 3) The interpreter that pip'd manga-ocr into this machine.
    env_home = os.environ.get("LOCALAPPDATA", "")
    if env_home:
        add(str(Path(env_home) / "Programs" / "Python" / "Python312" / "python.exe"))
        add(str(Path(env_home) / "Programs" / "Python" / "Python311" / "python.exe"))
    add(os.path.expandvars(r"%LOCALAPPDATA%\Programs\Python\Python312\python.exe"))

    # 4) Whatever `python` / `py` resolve to on PATH.
    add("python")
    add("py")
    return found


def _probe(python: str, timeout: float = 12.0) -> dict | None:
    """Ask a candidate interpreter whether it can do manga OCR."""
    script = worker_script()
    if not script.exists():
        return None
    creationflags = getattr(subprocess, "CREATE_NO_WINDOW", 0) if os.name == "nt" else 0
    try:
        proc = subprocess.run(
            [python, str(script), "--check"],
            capture_output=True, text=True, timeout=timeout,
            creationflags=creationflags,
        )
    except Exception:
        return None
    if proc.returncode != 0 or not proc.stdout.strip():
        return None
    try:
        info = json.loads(proc.stdout.strip().splitlines()[-1])
    except Exception:
        return None
    info["_python"] = python
    return info


_CACHE: dict | None = None
_CACHE_KEY: tuple = ()


def _cache_path() -> Path:
    try:
        from .config import app_data_dir
        return app_data_dir() / "ocr_worker.json"
    except Exception:
        return Path(tempfile.gettempdir()) / "mangatrans_ocr_worker.json"


def _load_disk_cache() -> dict | None:
    """Remember the working interpreter across runs.

    Probing costs several seconds per candidate (each one imports torch), so
    without this every app start would stall. The cached entry is re-validated
    cheaply by checking the path still exists.
    """
    try:
        path = _cache_path()
        if not path.exists():
            return None
        data = json.loads(path.read_text(encoding="utf-8-sig"))
        python = data.get("python")
        if python and Path(python).exists() and data.get("manga_ocr"):
            return data
    except Exception:
        pass
    return None


def _save_disk_cache(info: dict) -> None:
    try:
        payload = {k: v for k, v in info.items() if not k.startswith("_")}
        payload["python"] = info.get("_python")
        _cache_path().write_text(
            json.dumps(payload, ensure_ascii=False), encoding="utf-8-sig")
    except Exception:
        pass


def find_worker_python(force: bool = False) -> tuple[str | None, dict]:
    """Locate a Python that has manga-ocr, caching the result.

    Returns (python_path_or_None, info_dict). An empty info means nothing was
    usable; callers should then fall back to Windows OCR or manual input.
    """
    global _CACHE, _CACHE_KEY
    candidates = tuple(_python_candidates())
    if not force and _CACHE is not None and _CACHE_KEY == candidates:
        chosen = _CACHE.get("_python")
        return chosen, _CACHE

    if not force:
        cached = _load_disk_cache()
        if cached:
            python = cached["python"]
            _CACHE = dict(cached)
            _CACHE["_python"] = python
            _CACHE_KEY = candidates
            return python, _CACHE

    for python in candidates:
        info = _probe(python)
        if info and info.get("manga_ocr"):
            _CACHE = info
            _CACHE_KEY = candidates
            _save_disk_cache(info)
            return python, info

    _CACHE = {}
    _CACHE_KEY = candidates
    return None, {}


def external_ocr_available(force: bool = False) -> bool:
    python, _info = find_worker_python(force=force)
    return python is not None


def run_external_ocr(image_path: Path, timeout: float = 300.0):
    """Run the worker on an image file and return an OCRResult-like payload."""
    from .ocr import OCRResult

    python, info = find_worker_python()
    if python is None:
        return OCRResult(
            error=(
                "找不到可用于日文 OCR 的 Python。请安装 Python 与 manga-ocr：\n"
                "    pip install manga-ocr\n"
                "然后在「设置 → 文字识别 → OCR Python 路径」里选中它。"
            )
        )

    script = worker_script()
    if not script.exists():
        return OCRResult(error=f"缺少 OCR worker 脚本：{script}")

    fd, out_name = tempfile.mkstemp(prefix="mgt_worker_", suffix=".json")
    os.close(fd)
    out_path = Path(out_name)
    creationflags = getattr(subprocess, "CREATE_NO_WINDOW", 0) if os.name == "nt" else 0
    try:
        proc = subprocess.run(
            [python, str(script), "--image", str(image_path), "--out", str(out_path)],
            capture_output=True, text=True, timeout=timeout,
            creationflags=creationflags,
        )
        if not out_path.exists():
            detail = (proc.stderr or proc.stdout or "").strip()
            return OCRResult(error=f"OCR worker 未返回结果：{detail[:400]}")
        data = json.loads(out_path.read_text(encoding="utf-8-sig"))
        if not data.get("ok"):
            return OCRResult(error=data.get("error") or "OCR worker 失败",
                             backend=data.get("backend") or "外部 worker")
        return OCRResult(
            text=data.get("text") or "",
            backend=data.get("backend") or "外部 worker",
            lines=data.get("lines") or [],
        )
    except subprocess.TimeoutExpired:
        return OCRResult(error="外部 OCR 超时（模型可能仍在加载）")
    except Exception as exc:
        return OCRResult(error=f"外部 OCR 调用失败：{exc}")
    finally:
        try:
            out_path.unlink(missing_ok=True)
        except Exception:
            pass
