# -*- coding: utf-8 -*-
"""Local OCR backends.

1. manga-ocr  (optional, best for Japanese manga; pip install manga-ocr)
2. Windows.Media.Ocr through a bundled PowerShell helper (zh-Hans / en-US)
3. manual input (always available in the UI)

The translation module itself talks to LM Studio; OCR is deliberately
pluggable because the installed model set decides what is possible.
"""

from __future__ import annotations

import importlib.util
import io
import json
import os
import re
import subprocess
import sys
import tempfile
from dataclasses import dataclass, field
from pathlib import Path

from PySide6.QtCore import QBuffer, QIODevice
from PySide6.QtGui import QImage


def resource_path(relative: str) -> Path:
    """Resolve a bundled resource both in source tree and PyInstaller bundle."""
    base = getattr(sys, "_MEIPASS", None)
    if base:
        return Path(base) / relative
    return Path(__file__).resolve().parent.parent / relative


@dataclass
class OCRResult:
    text: str = ""
    backend: str = ""
    error: str = ""
    lines: list[dict] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.error and bool(self.text.strip())


_CJK_SPACE_RE = re.compile(
    r"(?<=[\u3000-\u303f\u3040-\u30ff\u3400-\u4dbf\u4e00-\u9fff\uff00-\uffef])"
    r"[ \t]+"
    r"(?=[\u3000-\u303f\u3040-\u30ff\u3400-\u4dbf\u4e00-\u9fff\uff00-\uffef])"
)


def clean_ocr_text(text: str) -> str:
    """Windows OCR inserts spaces between CJK glyphs; remove them."""
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    for _ in range(3):
        new = _CJK_SPACE_RE.sub("", text)
        if new == text:
            break
        text = new
    return "\n".join(line.strip() for line in text.split("\n")).strip()


def manga_ocr_available() -> bool:
    return importlib.util.find_spec("manga_ocr") is not None


def windows_ocr_available() -> bool:
    return os.name == "nt" and resource_path("tools/win_ocr.ps1").exists()


def available_backends() -> list[str]:
    result = []
    if manga_ocr_available():
        result.append("manga")
    elif _external_worker_ready():
        result.append("manga-worker")
    if windows_ocr_available():
        result.append("windows")
    return result


def _external_worker_ready() -> bool:
    try:
        from .ocr_worker_client import external_ocr_available
        return external_ocr_available()
    except Exception:
        return False


def describe_backends() -> str:
    names = []
    if manga_ocr_available():
        names.append("manga-ocr（日文漫画）")
    elif _external_worker_ready():
        names.append("manga-ocr（外部 worker）")
    if windows_ocr_available():
        names.append("Windows OCR（中/英）")
    return "、".join(names) if names else "无（仅手动输入）"


def _qimage_to_png_bytes(image: QImage) -> bytes:
    buf = QBuffer()
    buf.open(QIODevice.WriteOnly)
    image.save(buf, "PNG")
    data = bytes(buf.data())
    buf.close()
    return data


def safe_ocr_temp_png(image: QImage) -> Path:
    fd, name = tempfile.mkstemp(prefix="mgt_ocr_", suffix=".png")
    os.close(fd)
    path = Path(name)
    image.save(str(path), "PNG")
    return path


_MANGA_MODEL = None
_MANGA_ERROR = ""


def manga_model_cached() -> bool:
    """True when the manga-ocr weights are already downloaded.

    The weights live in the HuggingFace cache, not inside the packaged exe, so
    a fresh machine needs one download before Japanese OCR can work.
    """
    base = os.environ.get("HF_HOME") or os.path.join(
        os.path.expanduser("~"), ".cache", "huggingface")
    hub = os.path.join(base, "hub", "models--kha-white--manga-ocr-base")
    if not os.path.isdir(hub):
        return False
    for root, _dirs, files in os.walk(os.path.join(hub, "snapshots")):
        if any(name.endswith((".bin", ".safetensors")) for name in files):
            return True
    return False


