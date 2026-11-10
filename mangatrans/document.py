# -*- coding: utf-8 -*-
"""Document / page model with lazy image loading and non-destructive edits."""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QRect, QSize  # noqa: F401  (QRect used by crop_raw)
from PySide6.QtGui import QColor, QFont, QImage, QImageReader, QPainter, QPixmap

from .textrender import RegionOp, paint_ops

# A page shown at this width in scene coordinates; zooming scales the view.
BASE_PAGE_WIDTH = 900.0
PAGE_GAP = 30.0


class PageModel:
    def __init__(self, path: Path):
        self.path = Path(path)
        self.ops: list[RegionOp] = []
        self._pix_cache: dict[int, QPixmap] = {}
        self._orig_size = QSize(1000, 1400)

        reader = QImageReader(str(self.path))
        reader.setAutoTransform(True)
        size = reader.size()
        if size.isValid() and size.width() > 0 and size.height() > 0:
            self._orig_size = size

    @property
    def original_size(self) -> QSize:
        return QSize(self._orig_size)

    @property
    def has_edits(self) -> bool:
        return bool(self.ops)

    @property
    def display_height(self) -> float:
        o = self._orig_size
        if o.width() <= 0:
            return BASE_PAGE_WIDTH * 1.4
        return BASE_PAGE_WIDTH * o.height() / o.width()

    def _read(self, max_width: int | None) -> QImage:
        reader = QImageReader(str(self.path))
        reader.setAutoTransform(True)
        size = reader.size()
        if size.isValid() and max_width:
            scale = min(1.0, max_width / float(size.width()))
            # Also cap extremely tall strips to keep memory sane.
            if size.height() * scale > 7000:
                scale = 7000.0 / size.height()
            if scale < 1.0:
                reader.setScaledSize(QSize(
                    max(1, int(round(size.width() * scale))),
                    max(1, int(round(size.height() * scale))),
                ))
        image = reader.read()
        if image.isNull():
            image = QImage(700, 1000, QImage.Format_ARGB32)
            image.fill(QColor("#f2f2f2"))
            painter = QPainter(image)
            painter.setPen(QColor("#999999"))
            font = QFont("Microsoft YaHei")
            font.setPixelSize(28)
            painter.setFont(font)
            painter.drawText(image.rect(), 0x84, f"无法读取图片\n{self.path.name}")
            painter.end()
        return image

    def pixmap(self, max_width: int = 1600) -> QPixmap:
        key = int(max_width)
        cached = self._pix_cache.get(key)
        if cached is not None:
            return cached
        image = self._read(key).convertToFormat(QImage.Format_ARGB32)
        paint_ops(image, self.ops)
        pixmap = QPixmap.fromImage(image)
        self._pix_cache[key] = pixmap
        while len(self._pix_cache) > 2:
            self._pix_cache.pop(next(iter(self._pix_cache)))
        return pixmap

    def full_image(self) -> QImage:
        image = self._read(None).convertToFormat(QImage.Format_ARGB32)
        paint_ops(image, self.ops)
        return image

    def raw_image(self) -> QImage:
        """Page without any edits - used for OCR."""
        return self._read(None).convertToFormat(QImage.Format_ARGB32)

    def raw_pixmap(self, max_width: int = 1500) -> QPixmap:
        """Page without edits, used as the backdrop in the region editor.

        The editor paints its live preview on top, so a baked-in copy of the
        previous text would otherwise show through.
        """
        return QPixmap.fromImage(self._read(max_width).convertToFormat(QImage.Format_ARGB32))

    def crop_raw(self, rect) -> QImage:
        """Crop a normalized rect out of the untouched page."""
        image = self.raw_image()
        w, h = image.width(), image.height()
        x0 = max(0, min(w - 2, int(rect.x() * w)))
        y0 = max(0, min(h - 2, int(rect.y() * h)))
        x1 = max(x0 + 1, min(w, int((rect.x() + rect.width()) * w)))
        y1 = max(y0 + 1, min(h, int((rect.y() + rect.height()) * h)))
        return image.copy(QRect(x0, y0, x1 - x0, y1 - y0))

    def add_op(self, op: RegionOp) -> None:
        self.ops.append(op)
        self._pix_cache.clear()

    def remove_op(self, op: RegionOp) -> None:
        try:
            self.ops.remove(op)
        except ValueError:
            return
        self._pix_cache.clear()

    def replace_op(self, op_index: int, op: RegionOp) -> None:
        if 0 <= op_index < len(self.ops):
            self.ops[op_index] = op
            self._pix_cache.clear()

    def remove_op_at(self, op_index: int) -> RegionOp | None:
        if 0 <= op_index < len(self.ops):
            op = self.ops.pop(op_index)
            self._pix_cache.clear()
            return op
        return None

    def invalidate(self) -> None:
        self._pix_cache.clear()


