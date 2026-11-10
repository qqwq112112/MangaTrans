# -*- coding: utf-8 -*-
"""Persistent project memory: opened books, categories, and translation progress.

Everything the user has ever opened is remembered here, together with the page
they stopped on and every region they translated. This is what makes it
possible to close the app mid-chapter and resume later.

Storage layout (%APPDATA%/MangaTrans/):

    projects.json      book index + progress (UTF-8 BOM, atomic writes)
    projects.json.bak  previous version, kept for one-step recovery
    thumbs/<id>.jpg    small cover thumbnails
"""

from __future__ import annotations

import hashlib
import json
import os
import time
from dataclasses import dataclass, field
from pathlib import Path

from PySide6.QtCore import QRectF, Qt
from PySide6.QtGui import QColor, QPixmap

from .config import app_data_dir
from .textrender import RegionOp

STORE_VERSION = 1
DEFAULT_CATEGORY = "default"
ALL_CATEGORY = "__all__"
THUMB_WIDTH = 320


def _now() -> str:
    return time.strftime("%Y-%m-%d %H:%M:%S")


def source_id(path: Path) -> str:
    """Stable id for a book.

    Uses the resolved path plus the file size, so a re-downloaded file with the
    same name does not silently inherit another book's progress.
    """
    resolved = Path(path).expanduser()
    try:
        resolved = resolved.resolve()
    except OSError:
        resolved = Path(os.path.abspath(str(resolved)))
    key = str(resolved).lower().replace("/", "\\")
    try:
        if resolved.is_file():
            key += f"|{resolved.stat().st_size}"
    except OSError:
        pass
    return hashlib.sha1(key.encode("utf-8")).hexdigest()[:12]


def _color_to_list(color: QColor) -> list[int]:
    c = QColor(color)
    return [c.red(), c.green(), c.blue(), c.alpha()]


def _color_from_list(value) -> QColor:
    try:
        r, g, b, a = (list(value) + [255])[:4]
        return QColor(int(r), int(g), int(b), int(a))
    except Exception:
        return QColor("#FFFFFF")


def op_to_dict(op: RegionOp) -> dict:
    return {
        "rect": [op.rect.x(), op.rect.y(), op.rect.width(), op.rect.height()],
        "fill": _color_to_list(op.fill_color),
        "text": op.text,
        "font": op.font_family,
        "font_ratio": op.font_ratio,
        "bold": bool(op.bold),
        "text_color": _color_to_list(op.text_color),
        "line_spacing": op.line_spacing,
        "padding": op.padding,
        "auto_fit": bool(op.auto_fit),
        "fill_shape": op.fill_shape,
        "fill_soft": op.fill_soft,
        "corner_radius": op.corner_radius,
        "fill_polygon": [[float(x), float(y)] for x, y in (op.fill_polygon or [])],
        "strokes": [
            {
                "points": [[float(px), float(py)] for px, py in s.get("points", [])],
                "color": [int(c) for c in s.get("color", [0, 0, 0, 255])[:4]],
                "width": float(s.get("width", 0.004)),
            }
            for s in (op.strokes or [])
        ],
        "rotation": op.rotation,
        "letter_spacing": op.letter_spacing,
        "column_gap": op.column_gap,
        "vertical": bool(op.vertical),
    }


def op_from_dict(data: dict) -> RegionOp:
    rect = list(data.get("rect") or [0, 0, 0, 0])[:4]
    while len(rect) < 4:
        rect.append(0)
    return RegionOp(
        rect=QRectF(float(rect[0]), float(rect[1]), float(rect[2]), float(rect[3])),
        fill_color=_color_from_list(data.get("fill")),
        text=str(data.get("text") or ""),
        font_family=str(data.get("font") or "Microsoft YaHei"),
        font_ratio=float(data.get("font_ratio") or 0.032),
        bold=bool(data.get("bold")),
        text_color=_color_from_list(data.get("text_color")),
        line_spacing=float(data.get("line_spacing") or 1.12),
        padding=float(data.get("padding") or 0.06),
        auto_fit=bool(data.get("auto_fit", True)),
        fill_shape=str(data.get("fill_shape") or "rect"),
        fill_soft=float(data.get("fill_soft") or 0.0),
        corner_radius=float(data.get("corner_radius") or 0.18),
        fill_polygon=[
            (float(pt[0]), float(pt[1]))
            for pt in (data.get("fill_polygon") or [])
            if isinstance(pt, (list, tuple)) and len(pt) >= 2
        ],
        strokes=[
            {
                "points": [[float(p[0]), float(p[1])] for p in s.get("points", [])
                           if isinstance(p, (list, tuple)) and len(p) >= 2],
                "color": list(s.get("color") or [0, 0, 0, 255]),
                "width": float(s.get("width") or 0.004),
            }
            for s in (data.get("strokes") or [])
            if isinstance(s, dict) and s.get("points")
        ],
        rotation=float(data.get("rotation") or 0.0),
        letter_spacing=float(data.get("letter_spacing") or 0.0),
        column_gap=float(data.get("column_gap") or 0.0),
        vertical=bool(data.get("vertical")),
    )