def _load_manga_model():
    """Create the MangaOcr instance, tolerating a machine without network.

    The offline flag MUST be set before `manga_ocr` is imported:
    huggingface_hub freezes HF_HUB_OFFLINE into a module constant at import
    time, so setting it afterwards has no effect. Measured on this machine,
    getting that order wrong turns a 9 s load into a 3 min 20 s stall of
    connect-timeouts (5 retries per file).

    When the weights are cached we therefore go offline immediately. When they
    are not, online is the only option - that attempt is what downloads them.
    """
    global _MANGA_MODEL, _MANGA_ERROR
    if _MANGA_MODEL is not None:
        return _MANGA_MODEL

    cached = manga_model_cached()
    if cached:
        os.environ["HF_HUB_OFFLINE"] = "1"
        os.environ["TRANSFORMERS_OFFLINE"] = "1"

    try:
        from manga_ocr import MangaOcr     # imports hugggingface_hub too
        _MANGA_MODEL = MangaOcr()
        return _MANGA_MODEL
    except Exception as exc:
        _MANGA_MODEL = None
        _MANGA_ERROR = str(exc)
        raise RuntimeError(_MANGA_ERROR) from exc
    finally:
        if cached:
            # Undo the flag so unrelated code in this process is not silently
            # forced offline. The hub constant is already fixed either way.
            os.environ.pop("HF_HUB_OFFLINE", None)
            os.environ.pop("TRANSFORMERS_OFFLINE", None)


def _manga_failure_hint(exc: Exception) -> str:
    """Turn a raw load error into something the user can act on."""
    detail = str(exc)
    lowered = detail.lower()
    looks_network = any(key in lowered for key in (
        "connection", "connect", "timeout", "timed out", "resolve",
        "ssl", "proxy", "offline", "unreachable", "max retries",
    ))
    if manga_model_cached():
        return (
            f"manga-ocr 模型加载失败：{detail}\n"
            "模型文件已在本地，可能是文件损坏或依赖缺失。"
            "可执行 --selfcheck-ocr 查看详细报告。"
        )
    if looks_network:
        return (
            f"manga-ocr 模型尚未下载，且无法连接 HuggingFace：{detail}\n"
            "解决方式（任选其一）：\n"
            "1. 设置镜像后重试：在启动前执行  set HF_ENDPOINT=https://hf-mirror.com\n"
            "2. 挂着代理运行一次，让模型（约 400 MB）下载完；之后可离线使用\n"
            "3. 本机没有网络时，把已下载好的模型缓存目录拷过来：\n"
            "   %USERPROFILE%\\.cache\\huggingface\\hub\\models--kha-white--manga-ocr-base\n"
            "下载完成前可以先用「原文」框手打日文。"
        )
    return (
        f"manga-ocr 模型加载失败：{detail}\n"
        "可先用「原文」框手打，或执行 --selfcheck-ocr 查看详细报告。"
    )


def _ocr_manga(image: QImage, split_columns: bool = True) -> OCRResult:
    try:
        from PIL import Image  # noqa: F401  (import check for the optional stack)
    except Exception as exc:
        return OCRResult(error=f"缺少 Pillow：{exc}")

    try:
        model = _load_manga_model()
    except Exception as exc:
        return OCRResult(error=_manga_failure_hint(exc), backend="manga-ocr")

    def read(img: QImage) -> str:
        pil_img = Image.open(io.BytesIO(_qimage_to_png_bytes(img))).convert("RGB")
        return (model(pil_img) or "").strip()

    try:
        # A bubble holding several vertical columns loses text when fed to
        # manga-ocr as one image; detect the columns and read right-to-left.
        if split_columns:
            from .textdetect import crop_normalized, detect_vertical_columns

            columns = detect_vertical_columns(image)
            if len(columns) >= 2:
                parts = [read(crop_normalized(image, c)) for c in columns]
                parts = [p for p in parts if p]
                if parts:
                    return OCRResult(
                        text=clean_ocr_text("\n".join(parts)),
                        backend="manga-ocr 分栏",
                    )
        return OCRResult(text=clean_ocr_text(read(image)), backend="manga-ocr")
    except Exception as exc:
        return OCRResult(error=f"manga-ocr 识别失败：{exc}")