class Document:
    def __init__(self, pages: list[PageModel], source_path: Path | None = None,
                 title: str = ""):
        self.pages = pages
        self.source_path = Path(source_path) if source_path else None
        self.title = title or (self.source_path.name if self.source_path else "未命名")
        self._undo: list[tuple[int, RegionOp]] = []

    @property
    def page_count(self) -> int:
        return len(self.pages)

    def page_pixmap(self, index: int, max_width: int = 1600) -> QPixmap:
        return self.pages[index].pixmap(max_width)

    def original_size(self, index: int) -> QSize:
        return self.pages[index].original_size

    def add_op(self, index: int, op: RegionOp, record: bool = True) -> None:
        """Attach an op to a page.

        record=False is used when replaying history or restoring a saved
        project: those paths must not create new history entries.
        """
        self.pages[index].add_op(op)
        if record:
            self._undo.append((index, op))

    def ops_snapshot(self) -> list[list[RegionOp]]:
        """Deep copy of every page's ops, for the translation history."""
        return [[op.cloned() for op in page.ops] for page in self.pages]

    def restore_ops(self, snapshot: list[list[RegionOp]]) -> None:
        """Replace all page contents with a snapshot (history replay)."""
        for index, page in enumerate(self.pages):
            if index < len(snapshot):
                page.ops = [op.cloned() for op in snapshot[index]]
            else:
                page.ops = []
            page.invalidate()

    def undo_last(self) -> int | None:
        if not self._undo:
            return None
        index, op = self._undo.pop()
        self.pages[index].remove_op(op)
        return index

    @property
    def can_undo(self) -> bool:
        return bool(self._undo)

    @property
    def edited_pages(self) -> int:
        return sum(1 for p in self.pages if p.has_edits)

    def export_page(self, index: int, output: Path, quality: int = 95) -> None:
        output = Path(output)
        output.parent.mkdir(parents=True, exist_ok=True)
        image = self.pages[index].full_image()
        suffix = output.suffix.lower()
        if suffix in (".jpg", ".jpeg"):
            ok = image.save(str(output), "JPEG", quality)
        elif suffix in (".webp",):
            ok = image.save(str(output), "WEBP", quality)
        else:
            ok = image.save(str(output), "PNG")
        if not ok:
            raise OSError(f"保存失败：{output}")

    def export_zip(self, output_zip: Path, progress=None,
                   image_format: str = "png") -> Path:
        """Write every page into a single .zip.

        The archive is built in a temp file and moved into place at the end, so
        a cancelled/failed export never leaves a half-written zip behind.
        """
        import zipfile

        output_zip = Path(output_zip)
        output_zip.parent.mkdir(parents=True, exist_ok=True)
        tmp_path = output_zip.with_suffix(output_zip.suffix + ".part")

        total = self.page_count
        used_names: set[str] = set()
        fmt = (image_format or "png").lower()
        ext = ".jpg" if fmt in ("jpg", "jpeg") else ".png"
        qt_format = "JPEG" if ext == ".jpg" else "PNG"

        try:
            with zipfile.ZipFile(tmp_path, "w", zipfile.ZIP_DEFLATED) as zf:
                for i, page in enumerate(self.pages):
                    stem = page.path.stem or f"page_{i + 1}"
                    base = f"{i + 1:04d}_{stem}_zh" if stem[:1].isdigit() else f"{stem}_zh"
                    name = f"{base}{ext}"
                    if name.lower() in used_names:
                        name = f"{i + 1:04d}_{stem}_zh{ext}"
                    used_names.add(name.lower())

                    image = page.full_image()
                    ok = image.save(str(tmp_path.with_name("_page.tmp")), qt_format,
                                    92 if ext == ".jpg" else 100)
                    if not ok:
                        raise OSError(f"第 {i + 1} 页渲染失败")
                    zf.write(tmp_path.with_name("_page.tmp"), arcname=name)
                    if progress:
                        progress(i + 1, total, Path(name))
            tmp_path.replace(output_zip)
        finally:
            for leftover in (tmp_path, tmp_path.with_name("_page.tmp")):
                try:
                    leftover.unlink(missing_ok=True)
                except Exception:
                    pass
        return output_zip

    def export_all(self, output_dir: Path, progress=None) -> list[Path]:
        output_dir = Path(output_dir)
        output_dir.mkdir(parents=True, exist_ok=True)
        written: list[Path] = []
        total = self.page_count
        used_names: set[str] = set()
        for i, page in enumerate(self.pages):
            stem = page.path.stem or f"page_{i + 1}"
            name = f"{stem}_zh.png"
            if name.lower() in used_names:
                name = f"{i + 1:04d}_{stem}_zh.png"
            used_names.add(name.lower())
            target = output_dir / name
            self.export_page(i, target)
            written.append(target)
            if progress:
                progress(i + 1, total, target)
        return written
