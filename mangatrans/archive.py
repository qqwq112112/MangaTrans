# -*- coding: utf-8 -*-
"""ZIP/CBZ extraction and image collection with natural ordering."""

from __future__ import annotations

import hashlib
import re
import shutil
import zipfile
from pathlib import Path, PurePosixPath
from .constants import IMAGE_EXTS
from .config import cache_dir


class ArchiveError(Exception):
    pass


_NUM_RE = re.compile(r"(\d+)")


def natural_key(text: str):
    """Sort key so that page2 < page10."""
    return [int(part) if part.isdigit() else part.lower()
            for part in _NUM_RE.split(text)]


def _decode_zip_name(info: zipfile.ZipInfo) -> str:
    """ZIP spec stores non-UTF8 names as CP437; Chinese/Japanese zips need re-decoding."""
    if info.flag_bits & 0x800:
        return info.filename
    try:
        raw = info.filename.encode("cp437")
    except Exception:
        return info.filename
    for enc in ("utf-8", "gbk", "shift_jis"):
        try:
            return raw.decode(enc)
        except Exception:
            continue
    return info.filename


def _safe_parts(name: str) -> list[str]:
    name = name.replace("\\", "/")
    parts = [p for p in PurePosixPath(name).parts if p not in ("", ".", "/")]
    if not parts:
        return []
    if any(p == ".." or p.endswith(":") for p in parts):
        return []
    return parts


def _file_digest(path: Path) -> str:
    h = hashlib.sha1()
    with path.open("rb") as fh:
        h.update(fh.read(1024 * 1024))
    h.update(str(path.stat().st_size).encode("ascii"))
    return h.hexdigest()[:10]


def extract_archive(path: Path) -> Path:
    """Extract a zip/cbz into a reusable cache folder and return it."""
    path = Path(path)
    if not path.exists():
        raise ArchiveError(f"文件不存在：{path}")
    if path.suffix.lower() not in (".zip", ".cbz"):
        raise ArchiveError("目前只支持 .zip / .cbz 压缩包（rar/7z 请先转换）")

    dest = cache_dir() / f"{path.stem}_{_file_digest(path)}"
    marker = dest / ".mangatrans_ok"
    if marker.exists():
        return dest

    staging = dest.parent / (dest.name + ".extracting")
    shutil.rmtree(staging, ignore_errors=True)
    staging.mkdir(parents=True, exist_ok=True)

    try:
        with zipfile.ZipFile(path) as zf:
            bad = zf.testzip()
            if bad:
                raise ArchiveError(f"压缩包内文件损坏：{bad}")
            for info in zf.infolist():
                if info.is_dir():
                    continue
                name = _decode_zip_name(info)
                parts = _safe_parts(name)
                if not parts:
                    continue
                if "__MACOSX" in parts or parts[-1].startswith("._"):
                    continue
                target = staging.joinpath(*parts)
                target.parent.mkdir(parents=True, exist_ok=True)
                with zf.open(info) as src, target.open("wb") as dst:
                    shutil.copyfileobj(src, dst, 1024 * 1024)
    except zipfile.BadZipFile as exc:
        shutil.rmtree(staging, ignore_errors=True)
        raise ArchiveError(f"不是有效的 ZIP 文件：{exc}") from exc
    except Exception:
        shutil.rmtree(staging, ignore_errors=True)
        raise

    if dest.exists():
        shutil.rmtree(dest, ignore_errors=True)
    staging.rename(dest)
    (dest / ".mangatrans_ok").write_text("ok", encoding="ascii")
    return dest


def collect_images(root: Path) -> list[Path]:
    root = Path(root)
    if root.is_file():
        return [root] if root.suffix.lower() in IMAGE_EXTS else []
    found: list[Path] = []
    for child in root.rglob("*"):
        try:
            if child.is_file() and child.suffix.lower() in IMAGE_EXTS:
                if "__MACOSX" in child.parts:
                    continue
                found.append(child)
        except OSError:
            continue
    found.sort(key=lambda p: natural_key(str(p.relative_to(root)).replace("\\", "/")))
    return found


def load_input_images(path: Path) -> tuple[list[Path], str]:
    """Return (image files, display title). Handles zip/cbz, folder, single image."""
    path = Path(path)
    if path.is_dir():
        images = collect_images(path)
        title = path.name
    elif path.suffix.lower() in (".zip", ".cbz"):
        folder = extract_archive(path)
        images = collect_images(folder)
        title = path.name
    elif path.suffix.lower() in IMAGE_EXTS:
        images = [path]
        title = path.name
    else:
        raise ArchiveError(f"不支持的输入：{path.name}")

    if not images:
        raise ArchiveError("没有在压缩包 / 文件夹里找到图片")
    return images, title
