# -*- coding: utf-8 -*-
"""Project library: every book ever opened, grouped by category.

Closes the loop on "断点记忆": pick a book here and it reopens with the page
you stopped on and all translations already applied.
"""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QSize, Qt
from PySide6.QtGui import QColor, QFont, QFontMetrics, QIcon, QPainter, QPixmap
from PySide6.QtWidgets import (
    QAbstractItemView,
    QDialog,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMenu,
    QProgressBar,
    QPushButton,
    QSplitter,
    QVBoxLayout,
    QWidget,
)

from . import notify
from .project_store import ALL_CATEGORY, DEFAULT_CATEGORY, Project, ProjectStore

CARD_HEIGHT = 108
THUMB_SIZE = QSize(72, 96)


def _placeholder_thumb(size: QSize) -> QPixmap:
    pix = QPixmap(size)
    pix.fill(QColor("#111722"))
    painter = QPainter(pix)
    painter.setRenderHint(QPainter.Antialiasing, True)
    painter.setPen(QColor("#3a4757"))
    font = QFont("Microsoft YaHei")
    font.setPixelSize(11)
    painter.setFont(font)
    painter.drawText(pix.rect(), Qt.AlignCenter, "无\n预\n览")
    painter.end()
    return pix


class ProjectCard(QWidget):
    """One row in the library: cover, title, progress, path."""

    def __init__(self, project: Project, store: ProjectStore, parent=None):
        super().__init__(parent)
        self.setAttribute(Qt.WA_TransparentForMouseEvents, True)

        row = QHBoxLayout(self)
        row.setContentsMargins(8, 6, 10, 6)
        row.setSpacing(12)

        thumb = QLabel()
        thumb.setFixedSize(THUMB_SIZE)
        thumb.setStyleSheet("border-radius:6px; background:#111722;")
        thumb.setAlignment(Qt.AlignCenter)
        thumb_path = store.thumbnail_path(project)
        if thumb_path is not None:
            pix = QPixmap(str(thumb_path))
            if not pix.isNull():
                thumb.setPixmap(pix.scaled(
                    THUMB_SIZE, Qt.KeepAspectRatio, Qt.SmoothTransformation))
        if thumb.pixmap().isNull():
            thumb.setPixmap(_placeholder_thumb(THUMB_SIZE))
        if not project.exists:
            thumb.setToolTip("原文件已不存在")
        row.addWidget(thumb)

        info = QVBoxLayout()
        info.setSpacing(3)
        info.setContentsMargins(0, 2, 0, 2)

        title_row = QHBoxLayout()
        title_row.setSpacing(6)
        title = QLabel()
        title.setStyleSheet("font-size:14px; font-weight:600; color:#e4ebf5;")
        metrics = QFontMetrics(title.font())
        width = 380 if project.exists else 320
        title.setText(metrics.elidedText(project.title or project.path.name,
                                         Qt.ElideMiddle, width))
        title_row.addWidget(title)
        if not project.exists:
            missing = QLabel("文件缺失")
            missing.setStyleSheet(
                "color:#f2707f; font-size:11px; border:1px solid #43303a;"
                "border-radius:6px; padding:0px 6px;")
            title_row.addWidget(missing)
        title_row.addStretch(1)
        info.addLayout(title_row)

        meta_bits = [f"第 {project.last_page + 1} / {max(1, project.page_count)} 页"]
        if project.translated_regions:
            meta_bits.append(f"已译 {project.translated_regions} 处")
            meta_bits.append(f"覆盖 {project.translated_pages} 页")
        else:
            meta_bits.append("尚无翻译")
        meta_bits.append(project.updated[:16])
        meta = QLabel("  ·  ".join(meta_bits))
        meta.setStyleSheet("color:#8b97a8; font-size:12px;")
        info.addWidget(meta)

        bar = QProgressBar()
        bar.setRange(0, 100)
        bar.setValue(int(round(project.progress_ratio * 100)))
        bar.setTextVisible(False)
        bar.setFixedHeight(5)
        bar.setStyleSheet(
            "QProgressBar{border:none;border-radius:2px;background:#1c2431;}"
            "QProgressBar::chunk{background:#2dd4bf;border-radius:2px;}")
        info.addWidget(bar)

        path_label = QLabel()
        path_label.setStyleSheet("color:#5c6675; font-size:11px;")
        path_metrics = QFontMetrics(path_label.font())
        path_label.setText(path_metrics.elidedText(
            str(project.path), Qt.ElideMiddle, 520))
        info.addWidget(path_label)
        info.addStretch(1)

        row.addLayout(info, 1)