@dataclass
class Project:
    id: str
    source: str
    title: str = ""
    kind: str = "archive"           # archive | folder | image
    page_count: int = 0
    last_page: int = 0
    reading_mode: str = "horizontal"
    category: str = DEFAULT_CATEGORY
    created: str = field(default_factory=_now)
    updated: str = field(default_factory=_now)
    thumb: str = ""
    ops: dict[str, list[dict]] = field(default_factory=dict)

    # ---------------------------------------------------------------- helpers

    @property
    def path(self) -> Path:
        return Path(self.source)

    @property
    def exists(self) -> bool:
        try:
            return self.path.exists()
        except OSError:
            return False

    @property
    def translated_regions(self) -> int:
        return sum(len(v) for v in self.ops.values())

    @property
    def translated_pages(self) -> int:
        return len([k for k, v in self.ops.items() if v])

    @property
    def progress_ratio(self) -> float:
        if self.page_count <= 0:
            return 0.0
        return min(1.0, self.translated_pages / float(self.page_count))

    @property
    def has_progress(self) -> bool:
        return bool(self.ops) or self.last_page > 0

    def ops_for_page(self, index: int) -> list[RegionOp]:
        raw = self.ops.get(str(index)) or []
        return [op_from_dict(d) for d in raw]

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "source": self.source,
            "title": self.title,
            "kind": self.kind,
            "page_count": self.page_count,
            "last_page": self.last_page,
            "reading_mode": self.reading_mode,
            "category": self.category,
            "created": self.created,
            "updated": self.updated,
            "thumb": self.thumb,
            "ops": self.ops,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "Project":
        ops_raw = data.get("ops") or {}
        ops: dict[str, list[dict]] = {}
        if isinstance(ops_raw, dict):
            for key, value in ops_raw.items():
                if not isinstance(value, list):
                    continue
                clean = [d for d in value if isinstance(d, dict) and d.get("rect")]
                # Drop pages whose entries were all invalid, otherwise the
                # project reports translations that cannot be rendered.
                if clean:
                    ops[str(key)] = clean
        return cls(
            id=str(data.get("id") or ""),
            source=str(data.get("source") or ""),
            title=str(data.get("title") or Path(str(data.get("source") or "")).name),
            kind=str(data.get("kind") or "archive"),
            page_count=int(data.get("page_count") or 0),
            last_page=int(data.get("last_page") or 0),
            reading_mode=str(data.get("reading_mode") or "horizontal"),
            category=str(data.get("category") or DEFAULT_CATEGORY),
            created=str(data.get("created") or _now()),
            updated=str(data.get("updated") or _now()),
            thumb=str(data.get("thumb") or ""),
            ops=ops,
        )