def _ocr_windows(image: QImage, language: str = "zh-Hans-CN") -> OCRResult:
    script = resource_path("tools/win_ocr.ps1")
    if not script.exists():
        return OCRResult(error=f"缺少 OCR 辅助脚本：{script}")

    img_path = safe_ocr_temp_png(image)
    out_path = img_path.with_suffix(".json")
    powershell = os.path.join(
        os.environ.get("SystemRoot", r"C:\Windows"),
        "System32", "WindowsPowerShell", "v1.0", "powershell.exe",
    )
    creationflags = 0
    if os.name == "nt":
        creationflags = getattr(subprocess, "CREATE_NO_WINDOW", 0)

    try:
        proc = subprocess.run(
            [
                powershell, "-NoProfile", "-NonInteractive",
                "-ExecutionPolicy", "Bypass", "-File", str(script),
                "-ImagePath", str(img_path),
                "-OutPath", str(out_path),
                "-Language", language,
            ],
            capture_output=True, text=True, timeout=60, creationflags=creationflags,
        )
        if not out_path.exists():
            detail = (proc.stderr or proc.stdout or "").strip()
            return OCRResult(error=f"Windows OCR 未返回结果。{detail[:300]}")
        data = json.loads(out_path.read_text(encoding="utf-8-sig"))
        if not data.get("ok"):
            return OCRResult(error=data.get("error") or "Windows OCR 失败")
        return OCRResult(
            text=clean_ocr_text(data.get("text") or ""),
            backend="windows",
            lines=data.get("lines") or [],
        )
    except subprocess.TimeoutExpired:
        return OCRResult(error="Windows OCR 超时")
    except Exception as exc:
        return OCRResult(error=f"Windows OCR 调用失败：{exc}")
    finally:
        for p in (img_path, out_path):
            try:
                p.unlink(missing_ok=True)
            except Exception:
                pass


_KANA_RE = re.compile(r"[\u3040-\u309f\u30a0-\u30ff]")


def looks_japanese(text: str) -> bool:
    """Japanese text nearly always contains kana; kanji-only output is a warning sign."""
    return bool(_KANA_RE.search(text or ""))


def _ocr_manga_via_worker(image: QImage) -> OCRResult:
    """Run manga-ocr in a separate process (used when torch is not bundled).

    Keeping this optional is what lets the main exe stay ~170 MB: the heavy
    stack lives in whatever Python has manga-ocr installed.
    """
    try:
        from .ocr_worker_client import run_external_ocr
    except Exception as exc:
        # A broken/missing bridge must degrade to Windows OCR or manual input,
        # never reach the UI as an unhandled traceback.
        return OCRResult(error=f"外部 OCR 模块不可用：{exc}")

    tmp = safe_ocr_temp_png(image)
    try:
        return run_external_ocr(tmp)
    finally:
        try:
            tmp.unlink(missing_ok=True)
        except Exception:
            pass


def manga_backend_available() -> bool:
    """True if Japanese OCR is possible, in-process or via a worker."""
    if manga_ocr_available():
        return True
    try:
        from .ocr_worker_client import external_ocr_available
        return external_ocr_available()
    except Exception:
        return False