class LibraryDialog(QDialog):
    """Browse, categorise and resume remembered projects."""

    def __init__(self, store: ProjectStore, parent=None):
        super().__init__(parent)
        self.setWindowTitle("项目库 · 断点续译")
        self.setModal(True)
        self.resize(1000, 660)
        self.setMinimumSize(860, 560)

        self.store = store
        self.chosen_path: Path | None = None
        self.restore_progress = True
        self._category = ALL_CATEGORY
        self._build_ui()
        self._reload_categories()
        self._reload_projects()

    # ------------------------------------------------------------------ UI

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(16, 14, 16, 12)
        root.setSpacing(10)

        header = QHBoxLayout()
        header.setSpacing(8)
        title = QLabel("项目库")
        title.setObjectName("Title")
        header.addWidget(title)
        self.count_badge = QLabel("")
        self.count_badge.setObjectName("Badge")
        header.addWidget(self.count_badge)
        header.addStretch(1)
        self.search = QLineEdit()
        self.search.setPlaceholderText("搜索标题或路径…")
        self.search.setClearButtonEnabled(True)
        self.search.setFixedWidth(240)
        self.search.textChanged.connect(self._reload_projects)
        header.addWidget(self.search)
        root.addLayout(header)

        splitter = QSplitter(Qt.Horizontal)

        left = QWidget()
        left_layout = QVBoxLayout(left)
        left_layout.setContentsMargins(0, 0, 0, 0)
        left_layout.setSpacing(6)
        self.cat_list = QListWidget()
        self.cat_list.setFixedWidth(200)
        self.cat_list.currentItemChanged.connect(self._category_changed)
        left_layout.addWidget(self.cat_list, 1)

        cat_buttons = QHBoxLayout()
        cat_buttons.setSpacing(5)
        btn_new = QPushButton("新建")
        btn_new.setToolTip("新建分类")
        btn_new.clicked.connect(self._new_category)
        cat_buttons.addWidget(btn_new)
        btn_rename = QPushButton("重命名")
        btn_rename.clicked.connect(self._rename_category)
        cat_buttons.addWidget(btn_rename)
        btn_del = QPushButton("删除")
        btn_del.setObjectName("Danger")
        btn_del.setToolTip("删除分类（里面的项目会回到「未分类」）")
        btn_del.clicked.connect(self._delete_category)
        cat_buttons.addWidget(btn_del)
        left_layout.addLayout(cat_buttons)
        splitter.addWidget(left)

        right = QWidget()
        right_layout = QVBoxLayout(right)
        right_layout.setContentsMargins(10, 0, 0, 0)
        right_layout.setSpacing(6)
        self.project_list = QListWidget()
        self.project_list.setSelectionMode(QAbstractItemView.SingleSelection)
        self.project_list.setVerticalScrollMode(QAbstractItemView.ScrollPerPixel)
        self.project_list.setContextMenuPolicy(Qt.CustomContextMenu)
        self.project_list.customContextMenuRequested.connect(self._project_menu)
        self.project_list.itemDoubleClicked.connect(lambda _i: self._open(True))
        self.project_list.currentItemChanged.connect(self._update_actions)
        right_layout.addWidget(self.project_list, 1)

        self.empty_hint = QLabel(
            "还没有打开过任何漫画。\n用主界面的「打开」载入一本书，它就会出现在这里。")
        self.empty_hint.setObjectName("Hint")
        self.empty_hint.setAlignment(Qt.AlignCenter)
        self.empty_hint.setVisible(False)
        right_layout.addWidget(self.empty_hint)
        splitter.addWidget(right)
        splitter.setSizes([200, 780])
        root.addWidget(splitter, 1)

        footer = QHBoxLayout()
        footer.setSpacing(8)
        self.summary = QLabel("")
        self.summary.setObjectName("Hint")
        footer.addWidget(self.summary, 1)
        self.btn_clear = QPushButton("清除进度")
        self.btn_clear.setObjectName("Danger")
        self.btn_clear.setToolTip("保留项目记录，但删除已翻译内容和页码")
        self.btn_clear.clicked.connect(self._clear_progress)
        footer.addWidget(self.btn_clear)
        self.btn_remove = QPushButton("移出项目库")
        self.btn_remove.setObjectName("Danger")
        self.btn_remove.setToolTip("只从列表移除，不会删除磁盘上的原文件")
        self.btn_remove.clicked.connect(self._remove_project)
        footer.addWidget(self.btn_remove)
        btn_fresh = QPushButton("从头打开")
        btn_fresh.setToolTip("忽略上次进度，重新开始")
        btn_fresh.clicked.connect(lambda: self._open(False))
        footer.addWidget(btn_fresh)
        self.btn_resume = QPushButton("继续阅读")
        self.btn_resume.setObjectName("Primary")
        self.btn_resume.setMinimumWidth(120)
        self.btn_resume.clicked.connect(lambda: self._open(True))
        footer.addWidget(self.btn_resume)
        btn_close = QPushButton("关闭")
        btn_close.clicked.connect(self.reject)
        footer.addWidget(btn_close)
        root.addLayout(footer)

    # ------------------------------------------------------------------ lists

    def _reload_categories(self) -> None:
        counts = self.store.counts()
        previous = self._category
        self.cat_list.blockSignals(True)
        self.cat_list.clear()
        rows = [(ALL_CATEGORY, f"全部项目  ({counts.get(ALL_CATEGORY, 0)})")]
        for cat in self.store.categories:
            rows.append((cat["id"], f"{cat['name']}  ({counts.get(cat['id'], 0)})"))
        for cid, label in rows:
            item = QListWidgetItem(label)
            item.setData(Qt.UserRole, cid)
            self.cat_list.addItem(item)
            if cid == previous:
                self.cat_list.setCurrentItem(item)
        if self.cat_list.currentItem() is None and self.cat_list.count():
            self.cat_list.setCurrentRow(0)
            self._category = self.cat_list.currentItem().data(Qt.UserRole)
        self.cat_list.blockSignals(False)
        self.count_badge.setText(f"{counts.get(ALL_CATEGORY, 0)} 本书")

    def _category_changed(self, current, _previous=None) -> None:
        if current is None:
            return
        self._category = current.data(Qt.UserRole)
        self._reload_projects()

    def _reload_projects(self) -> None:
        needle = self.search.text().strip().lower()
        projects = self.store.by_category(self._category)
        if needle:
            projects = [p for p in projects
                        if needle in (p.title or "").lower()
                        or needle in p.source.lower()]
        self.project_list.clear()
        for project in projects:
            item = QListWidgetItem()
            item.setData(Qt.UserRole, project.id)
            card = ProjectCard(project, self.store)
            item.setSizeHint(QSize(0, CARD_HEIGHT))
            self.project_list.addItem(item)
            self.project_list.setItemWidget(item, card)

        has_any = bool(projects)
        self.project_list.setVisible(has_any)
        self.empty_hint.setVisible(not has_any)
        if not has_any:
            self.empty_hint.setText(
                "没有匹配的项目" if needle else
                "还没有打开过任何漫画。\n用主界面的「打开」载入一本书，它就会出现在这里。")
        if has_any and self.project_list.currentItem() is None:
            self.project_list.setCurrentRow(0)
        self.summary.setText(f"共 {len(projects)} 个项目 · 双击可直接继续")
        self._update_actions()

    def _current_project(self) -> Project | None:
        item = self.project_list.currentItem()
        if item is None:
            return None
        return self.store.get(item.data(Qt.UserRole))

    def _update_actions(self, *_args) -> None:
        project = self._current_project()
        has = project is not None
        self.btn_resume.setEnabled(has)
        self.btn_clear.setEnabled(has and bool(project.ops))
        self.btn_remove.setEnabled(has)

    # ------------------------------------------------------------------ actions

    def _open(self, restore: bool) -> None:
        project = self._current_project()
        if project is None:
            return
        if not project.exists:
            notify.alert(
                self, "文件不存在",
                f"找不到原文件：\n{project.source}\n\n"
                "可能已被移动或删除。可以先用「移出项目库」清掉这条记录。",
                kind="error")
            return
        if not restore and project.has_progress:
            if not notify.confirm(
                    self, "从头打开",
                    "这个项目有保存的进度。从头打开不会删除它，"
                    "但你这次的改动会覆盖旧进度。继续？",
                    yes_text="继续"):
                return
        self.chosen_path = project.path
        self.restore_progress = restore
        self.accept()

    def _project_menu(self, pos) -> None:
        item = self.project_list.itemAt(pos)
        if item is None:
            return
        self.project_list.setCurrentItem(item)
        project = self._current_project()
        if project is None:
            return

        menu = QMenu(self)
        menu.addAction("继续阅读", lambda: self._open(True))
        menu.addAction("从头打开", lambda: self._open(False))
        menu.addSeparator()

        move_menu = menu.addMenu("移动到分类")
        for cat in self.store.categories:
            action = move_menu.addAction(cat["name"])
            action.setCheckable(True)
            action.setChecked(cat["id"] == project.category)
            action.triggered.connect(
                lambda _c=False, cid=cat["id"]: self._move_to(cid))
        menu.addSeparator()
        menu.addAction("打开所在文件夹", lambda: self._reveal(project))
        menu.addAction("清除翻译进度", self._clear_progress)
        menu.addAction("移出项目库", self._remove_project)
        menu.exec(self.project_list.viewport().mapToGlobal(pos))

    def _move_to(self, category: str) -> None:
        project = self._current_project()
        if project is None:
            return
        if self.store.set_category(project.id, category):
            self._reload_categories()
            self._reload_projects()
            self.summary.setText(f"已移动到「{self.store.category_name(category)}」")

    def _reveal(self, project: Project) -> None:
        import os
        import subprocess

        target = project.path
        try:
            if target.is_file():
                subprocess.Popen(["explorer", "/select,", str(target)])
            else:
                os.startfile(str(target.parent if target.is_file() else target))
        except Exception as exc:
            notify.alert(self, "无法打开", str(exc), kind="error")

    def _clear_progress(self) -> None:
        project = self._current_project()
        if project is None:
            return
        if not notify.confirm(
                self, "清除进度",
                f"确定清除《{project.title}》的全部翻译和页码记录？\n"
                "项目仍会保留在列表里，原文件不受影响。",
                yes_text="清除", danger=True):
            return
        self.store.clear_progress(project.id)
        self._reload_projects()
        self.summary.setText("已清除该项目的翻译进度")

    def _remove_project(self) -> None:
        project = self._current_project()
        if project is None:
            return
        if not notify.confirm(
                self, "移出项目库",
                f"把《{project.title}》移出项目库？\n"
                "只删除这条记录和缩略图，磁盘上的原文件不会动。",
                yes_text="移出", danger=True):
            return
        self.store.remove(project.id)
        self._reload_categories()
        self._reload_projects()
        self.summary.setText("已移出项目库")

    # ------------------------------------------------------------------ categories

    def _new_category(self) -> None:
        name, ok = QInputDialog.getText(self, "新建分类", "分类名称：")
        if not ok or not name.strip():
            return
        cid = self.store.add_category(name)
        self._reload_categories()
        if cid:
            for row in range(self.cat_list.count()):
                item = self.cat_list.item(row)
                if item.data(Qt.UserRole) == cid:
                    self.cat_list.setCurrentItem(item)
                    break
        self.summary.setText(f"已创建分类「{name.strip()}」")

    def _rename_category(self) -> None:
        item = self.cat_list.currentItem()
        if item is None:
            return
        cid = item.data(Qt.UserRole)
        if cid == ALL_CATEGORY:
            self.summary.setText("「全部项目」不是分类，无法重命名")
            return
        if cid == DEFAULT_CATEGORY:
            self.summary.setText("「未分类」是内置分类，无法重命名")
            return
        old = self.store.category_name(cid)
        name, ok = QInputDialog.getText(self, "重命名分类", "新名称：", text=old)
        if not ok or not name.strip():
            return
        if self.store.rename_category(cid, name):
            self._reload_categories()
            self.summary.setText(f"「{old}」已改名为「{name.strip()}」")

    def _delete_category(self) -> None:
        item = self.cat_list.currentItem()
        if item is None:
            return
        cid = item.data(Qt.UserRole)
        if cid in (ALL_CATEGORY, DEFAULT_CATEGORY):
            self.summary.setText("内置分类不能删除")
            return
        name = self.store.category_name(cid)
        count = self.store.counts().get(cid, 0)
        if not notify.confirm(
                self, "删除分类",
                f"删除分类「{name}」？\n其中的 {count} 个项目会回到「未分类」，进度不受影响。",
                yes_text="删除", danger=True):
            return
        if self.store.delete_category(cid):
            self._category = ALL_CATEGORY
            self._reload_categories()
            self._reload_projects()
            self.summary.setText(f"已删除分类「{name}」")


def make_icon(pixmap: QPixmap) -> QIcon:
    return QIcon(pixmap)