class ProjectStore:
    """JSON-backed book index. All writes are atomic."""

    def __init__(self, path: Path | None = None, thumb_dir: Path | None = None):
        base = app_data_dir()
        self.path = Path(path) if path else base / "projects.json"
        self.thumb_dir = Path(thumb_dir) if thumb_dir else base / "thumbs"
        self.categories: list[dict] = [{"id": DEFAULT_CATEGORY, "name": "未分类"}]
        self.projects: dict[str, Project] = {}
        self.load()

    # ------------------------------------------------------------------ io

    def load(self) -> None:
        for index, candidate in enumerate((self.path,
                                           self.path.with_suffix(".json.bak"))):
            if not candidate.exists():
                continue
            try:
                data = json.loads(candidate.read_text(encoding="utf-8-sig"))
            except Exception:
                continue
            self._ingest(data)
            if index > 0:
                # Recovered from the backup: rewrite the primary so the next
                # start does not have to fall back again.
                self.save()
            return

    def _ingest(self, data: dict) -> None:
        cats = data.get("categories")
        if isinstance(cats, list) and cats:
            clean = []
            for c in cats:
                if isinstance(c, dict) and c.get("id"):
                    clean.append({"id": str(c["id"]), "name": str(c.get("name") or "分类")})
            if clean:
                self.categories = clean
        if not any(c["id"] == DEFAULT_CATEGORY for c in self.categories):
            self.categories.insert(0, {"id": DEFAULT_CATEGORY, "name": "未分类"})

        projects = data.get("projects")
        if isinstance(projects, dict):
            for key, value in projects.items():
                if not isinstance(value, dict):
                    continue
                project = Project.from_dict(value)
                if not project.id:
                    project.id = str(key)
                if project.source:
                    self.projects[project.id] = project
        self._normalize_categories()

    def _normalize_categories(self) -> None:
        known = {c["id"] for c in self.categories}
        for project in self.projects.values():
            if project.category not in known:
                project.category = DEFAULT_CATEGORY

    def save(self) -> bool:
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            payload = {
                "version": STORE_VERSION,
                "categories": self.categories,
                "projects": {p.id: p.to_dict() for p in self.projects.values()},
            }
            text = json.dumps(payload, ensure_ascii=False, indent=2)
            tmp = self.path.with_suffix(".json.tmp")
            tmp.write_text(text, encoding="utf-8-sig")
            if self.path.exists():
                try:
                    self.path.replace(self.path.with_suffix(".json.bak"))
                except OSError:
                    pass
            tmp.replace(self.path)
            return True
        except Exception:
            return False

    # ------------------------------------------------------------------ query

    def get(self, project_id: str) -> Project | None:
        return self.projects.get(project_id)

    def all(self) -> list[Project]:
        return sorted(self.projects.values(), key=lambda p: p.updated, reverse=True)

    def by_category(self, category: str) -> list[Project]:
        if category == ALL_CATEGORY:
            return self.all()
        return [p for p in self.all() if p.category == category]

    def category_name(self, category: str) -> str:
        for c in self.categories:
            if c["id"] == category:
                return c["name"]
        return "未分类"

    def counts(self) -> dict[str, int]:
        result = {ALL_CATEGORY: len(self.projects)}
        for c in self.categories:
            result[c["id"]] = sum(1 for p in self.projects.values() if p.category == c["id"])
        return result

    # ------------------------------------------------------------------ mutate

    def touch(self, path: Path, title: str, kind: str, page_count: int) -> Project:
        """Register a book, creating the entry on first open."""
        pid = source_id(path)
        project = self.projects.get(pid)
        if project is None:
            self.projects[pid] = Project(
                id=pid,
                source=str(Path(path).resolve()),
                title=title or Path(path).name,
                kind=kind,
                page_count=page_count,
            )
        else:
            project.title = title or project.title
            project.kind = kind
            project.page_count = page_count
            project.updated = _now()
            if project.last_page >= page_count > 0:
                project.last_page = max(0, page_count - 1)
        return self.projects[pid]

    def save_progress(self, project_id: str, doc, page_index: int,
                      reading_mode: str, thumb: QPixmap | None = None) -> Project | None:
        project = self.projects.get(project_id)
        if project is None or doc is None:
            return None

        ops: dict[str, list[dict]] = {}
        for index, page in enumerate(doc.pages):
            if page.ops:
                ops[str(index)] = [op_to_dict(op) for op in page.ops]
        project.ops = ops
        project.page_count = doc.page_count
        project.last_page = max(0, min(doc.page_count - 1, int(page_index)))
        project.reading_mode = reading_mode
        project.updated = _now()
        project.title = doc.title or project.title
        if thumb is not None and not thumb.isNull():
            name = self.save_thumbnail(project_id, thumb)
            if name:
                project.thumb = name
        self.save()
        return project

    def set_category(self, project_id: str, category: str) -> bool:
        project = self.projects.get(project_id)
        if project is None:
            return False
        if not any(c["id"] == category for c in self.categories):
            return False
        project.category = category
        project.updated = _now()
        self.save()
        return True

    def add_category(self, name: str) -> str | None:
        name = (name or "").strip()
        if not name:
            return None
        for c in self.categories:
            if c["name"] == name:
                return c["id"]
        cid = hashlib.sha1(f"{name}{time.time()}".encode("utf-8")).hexdigest()[:8]
        self.categories.append({"id": cid, "name": name})
        self.save()
        return cid

    def rename_category(self, category: str, name: str) -> bool:
        name = (name or "").strip()
        if not name or category == DEFAULT_CATEGORY:
            return False
        for c in self.categories:
            if c["id"] == category:
                c["name"] = name
                self.save()
                return True
        return False

    def delete_category(self, category: str) -> bool:
        if category == DEFAULT_CATEGORY:
            return False
        before = len(self.categories)
        self.categories = [c for c in self.categories if c["id"] != category]
        if len(self.categories) == before:
            return False
        for project in self.projects.values():
            if project.category == category:
                project.category = DEFAULT_CATEGORY
        self.save()
        return True

    def clear_progress(self, project_id: str) -> bool:
        """Forget translations and the page position, keep the book listed."""
        project = self.projects.get(project_id)
        if project is None:
            return False
        project.ops = {}
        project.last_page = 0
        project.updated = _now()
        self.save()
        return True

    def remove(self, project_id: str) -> bool:
        project = self.projects.pop(project_id, None)
        if project is None:
            return False
        self._delete_thumbnail(project)
        self.save()
        return True

    # ------------------------------------------------------------------ thumbs

    def thumbnail_path(self, project: Project) -> Path | None:
        if not project.thumb:
            return None
        path = self.thumb_dir / project.thumb
        return path if path.exists() else None

    def save_thumbnail(self, project_id: str, pixmap: QPixmap) -> str:
        try:
            self.thumb_dir.mkdir(parents=True, exist_ok=True)
            if pixmap.width() > THUMB_WIDTH:
                pixmap = pixmap.scaledToWidth(THUMB_WIDTH, Qt.SmoothTransformation)
            name = f"{project_id}.jpg"
            target = self.thumb_dir / name
            if pixmap.save(str(target), "JPEG", 78):
                return name
        except Exception:
            pass
        return ""

    def _delete_thumbnail(self, project: Project) -> None:
        path = self.thumbnail_path(project)
        if path is not None:
            try:
                path.unlink(missing_ok=True)
            except OSError:
                pass