def run_ocr(image: QImage, backend: str = "auto", language: str = "zh-Hans-CN") -> OCRResult:
    if image is None or image.isNull():
        return OCRResult(error="图片为空")

    if backend == "manual":
        return OCRResult(error="当前设置为手动输入")

    if backend == "manga":
        if manga_ocr_available():
            return _ocr_manga(image)
        if manga_backend_available():
            return _ocr_manga_via_worker(image)
        return OCRResult(
            error="没有可用的日文 OCR。请安装 manga-ocr，"
                  "或在设置里指定已安装 manga-ocr 的 Python。")

    if backend == "windows":
        if not windows_ocr_available():
            return OCRResult(error="Windows OCR 不可用")
        return _ocr_windows(image, language)

    # auto: prefer in-process (fastest), then the external worker, then
    # Windows OCR which covers Chinese/English only.
    if manga_ocr_available():
        result = _ocr_manga(image)
        if result.ok and looks_japanese(result.text):
            return result
        if result.ok and not looks_japanese(result.text) and windows_ocr_available():
            # Kanji-only could still be Japanese, but Chinese/English pages are
            # common enough that a second opinion is worth the extra call.
            alt = _ocr_windows(image, language)
            return alt if alt.ok else result
        if result.ok:
            return result
    elif manga_backend_available():
        result = _ocr_manga_via_worker(image)
        if result.ok:
            return result
    if windows_ocr_available():
        return _ocr_windows(image, language)
    if manga_ocr_available():
        return _ocr_manga(image)
    return OCRResult(error="没有可用的 OCR 后端，请手动输入原文")


# ---------------------------------------------------------------- model download

MANGA_MODEL_REPO = "kha-white/manga-ocr-base"
MANGA_MODEL_SIZE_MB = 400


def model_status() -> dict:
    """Report whether Japanese OCR can run right now.

    Used at startup so the app can offer to download the weights instead of
    failing on the first selection with a confusing error.
    """
    has_lib = manga_ocr_available()
    worker_ready = False
    if not has_lib:
        try:
            from .ocr_worker_client import external_ocr_available
            worker_ready = external_ocr_available()
        except Exception:
            worker_ready = False

    cached = manga_model_cached()
    return {
        "library": has_lib or worker_ready,
        "library_in_process": has_lib,
        "worker": worker_ready,
        "model_cached": cached,
        "ready": (has_lib or worker_ready) and cached,
        "needs_download": (has_lib or worker_ready) and not cached,
    }


def download_model(progress=None, use_mirror: bool = True) -> tuple[bool, str]:
    """Fetch the manga-ocr weights into the HuggingFace cache.

    `progress` receives (done, total, label). Returns (ok, message).
    Runs network I/O, so callers must invoke it from a worker thread.
    """
    try:
        from huggingface_hub import snapshot_download
    except Exception as exc:
        return False, f"缺少 huggingface_hub：{exc}"

    if use_mirror:
        os.environ.setdefault("HF_ENDPOINT", "https://hf-mirror.com")
    os.environ.pop("HF_HUB_OFFLINE", None)
    os.environ.pop("TRANSFORMERS_OFFLINE", None)

    if progress:
        progress(0, 1, "正在连接模型仓库…")

    attempts = []
    try:
        snapshot_download(
            repo_id=MANGA_MODEL_REPO,
            allow_patterns=["*.json", "*.txt", "*.bin", "*.safetensors", "*.model"],
        )
    except Exception as exc:
        attempts.append(str(exc))
        # Retry without the mirror in case the mirror itself is unreachable.
        if use_mirror:
            os.environ.pop("HF_ENDPOINT", None)
            if progress:
                progress(0, 1, "镜像不可用，改连官方源…")
            try:
                snapshot_download(repo_id=MANGA_MODEL_REPO)
            except Exception as exc2:
                attempts.append(str(exc2))
                return False, "下载失败：\n" + "\n".join(attempts[-2:])
        else:
            return False, f"下载失败：{attempts[-1]}"

    if not manga_model_cached():
        return False, "下载结束但没有找到模型文件，请检查网络或磁盘权限。"
    if progress:
        progress(1, 1, "下载完成")
    return True, "模型已就绪"


def endpoint_hint() -> str:
    """Human-readable description of where weights are stored."""
    base = os.environ.get("HF_HOME") or os.path.join(
        os.path.expanduser("~"), ".cache", "huggingface")
    return str(Path(base) / "hub" / f"models--{MANGA_MODEL_REPO.replace('/', '--')}")
