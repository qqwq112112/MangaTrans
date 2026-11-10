# -*- coding: utf-8 -*-
"""Main application window."""

from __future__ import annotations

import time
from pathlib import Path

from PySide6.QtCore import QRectF, QSize, Qt, QTimer
from PySide6.QtGui import QAction, QKeySequence, QPixmap
from PySide6.QtWidgets import (
    QApplication,
    QFileDialog,
    QSpinBox,
    QFrame,
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QProgressDialog,
    QPushButton,
    QSlider,
    QSizePolicy,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from .archive import ArchiveError, load_input_images
from .config import AppConfig
from .constants import APP_TITLE, APP_VERSION, IMAGE_EXTS
from .icons import app_icon
from .document import Document, PageModel
from .history import SnapshotHistory
from . import i18n, notify
from .library_dialog import LibraryDialog
from .project_store import ProjectStore
from .region_dialog import RegionDialog
from .settings_dialog import SettingsDialog
from .viewer import CanvasView


class DropHint(QWidget):
    """Empty state shown before a file is opened."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setAcceptDrops(False)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(40, 40, 40, 40)
        layout.addStretch(1)

        icon = QLabel("漫")
        icon.setAlignment(Qt.AlignCenter)
        icon.setStyleSheet(
            "font-family:'Noto Sans SC','Microsoft YaHei'; font-size:64px;"
            "color:#2dd4bf; font-weight:700;")
        layout.addWidget(icon)

        title = QLabel("拖入 ZIP / CBZ 压缩包，或选择文件夹")
        title.setAlignment(Qt.AlignCenter)
        title.setStyleSheet("font-size:17px; font-weight:600; color:#dbe3ee;")
        layout.addWidget(title)

        hint = QLabel(
            "支持 .zip / .cbz / 图片文件夹。解开后按文件名自然排序：\n"
            "滚轮缩放 · 左键长按拖动框选 · 右击确认翻译 · 上下/左右翻页"
        )
        hint.setAlignment(Qt.AlignCenter)
        hint.setObjectName("Hint")
        layout.addWidget(hint)

        btn_row = QHBoxLayout()
        btn_row.addStretch(1)
        self.btn_zip = QPushButton("打开压缩包 / 图片")
        self.btn_zip.setObjectName("Primary")
        self.btn_zip.setMinimumWidth(170)
        btn_row.addWidget(self.btn_zip)
        self.btn_dir = QPushButton("打开文件夹")
        self.btn_dir.setMinimumWidth(140)
        btn_row.addWidget(self.btn_dir)
        self.btn_library = QPushButton("项目库")
        self.btn_library.setMinimumWidth(140)
        btn_row.addWidget(self.btn_library)
        btn_row.addStretch(1)
        layout.addSpacing(10)
        layout.addLayout(btn_row)

        # Quick resume strip: the three most recent books, one click away.
        self.recent_host = QWidget()
        self.recent_layout = QVBoxLayout(self.recent_host)
        self.recent_layout.setContentsMargins(0, 18, 0, 0)
        self.recent_layout.setSpacing(6)
        self.recent_title = QLabel("最近打开")
        self.recent_title.setAlignment(Qt.AlignCenter)
        self.recent_title.setObjectName("Hint")
        self.recent_layout.addWidget(self.recent_title)
        self._recent_buttons: list[QPushButton] = []
        for _ in range(3):
            btn = QPushButton()
            btn.setObjectName("Ghost")
            btn.setMinimumWidth(360)
            btn.setCursor(Qt.PointingHandCursor)
            btn.clicked.connect(lambda _c=False, b=btn: self._on_recent(b))
            btn.setVisible(False)
            self.recent_layout.addWidget(btn, 0, Qt.AlignHCenter)
            self._recent_buttons.append(btn)
        layout.addWidget(self.recent_host)
        layout.addStretch(2)
        self._recent_projects: list = []
        self.on_recent = None

    def set_recent(self, projects: list) -> None:
        self._recent_projects = projects[:3]
        for i, btn in enumerate(self._recent_buttons):
            if i < len(self._recent_projects):
                project = self._recent_projects[i]
                label = project.title or project.path.name
                btn.setText(
                    f"{label}    ·    第 {project.last_page + 1}/{max(1, project.page_count)} 页"
                    f"    ·    {project.translated_regions} 处翻译")
                btn.setToolTip(f"继续阅读：{project.source}")
                btn.setVisible(True)
            else:
                btn.setVisible(False)
        self.recent_host.setVisible(bool(self._recent_projects))

    def _on_recent(self, btn: QPushButton) -> None:
        try:
            index = self._recent_buttons.index(btn)
        except ValueError:
            return
        if index < len(self._recent_projects) and self.on_recent is not None:
            self.on_recent(self._recent_projects[index].path)


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.config = AppConfig.load()
        self.doc: Document | None = None
        self.store = ProjectStore()
        self.project_id: str | None = None
        self._has_stored_progress = False
        self._edited_since_open = True
        self.setWindowTitle(APP_TITLE)
        self.setWindowIcon(app_icon())
        self.resize(self.config.last_width, self.config.last_height)
        # Wide enough for the header's buttons at their natural size.
        self.setMinimumSize(QSize(1180, 700))
        self.setAcceptDrops(True)

        # Progress autosave: coalesce rapid edits (each region add, page flip)
        # into one write ~1.2 s later instead of hammering the disk.
        self._save_timer = QTimer(self)
        self._save_timer.setSingleShot(True)
        self._save_timer.setInterval(1200)
        self._save_timer.timeout.connect(lambda: self.save_progress(silent=True))

        # Periodic safety net: even if nothing triggers the debounce above (a
        # user reading one page for a long time), progress lands on disk at
        # least every N seconds. Default 10 minutes, configurable.
        self._periodic_save = QTimer(self)
        self._periodic_save.setInterval(max(30, int(self.config.autosave_seconds)) * 1000)
        self._periodic_save.timeout.connect(self._autosave_tick)
        self._last_autosave = ""

        # Two independent histories. Translation edits and view navigation must
        # be undoable separately, so they never share a stack.
        self._restoring = False
        self.tx_history = SnapshotHistory(
            capture=self._capture_ops, restore=self._restore_ops)
        self.view_history = SnapshotHistory(
            capture=self._capture_view, restore=self._restore_view)

        self._build_ui()
        self._build_actions()
        self._restore_reading_mode()

    # ------------------------------------------------------------------ UI

    def _build_ui(self) -> None:
        central = QWidget()
        root = QVBoxLayout(central)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        # header
        header = QFrame()
        header.setObjectName("Panel")
        header.setStyleSheet(
            "QFrame#Panel { background:#121822; border:none;"
            "border-bottom:1px solid #232c39; border-radius:0; }")
        h = QHBoxLayout(header)
        h.setContentsMargins(16, 9, 16, 9)
        h.setSpacing(9)

        brand = QLabel("MangaTrans")
        brand.setStyleSheet(
            "font-family:'Noto Sans SC','Microsoft YaHei'; font-size:16px;"
            "font-weight:700; color:#2dd4bf;")
        h.addWidget(brand)
        self.doc_label = QLabel(i18n.tr("未打开文件"))
        self.doc_label.setObjectName("Hint")
        self.doc_label.setMaximumWidth(280)
        # The document name is the first thing that should give up space when
        # the window narrows; buttons keep their full labels.
        self.doc_label.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Preferred)
        h.addWidget(self.doc_label, 1)
        h.addSpacing(8)

        self.btn_open = QPushButton(i18n.tr("打开"))
        self.btn_open.setToolTip("打开 ZIP / CBZ 压缩包或图片（Ctrl+O）")
        self.btn_open.clicked.connect(self.open_dialog)
        h.addWidget(self.btn_open)

        self.btn_library = QPushButton("项目库")
        self.btn_library.setObjectName("Ghost")
        self.btn_library.setToolTip("查看打开过的漫画，随时断点续译（Ctrl+L）")
        self.btn_library.clicked.connect(self.open_library)
        h.addWidget(self.btn_library)

        self.btn_save = QPushButton(i18n.tr("保存"))
        self.btn_save.setObjectName("Ghost")
        self.btn_save.setToolTip("立即保存当前页码与全部翻译（Ctrl+S，平时会自动保存）")
        self.btn_save.clicked.connect(lambda: self.save_progress(silent=False))
        h.addWidget(self.btn_save)


        # reading mode segmented control
        self.btn_mode_h = QPushButton(i18n.tr("左右翻页"))
        self.btn_mode_v = QPushButton(i18n.tr("上下翻页"))
        for b in (self.btn_mode_h, self.btn_mode_v):
            b.setCheckable(True)
            b.setCursor(Qt.PointingHandCursor)
            b.setMinimumWidth(82)
        self.btn_mode_h.clicked.connect(lambda: self._set_mode("horizontal"))
        self.btn_mode_v.clicked.connect(lambda: self._set_mode("vertical"))
        h.addWidget(self.btn_mode_h)
        h.addWidget(self.btn_mode_v)
        h.addSpacing(8)

        self.btn_undo = QPushButton(i18n.tr("← 上一步"))
        self.btn_undo.setToolTip("翻译：回退到上一处译文状态（Ctrl+Z）")
        self.btn_undo.clicked.connect(self.tx_undo)
        h.addWidget(self.btn_undo)

        self.btn_redo = QPushButton(i18n.tr("下一步 →"))
        self.btn_redo.setToolTip("翻译：前进到下一处译文状态（Ctrl+Y）")
        self.btn_redo.clicked.connect(self.tx_redo)
        h.addWidget(self.btn_redo)

        h.addSpacing(8)

        # View history is a separate pair, so undoing a translation never
        # rewinds the page you were reading.
        self.btn_view_undo = QPushButton(i18n.tr("视图 ↶"))
        self.btn_view_undo.setToolTip("视图：回退翻页/缩放（Alt+←）")
        self.btn_view_undo.clicked.connect(self.view_undo)
        h.addWidget(self.btn_view_undo)

        self.btn_view_redo = QPushButton(i18n.tr("视图 ↷"))
        self.btn_view_redo.setToolTip("视图：前进翻页/缩放（Alt+→）")
        self.btn_view_redo.clicked.connect(self.view_redo)
        h.addWidget(self.btn_view_redo)

        h.addSpacing(8)

        self.btn_export = QPushButton(i18n.tr("导出页"))
        self.btn_export.clicked.connect(self.export_current)
        h.addWidget(self.btn_export)

        self.btn_export_all = QPushButton(i18n.tr("导出夹"))
        self.btn_export_all.clicked.connect(self.export_all)
        h.addWidget(self.btn_export_all)

        self.btn_export_zip = QPushButton(i18n.tr("导出ZIP"))
        self.btn_export_zip.setObjectName("Primary")
        self.btn_export_zip.setToolTip("把整本书导出为单个 zip 压缩包")
        self.btn_export_zip.clicked.connect(self.export_zip)
        h.addWidget(self.btn_export_zip)

        self.btn_settings = QPushButton(i18n.tr("设置"))
        self.btn_settings.clicked.connect(self.open_settings)
        h.addWidget(self.btn_settings)
        root.addWidget(header)

        # canvas + empty state
        self.stack = QStackedWidget()
        self.canvas = CanvasView()
        self.empty = DropHint()
        self.empty.btn_zip.clicked.connect(self.open_dialog)
        self.empty.btn_dir.clicked.connect(self.open_folder_dialog)
        self.empty.btn_library.clicked.connect(self.open_library)
        self.empty.on_recent = lambda path: self.open_path(path, restore=True)
        self.stack.addWidget(self.canvas)
        self.stack.addWidget(self.empty)
        self.stack.setCurrentWidget(self.empty)
        root.addWidget(self.stack, 1)

        # footer: two rows. Everything used to share one row, and at the minimum
        # window width the page slider overlapped the selection buttons.
        footer = QFrame()
        footer.setStyleSheet("background:#121822; border-top:1px solid #232c39;")
        footer_col = QVBoxLayout(footer)
        footer_col.setContentsMargins(14, 4, 14, 4)
        footer_col.setSpacing(2)

        nav_row = QWidget()
        f = QHBoxLayout(nav_row)
        f.setContentsMargins(0, 0, 0, 0)
        f.setSpacing(8)

        tool_row = QWidget()
        g = QHBoxLayout(tool_row)
        g.setContentsMargins(0, 0, 0, 0)
        g.setSpacing(8)

        self.btn_prev = QPushButton(i18n.tr("‹ 上一页"))
        self.btn_prev.setObjectName("Ghost")
        self.btn_prev.clicked.connect(lambda: self._view_action(self.canvas.prev_page))
        f.addWidget(self.btn_prev)

        self.page_label = QLabel("— / —")
        self.page_label.setMinimumWidth(72)
        self.page_label.setAlignment(Qt.AlignCenter)
        f.addWidget(self.page_label)

        self.btn_next = QPushButton(i18n.tr("下一页 ›"))
        self.btn_next.setObjectName("Ghost")
        self.btn_next.clicked.connect(lambda: self._view_action(self.canvas.next_page))
        f.addWidget(self.btn_next)

        # Page navigation: arrows for ±1, a wide slider for scrubbing, and a
        # spin box for jumping to an exact page in long books (where one slider
        # pixel can cover several pages).
        self.page_spin = QSpinBox()
        self.page_spin.setRange(1, 1)
        self.page_spin.setFixedWidth(74)
        self.page_spin.setAlignment(Qt.AlignCenter)
        self.page_spin.setToolTip("输入页码后回车直接跳转")
        self.page_spin.setSuffix(" " + i18n.tr("页"))
        self.page_spin.valueChanged.connect(self._page_spin_changed)
        f.addWidget(self.page_spin)

        self.page_slider = QSlider(Qt.Horizontal)
        self.page_slider.setRange(0, 0)
        self.page_slider.setMinimumWidth(200)
        self.page_slider.setMaximumWidth(420)
        self.page_slider.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self.page_slider.setPageStep(1)
        self.page_slider.setSingleStep(1)
        self.page_slider.setTickPosition(QSlider.NoTicks)
        self.page_slider.setToolTip("拖动快速翻页（← → 微调单页）")
        self.page_slider.valueChanged.connect(self._slider_moved)
        f.addWidget(self.page_slider, 1)

        f.addStretch(1)

        footer_col.addWidget(nav_row)
        footer_col.addWidget(tool_row)

        # Selection controls: a visible cancel is essential - relying on Esc
        # alone fails whenever the canvas does not hold keyboard focus.
        self.sel_label = QLabel("")
        self.sel_label.setObjectName("Badge")
        self.sel_label.setVisible(False)
        g.addWidget(self.sel_label)

        self.btn_sel_undo = QPushButton(i18n.tr("撤销选区"))
        self.btn_sel_undo.setToolTip("移除最后画出的一个选区框")
        self.btn_sel_undo.clicked.connect(self.undo_last_selection)
        g.addWidget(self.btn_sel_undo)

        self.btn_sel_clear = QPushButton(i18n.tr("取消选区"))
        self.btn_sel_clear.setObjectName("Danger")
        self.btn_sel_clear.setToolTip("清空所有未确认的选区框（Esc）")
        self.btn_sel_clear.clicked.connect(self.cancel_selection)
        g.addWidget(self.btn_sel_clear)
        f.addSpacing(10)

        self.hint_label = QLabel(i18n.tr("滚轮缩放 · 左键长按框选 · 右击确认"))
        self.hint_label.setObjectName("Hint")
        f.addWidget(self.hint_label)
        f.addSpacing(12)

        self.btn_zoom_out = QPushButton("−")
        self.btn_zoom_out.setFixedWidth(34)
        self.btn_zoom_out.clicked.connect(lambda: self._view_action(lambda: self.canvas._zoom_by(1 / 1.25)))
        g.addWidget(self.btn_zoom_out)
        self.zoom_label = QLabel("100%")
        self.zoom_label.setMinimumWidth(48)
        self.zoom_label.setAlignment(Qt.AlignCenter)
        g.addWidget(self.zoom_label)
        self.btn_zoom_in = QPushButton("+")
        self.btn_zoom_in.setFixedWidth(34)
        self.btn_zoom_in.clicked.connect(lambda: self._view_action(lambda: self.canvas._zoom_by(1.25)))
        g.addWidget(self.btn_zoom_in)

        self.btn_fit_page = QPushButton(i18n.tr("适应窗口"))
        self.btn_fit_page.setToolTip("整页缩放到窗口内（等比，不裁切不失真）Ctrl+9")
        self.btn_fit_page.clicked.connect(lambda: self._view_action(self.canvas.fit_page))
        g.addWidget(self.btn_fit_page)

        self.btn_fit = QPushButton(i18n.tr("适应宽度"))
        self.btn_fit.setToolTip("宽度铺满窗口，纵向可滚动（长条漫用）Ctrl+0")
        self.btn_fit.clicked.connect(lambda: self._view_action(self.canvas.fit_width))
        g.addWidget(self.btn_fit)
        self.btn_actual = QPushButton(i18n.tr("原始大小"))
        self.btn_actual.clicked.connect(lambda: self._view_action(self.canvas.actual_size))
        g.addWidget(self.btn_actual)

        root.addWidget(footer)
        self.setCentralWidget(central)

        self.statusBar().showMessage("就绪")
        self._ensure_buttons_fit()

        self.canvas.regionsConfirmed.connect(self.on_regions_confirmed)
        self.canvas.appliedOpContext.connect(self.on_applied_op_context)
        self.canvas.pageActivated.connect(self._page_changed)
        self.canvas.zoomChanged.connect(self._zoom_changed)
        self.canvas.statusMessage.connect(self.statusBar().showMessage)
        self.canvas.pendingChanged.connect(self._on_pending_changed)
        self._update_enabled()
        self._refresh_library_button()

    @staticmethod
    def _fit_button(btn: QPushButton) -> int:
        """Make one button wide enough for its current label."""
        from PySide6.QtGui import QFontMetrics

        label = btn.text()
        if not label:
            return 0
        fm = QFontMetrics(btn.font())
        # Text width + horizontal padding (10px each side from the theme)
        # + border, plus a couple of pixels of slack.
        needed = fm.horizontalAdvance(label) + 28
        if btn.minimumWidth() < needed:
            btn.setMinimumWidth(needed)
        btn.setSizePolicy(QSizePolicy.Minimum, QSizePolicy.Fixed)
        return needed

    def _ensure_buttons_fit(self) -> None:
        """Give every button a minimum width that fits its label.

        Without this, a narrow window squeezes buttons below their text width
        and Qt elides the label ("导出本页" -> "导出…"), which looks broken.
        Measuring with the real font keeps it correct across DPI settings.
        """
        for btn in self.findChildren(QPushButton):
            self._fit_button(btn)

    def _build_actions(self) -> None:
        bar = self.menuBar()

        file_menu = bar.addMenu(i18n.tr("文件"))
        act_open = QAction("打开压缩包 / 图片…", self)
        act_open.setShortcut(QKeySequence.Open)
        act_open.triggered.connect(self.open_dialog)
        file_menu.addAction(act_open)

        act_folder = QAction("打开文件夹…", self)
        act_folder.setShortcut("Ctrl+Shift+O")
        act_folder.triggered.connect(self.open_folder_dialog)
        file_menu.addAction(act_folder)
        file_menu.addSeparator()

        act_library = QAction("项目库 / 断点续译…", self)
        act_library.setShortcut("Ctrl+L")
        act_library.triggered.connect(self.open_library)
        file_menu.addAction(act_library)

        act_save = QAction("保存进度", self)
        act_save.setShortcut(QKeySequence.Save)
        act_save.triggered.connect(lambda: self.save_progress(silent=False))
        file_menu.addAction(act_save)
        file_menu.addSeparator()

        act_export = QAction("导出当前页…", self)
        act_export.setShortcut("Ctrl+E")
        act_export.triggered.connect(self.export_current)
        file_menu.addAction(act_export)

        act_export_all = QAction("批量导出全部页面（文件夹）…", self)
        act_export_all.setShortcut("Ctrl+Shift+E")
        act_export_all.triggered.connect(self.export_all)
        file_menu.addAction(act_export_all)

        act_export_zip = QAction("整体导出为 ZIP…", self)
        act_export_zip.setShortcut("Ctrl+Shift+Z")
        act_export_zip.triggered.connect(self.export_zip)
        file_menu.addAction(act_export_zip)
        file_menu.addSeparator()

        act_quit = QAction("退出", self)
        act_quit.setShortcut("Ctrl+Q")
        act_quit.triggered.connect(self.close)
        file_menu.addAction(act_quit)

        view_menu = bar.addMenu(i18n.tr("视图"))
        act_h = QAction("左右翻页", self)
        act_h.triggered.connect(lambda: self._set_mode("horizontal"))
        view_menu.addAction(act_h)
        act_v = QAction("上下翻页", self)
        act_v.triggered.connect(lambda: self._set_mode("vertical"))
        view_menu.addAction(act_v)
        view_menu.addSeparator()

        act_fit_page = QAction("适应窗口（整页）", self)
        act_fit_page.setShortcut("Ctrl+9")
        act_fit_page.triggered.connect(lambda: self._view_action(self.canvas.fit_page))
        view_menu.addAction(act_fit_page)

        act_fit = QAction("适应宽度", self)
        act_fit.setShortcut("Ctrl+0")
        act_fit.triggered.connect(lambda: self._view_action(self.canvas.fit_width))
        view_menu.addAction(act_fit)
        act_actual = QAction("原始大小", self)
        act_actual.setShortcut("Ctrl+1")
        act_actual.triggered.connect(lambda: self._view_action(self.canvas.actual_size))
        view_menu.addAction(act_actual)

        tool_menu = bar.addMenu(i18n.tr("工具"))
        act_sel_clear = QAction("取消选区（清空全部）", self)
        act_sel_clear.setShortcut("Esc")
        act_sel_clear.triggered.connect(self.cancel_selection)
        tool_menu.addAction(act_sel_clear)

        act_sel_undo = QAction("撤销最后一个选区", self)
        act_sel_undo.setShortcut("Shift+Backspace")
        act_sel_undo.triggered.connect(self.undo_last_selection)
        tool_menu.addAction(act_sel_undo)
        tool_menu.addSeparator()

        act_undo = QAction("翻译：上一步", self)
        act_undo.setShortcut("Ctrl+Z")
        act_undo.triggered.connect(self.tx_undo)
        tool_menu.addAction(act_undo)

        act_redo = QAction("翻译：下一步", self)
        act_redo.setShortcut("Ctrl+Y")
        act_redo.triggered.connect(self.tx_redo)
        tool_menu.addAction(act_redo)
        tool_menu.addSeparator()

        act_view_undo = QAction("视图：上一步", self)
        act_view_undo.setShortcut("Alt+Left")
        act_view_undo.triggered.connect(self.view_undo)
        tool_menu.addAction(act_view_undo)

        act_view_redo = QAction("视图：下一步", self)
        act_view_redo.setShortcut("Alt+Right")
        act_view_redo.triggered.connect(self.view_redo)
        tool_menu.addAction(act_view_redo)

        act_settings = QAction("设置…", self)
        act_settings.setShortcut("Ctrl+,")
        act_settings.triggered.connect(self.open_settings)
        tool_menu.addAction(act_settings)

        help_menu = bar.addMenu(i18n.tr("帮助"))
        act_help = QAction("快捷键与用法", self)
        act_help.triggered.connect(self.show_help)
        help_menu.addAction(act_help)
        act_license = QAction("开源声明（无需登录）", self)
        act_license.triggered.connect(self.show_license)
        help_menu.addAction(act_license)

        act_contact = QAction("联系作者", self)
        act_contact.triggered.connect(self.show_contact)
        help_menu.addAction(act_contact)
        help_menu.addSeparator()

        act_about = QAction("关于", self)
        act_about.triggered.connect(self.show_about)
        help_menu.addAction(act_about)

    # ------------------------------------------------------------------ open

    def open_dialog(self) -> None:
        filters = "压缩包 / 图片 (*.zip *.cbz *.png *.jpg *.jpeg *.webp *.bmp);;所有文件 (*.*)"
        path, _ = QFileDialog.getOpenFileName(
            self, "打开漫画压缩包或图片", self.config.last_dir or str(Path.home()), filters)
        if path:
            self.open_path(Path(path))

    def open_folder_dialog(self) -> None:
        path = QFileDialog.getExistingDirectory(
            self, "选择图片文件夹", self.config.last_dir or str(Path.home()))
        if path:
            self.open_path(Path(path))

    def open_path(self, path: Path, restore: bool = True) -> None:
        path = Path(path)
        # Never lose the previous book's progress when switching files.
        if self.doc is not None and self.project_id:
            self.save_progress(silent=True)

        QApplication.setOverrideCursor(Qt.WaitCursor)
        try:
            images, title = load_input_images(path)
            doc = Document([PageModel(p) for p in images], path, title)
        except ArchiveError as exc:
            QApplication.restoreOverrideCursor()
            notify.alert(self, "打开失败", str(exc), kind="error")
            return
        except Exception as exc:
            QApplication.restoreOverrideCursor()
            notify.alert(self, "打开失败", f"读取失败：{exc}", kind="error")
            return
        QApplication.restoreOverrideCursor()

        kind = "folder" if path.is_dir() else (
            "image" if path.suffix.lower() in IMAGE_EXTS else "archive")
        project = self.store.touch(path, title, kind, doc.page_count)
        self.project_id = project.id

        # "从头打开" must not destroy saved work until the user actually edits.
        # Remember whether this book still has stored translations we are
        # deliberately not applying, so autosave can keep them intact.
        self._has_stored_progress = bool(project.ops)
        self._edited_since_open = False

        self.doc = doc
        self.canvas.set_document(doc)
        self.stack.setCurrentWidget(self.canvas)
        self.doc_label.setText(f"{doc.title} · {doc.page_count} 页")
        self.setWindowTitle(f"{doc.title} · {APP_TITLE}")
        # Update the navigation controls WITHOUT emitting. setRange() clamps the
        # current value, and if the previous book was longer that clamp fires
        # valueChanged -> go_to_page(last) -> a visible jump to the final page
        # right after opening. Signals are blocked and the state is set once.
        for widget in (self.page_slider, self.page_spin):
            widget.blockSignals(True)
        self.page_slider.setRange(0, max(0, doc.page_count - 1))
        self.page_slider.setValue(0)
        self.page_spin.setRange(1, max(1, doc.page_count))
        self.page_spin.setValue(1)
        for widget in (self.page_slider, self.page_spin):
            widget.blockSignals(False)
        self.config.last_dir = str(path.parent if path.is_file() else path)
        self._page_changed(0)

        resumed = False
        if restore and project.has_progress:
            resumed = self._restore_progress(project, doc)
        if not resumed:
            self.canvas.go_to_page(0)

        self._update_enabled()
        self._reset_histories()
        self._periodic_save.start()
        if resumed:
            self.statusBar().showMessage(
                f"已恢复《{doc.title}》的进度：第 {project.last_page + 1} 页 · "
                f"{project.translated_regions} 处翻译 · 继续加油")
        else:
            self.statusBar().showMessage(
                f"已载入 {doc.page_count} 页 · 滚轮缩放，左键长按拖动框选文字")
        self._refresh_library_button()
        self.save_progress(silent=True)

    def _restore_progress(self, project, doc: Document) -> bool:
        """Reapply saved regions onto the freshly loaded document."""
        applied = 0
        for index in range(doc.page_count):
            ops = project.ops_for_page(index)
            if not ops:
                continue
            # add_op appends to the undo stack; restored edits are not
            # user actions, so attach them directly instead.
            doc.pages[index].ops.extend(ops)
            doc.pages[index].invalidate()
            applied += len(ops)

        if project.reading_mode in ("horizontal", "vertical") \
                and project.reading_mode != self.canvas.mode:
            self._set_mode(project.reading_mode)
        if project.last_page > 0:
            self.canvas.go_to_page(min(project.last_page, doc.page_count - 1))
        return applied > 0 or project.last_page > 0

    def save_progress(self, silent: bool = True) -> None:
        if self.doc is None or not self.project_id:
            if not silent:
                self.statusBar().showMessage("还没有打开项目")
                self._show_toast("还没有打开项目")
            return

        # "从头打开" leaves the stored translations in place until the user
        # actually edits. Without this guard, merely opening a book without
        # restore and then quitting would silently wipe months of work.
        preserving = (
            getattr(self, "_has_stored_progress", False)
            and not getattr(self, "_edited_since_open", True)
            and not any(page.ops for page in self.doc.pages)
        )
        if preserving:
            project = self.store.get(self.project_id)
            if project is not None:
                project.last_page = max(
                    0, min(self.doc.page_count - 1, self.canvas.current))
                project.reading_mode = self.config.reading_mode
                project.page_count = self.doc.page_count
                if self._current_thumbnail() is not None:
                    name = self.store.save_thumbnail(
                        project.id, self._current_thumbnail())
                    if name:
                        project.thumb = name
                self.store.save()
            if not silent:
                self.statusBar().showMessage(
                    "已记住页码；旧译文仍保留，等你开始修改再覆盖")
                self._show_toast("已保存进度")
            return

        project = self.store.save_progress(
            self.project_id, self.doc, self.canvas.current,
            self.config.reading_mode, self._current_thumbnail())
        if project is None:
            if not silent:
                self.statusBar().showMessage("保存失败：找不到项目记录")
                self._show_toast("保存失败：找不到项目记录")
            return
        if not silent:
            self.statusBar().showMessage(
                f"已保存：第 {project.last_page + 1}/{project.page_count} 页 · "
                f"{project.translated_regions} 处翻译")
            self._show_toast(
                f"已保存 · 第 {project.last_page + 1} 页 · "
                f"{project.translated_regions} 处翻译")

    def _show_toast(self, message: str, msec: int = 1000) -> None:
        """Show a small non-blocking confirmation that fades after `msec`.

        A modal QMessageBox would steal focus and need a click for something as
        routine as saving, so this is a frameless label pinned above the status
        bar that disappears on its own.
        """
        toast = getattr(self, "_toast", None)
        if toast is None:
            toast = QLabel(self)
            toast.setObjectName("Toast")
            toast.setAlignment(Qt.AlignCenter)
            toast.setAttribute(Qt.WA_TransparentForMouseEvents, True)
            toast.setStyleSheet(
                "QLabel#Toast{background:#14312e; color:#9ff3e8;"
                "border:1px solid #1f9c8d; border-radius:10px;"
                "padding:8px 18px; font-size:13px;}")
            self._toast = toast
            self._toast_timer = QTimer(self)
            self._toast_timer.setSingleShot(True)
            self._toast_timer.timeout.connect(self._hide_toast)
        toast.setText(message)
        toast.adjustSize()
        # Centre it near the bottom, just above the status bar.
        bar_h = self.statusBar().height() if self.statusBar() else 24
        x = (self.width() - toast.width()) // 2
        y = self.height() - bar_h - toast.height() - 22
        toast.move(max(8, x), max(8, y))
        toast.show()
        toast.raise_()
        self._toast_timer.start(int(msec))

    def _hide_toast(self) -> None:
        toast = getattr(self, "_toast", None)
        if toast is not None:
            toast.hide()

    def _current_thumbnail(self) -> QPixmap | None:
        """Cover for the library: page 1 of the book."""
        if self.doc is None or not self.doc.page_count:
            return None
        try:
            return self.doc.page_pixmap(0, 420)
        except Exception:
            return None

    def _autosave_tick(self) -> None:
        """Write progress on a timer, independent of user activity."""
        if self.doc is None or not self.project_id:
            return
        self.save_progress(silent=True)
        self._last_autosave = time.strftime("%H:%M:%S")
        self.statusBar().showMessage(
            f"已自动保存进度（{self._last_autosave}，每 "
            f"{max(1, self.config.autosave_seconds // 60)} 分钟一次）", 4000)

    def _queue_autosave(self) -> None:
        if self.doc is not None and self.project_id:
            self._save_timer.start()

    def open_library(self) -> None:
        if self.doc is not None:
            self.save_progress(silent=True)
        dialog = LibraryDialog(self.store, self)
        if dialog.exec() != LibraryDialog.Accepted or dialog.chosen_path is None:
            self._refresh_library_button()
            return
        self.open_path(dialog.chosen_path, restore=dialog.restore_progress)
        self._refresh_library_button()

    def _refresh_library_button(self) -> None:
        count = len(self.store.projects)
        # Keep the label short: the header is tight and a long label gets
        # elided when the window is narrow.
        self.btn_library.setText(f"项目 {count}" if count else "项目库")
        self.btn_library.setToolTip(
            f"项目库（{count} 本）：查看打开过的漫画，随时断点续译（Ctrl+L）")
        # The label changes at runtime, so its minimum width must be refreshed
        # too - otherwise this is the one button that still gets elided.
        self._fit_button(self.btn_library)
        self.empty.set_recent(self.store.all()[:3])

    # ------------------------------------------------------------------ mode / nav

    def _set_mode(self, mode: str) -> None:
        self.config.reading_mode = mode
        self.btn_mode_h.setChecked(mode == "horizontal")
        self.btn_mode_v.setChecked(mode == "vertical")
        if self.doc:
            self.canvas.set_mode(mode)
            self._page_changed(self.canvas.current)

    def _restore_reading_mode(self) -> None:
        self.canvas.mode = self.config.reading_mode
        self._set_mode(self.config.reading_mode)

    def _slider_moved(self, value: int) -> None:
        if self.doc and value != self.canvas.current:
            self._view_mark()
            self.canvas.go_to_page(value)

    def _page_spin_changed(self, value: int) -> None:
        if not self.doc:
            return
        index = value - 1     # the spin box is 1-based for the user
        if index != self.canvas.current:
            self.canvas.go_to_page(index)

    def _page_changed(self, index: int) -> None:
        if not self.doc:
            return
        total = self.doc.page_count
        self.page_label.setText(f"{index + 1} / {total}")
        if self.page_slider.value() != index:
            self.page_slider.blockSignals(True)
            self.page_slider.setValue(index)
            self.page_slider.blockSignals(False)
        if self.page_spin.value() != index + 1:
            self.page_spin.blockSignals(True)
            self.page_spin.setValue(index + 1)
            self.page_spin.blockSignals(False)
        self.btn_prev.setEnabled(index > 0)
        self.btn_next.setEnabled(index < total - 1)
        self._queue_autosave()

    def _zoom_changed(self, percent: int) -> None:
        self.zoom_label.setText(f"{percent}%")

    def _update_enabled(self) -> None:
        has_doc = self.doc is not None
        for w in (self.btn_export, self.btn_export_all, self.btn_export_zip,
                  self.btn_sel_undo, self.btn_sel_clear,
                  self.btn_undo, self.btn_redo,
                  self.btn_view_undo, self.btn_view_redo,
                  self.btn_fit_page, self.btn_fit, self.btn_actual, self.btn_zoom_in,
                  self.btn_zoom_out, self.page_slider, self.page_spin, self.btn_save,
                  self.btn_mode_h, self.btn_mode_v):
            w.setEnabled(has_doc)
        if has_doc:
            self._update_history_ui()
        self.btn_prev.setEnabled(has_doc and self.canvas.current > 0)
        self.btn_next.setEnabled(has_doc and self.canvas.current < (self.doc.page_count - 1 if self.doc else 0))

    # ------------------------------------------------------------------ selection

    def _on_pending_changed(self, count: int) -> None:
        """Show how many unconfirmed selection boxes exist."""
        self.sel_label.setText(f"待确认选区 {count} 处")
        self.sel_label.setVisible(count > 0)
        self.btn_sel_undo.setEnabled(count > 0)
        self.btn_sel_clear.setEnabled(count > 0)
        if count > 0:
            self.sel_label.setToolTip("右击画面确认并进入翻译面板；Esc 或「取消选区」清空")

    def cancel_selection(self) -> None:
        """Discard every unconfirmed selection box."""
        if not self.canvas.pending_count:
            self.statusBar().showMessage("当前没有待确认的选区")
            return
        count = self.canvas.pending_count
        self.canvas.clear_pending()
        self.statusBar().showMessage(f"已取消 {count} 处选区")

    def undo_last_selection(self) -> None:
        """Remove only the most recent selection box."""
        if not self.canvas.undo_last_pending():
            self.statusBar().showMessage("当前没有待确认的选区")

    # ------------------------------------------------------------------ translate

    def on_regions_confirmed(self, drafts: list) -> None:
        if not self.doc or not drafts:
            self.canvas.end_selection_session(False)
            return
        dialog = RegionDialog(self.doc, drafts, self.config, self.canvas, self)
        # "单独覆写" paints straight to the page without closing the panel. The
        # op it created is remembered per dialog so a second overwrite of the
        # same region replaces it instead of stacking a copy underneath.
        overwritten: dict[int, object] = {}
        dialog.overwriteRequested.connect(
            lambda page_index, op, d=dialog, store=overwritten:
            self._apply_overwrite(d, page_index, op, store))
        accepted = dialog.exec() == RegionDialog.Accepted
        self.canvas.end_selection_session(accepted)
        if not accepted:
            return

        ops = dialog.result_ops()
        if not ops:
            return
        # Skip regions already painted by 单独覆写: applying them again would
        # add a duplicate op at the same place.
        pending = [(idx, op) for idx, op in ops if overwritten.get(idx) is not op]
        if not pending:
            self.statusBar().showMessage("所选区域已通过「单独覆写」写入画面")
            self.save_progress(silent=True)
            return
        self._tx_mark()
        touched: set[int] = set()
        for page_index, op in pending:
            self.doc.add_op(page_index, op)
            touched.add(page_index)
        self._edited_since_open = True
        for page_index in sorted(touched):
            self.canvas.refresh_page(page_index)
        self._update_enabled()
        self.statusBar().showMessage(
            f"已应用 {len(pending)} 处翻译，共 {len(touched)} 页")
        self.save_progress(silent=True)

    def _apply_overwrite(self, dialog, page_index: int, op, store: dict) -> None:
        """Paint a single region immediately, without closing the panel.

        The first overwrite of a region appends an op; subsequent ones replace
        that same op, so repeated tweaking never accumulates duplicates.
        """
        if not self.doc:
            return
        # Clone: the dialog keeps editing the same RegionOp instance, so storing
        # the live object would make every overwrite alias the last one and
        # defeat both the replace check and the undo snapshots.
        snapshot = op.cloned()
        self._tx_mark()
        previous = store.get(page_index)
        page = self.doc.pages[page_index]
        if previous is not None and previous in page.ops:
            page.replace_op(page.ops.index(previous), snapshot)
            page.invalidate()
        else:
            self.doc.add_op(page_index, snapshot)
        store[page_index] = snapshot
        self._edited_since_open = True
        self.canvas.refresh_page(page_index)
        self._update_enabled()
        self.save_progress(silent=True)
        self.statusBar().showMessage("已单独覆写选区到画面（面板仍打开）")

    # ------------------------------------------------------------------ history

    def _capture_ops(self):
        return self.doc.ops_snapshot() if self.doc else []

    def _restore_ops(self, snapshot) -> None:
        if not self.doc:
            return
        self._restoring = True
        try:
            self.doc.restore_ops(snapshot)
            for index in range(self.doc.page_count):
                self.canvas.refresh_page(index)
            self._edited_since_open = True
            self._update_enabled()
        finally:
            self._restoring = False

    def _capture_view(self):
        return {
            "page": self.canvas.current,
            "scale": self.canvas.transform().m11(),
            "fit_mode": self.canvas._fit_mode,
        }

    def _restore_view(self, snapshot) -> None:
        if not self.doc:
            return
        self._restoring = True
        try:
            page = int(snapshot.get("page", 0))
            self.canvas._fit_mode = None
            if page != self.canvas.current:
                self.canvas.go_to_page(page)
            scale = float(snapshot.get("scale") or 0)
            if scale > 0:
                self.canvas._set_scale(scale)
            self.canvas._fit_mode = snapshot.get("fit_mode")
            self.canvas.centerOn(self.canvas._items[self.canvas.current])
        finally:
            self._restoring = False
        self._page_changed(self.canvas.current)

    def _tx_mark(self) -> None:
        """Call right before a translation change so it can be undone."""
        if not self._restoring and self.doc:
            self.tx_history.mark()

    def _view_mark(self) -> None:
        """Call right before a view change (page / zoom)."""
        if not self._restoring and self.doc:
            self.view_history.mark()

    def _view_action(self, action) -> None:
        """Run a view-changing action with an undo point recorded."""
        if self.doc and not self._restoring:
            self.view_history.mark()
        action()
        self._update_history_ui()

    def tx_undo(self) -> None:
        if not self.doc:
            return
        if not self.tx_history.undo():
            self.statusBar().showMessage("翻译：没有可回退的步骤")
            return
        self.save_progress(silent=True)
        self.statusBar().showMessage(
            f"翻译：已回到上一步（还可回退 {self.tx_history.undo_depth} 步）")

    def tx_redo(self) -> None:
        if not self.doc:
            return
        if not self.tx_history.redo():
            self.statusBar().showMessage("翻译：没有可前进的步骤")
            return
        self.save_progress(silent=True)
        self.statusBar().showMessage(
            f"翻译：已前进一步（还可前进 {self.tx_history.redo_depth} 步）")

    def view_undo(self) -> None:
        if not self.doc:
            return
        if not self.view_history.undo():
            self.statusBar().showMessage("视图：没有可回退的步骤")
            return
        self.statusBar().showMessage("视图：已回到上一步")

    def view_redo(self) -> None:
        if not self.doc:
            return
        if not self.view_history.redo():
            self.statusBar().showMessage("视图：没有可前进的步骤")
            return
        self.statusBar().showMessage("视图：已前进一步")

    def _update_history_ui(self) -> None:
        """Reflect both stacks in the button states and tooltips."""
        if not self.doc:
            for btn in (self.btn_undo, self.btn_redo,
                        self.btn_view_undo, self.btn_view_redo):
                btn.setEnabled(False)
            return
        tx_u, tx_r = self.tx_history.undo_depth, self.tx_history.redo_depth
        vw_u, vw_r = self.view_history.undo_depth, self.view_history.redo_depth

        self.btn_undo.setEnabled(self.tx_history.can_undo)
        self.btn_redo.setEnabled(self.tx_history.can_redo)
        self.btn_view_undo.setEnabled(self.view_history.can_undo)
        self.btn_view_redo.setEnabled(self.view_history.can_redo)

        self.btn_undo.setToolTip(f"翻译：回退（还可回退 {tx_u} 步）Ctrl+Z")
        self.btn_redo.setToolTip(f"翻译：前进（还可前进 {tx_r} 步）Ctrl+Y")
        self.btn_view_undo.setToolTip(f"视图：回退（还可回退 {vw_u} 步）Alt+←")
        self.btn_view_redo.setToolTip(f"视图：前进（还可前进 {vw_r} 步）Alt+→")

    def _reset_histories(self) -> None:
        self.view_history.reset()
        self.tx_history.reset()

    def undo(self) -> None:
        """Kept for compatibility: the old single-stack undo is now tx_undo."""
        self.tx_undo()

    def on_applied_op_context(self, context) -> None:
        """Right-click on an already translated region: edit it in place."""
        if not self.doc:
            return
        page_index, op_index = context
        page = self.doc.pages[page_index]
        if not (0 <= op_index < len(page.ops)):
            return
        existing = page.ops[op_index]
        from .viewer import RegionDraft

        draft = RegionDraft(
            page_index=page_index,
            rect=QRectF(existing.rect),
            page_size=page.original_size,
        )
        dialog = RegionDialog(self.doc, [draft], self.config, self.canvas, self,
                              preset_ops=[existing])
        if dialog.exec() != RegionDialog.Accepted:
            return
        ops = dialog.result_ops()
        self._tx_mark()
        self._edited_since_open = True
        if not ops:
            page.remove_op_at(op_index)
            self.canvas.refresh_page(page_index)
            self.statusBar().showMessage("已删除该处翻译")
            self.save_progress(silent=True)
            return
        page.replace_op(op_index, ops[0][1])
        self.canvas.refresh_page(page_index)
        self.statusBar().showMessage("已更新该处翻译")
        self.save_progress(silent=True)

    # ------------------------------------------------------------------ export

    def export_current(self) -> None:
        if not self.doc:
            return
        index = self.canvas.current
        stem = self.doc.pages[index].path.stem
        default = str(Path(self.config.last_dir or str(Path.home())) / f"{stem}_zh.png")
        path, selected_filter = QFileDialog.getSaveFileName(
            self, "导出当前页", default, "PNG 图片 (*.png);;JPEG 图片 (*.jpg)")
        if not path:
            return
        target = Path(path)
        if not target.suffix:
            target = target.with_suffix(".jpg" if "JPEG" in selected_filter else ".png")
        try:
            self.doc.export_page(index, target)
        except Exception as exc:
            notify.alert(self, "导出失败", str(exc), kind="error")
            return
        self.statusBar().showMessage(f"已导出：{target}")

    def export_all(self) -> None:
        if not self.doc:
            return
        base = Path(self.config.last_dir or str(Path.home()))
        out_dir = QFileDialog.getExistingDirectory(
            self, "选择导出目录", str(base))
        if not out_dir:
            return
        out = Path(out_dir) / f"{Path(self.doc.title).stem}_汉化"
        progress = QProgressDialog("正在导出…", "取消", 0, self.doc.page_count, self)
        progress.setWindowTitle("批量导出")
        progress.setWindowModality(Qt.WindowModal)
        progress.setMinimumDuration(200)

        def on_page(done: int, total: int, target: Path) -> None:
            progress.setValue(done)
            progress.setLabelText(f"正在导出 {done}/{total}\n{target.name}")
            QApplication.processEvents()

        try:
            written = self.doc.export_all(out, progress=on_page)
        except Exception as exc:
            progress.close()
            notify.alert(self, "导出失败", str(exc), kind="error")
            return
        progress.setValue(self.doc.page_count)
        progress.close()
        self.statusBar().showMessage(f"已导出 {len(written)} 页到 {out}")
        self._show_toast(f"已导出 {len(written)} 页")

    def export_zip(self) -> None:
        """Export the whole book as one .zip archive."""
        if not self.doc:
            return
        base = Path(self.config.last_dir or str(Path.home()))
        default = str(base / f"{Path(self.doc.title).stem}_汉化.zip")
        path, _filter = QFileDialog.getSaveFileName(
            self, "整体导出为 ZIP", default, "ZIP 压缩包 (*.zip)")
        if not path:
            return
        target = Path(path)
        if target.suffix.lower() != ".zip":
            target = target.with_suffix(".zip")

        progress = QProgressDialog("正在打包…", "取消", 0, self.doc.page_count, self)
        progress.setWindowTitle("整体导出")
        progress.setWindowModality(Qt.WindowModal)
        progress.setMinimumDuration(200)

        cancelled = {"flag": False}

        def on_page(done: int, total: int, name: Path) -> None:
            progress.setValue(done)
            progress.setLabelText(f"正在打包 {done}/{total}\n{name.name}")
            QApplication.processEvents()
            if progress.wasCanceled():
                cancelled["flag"] = True
                raise RuntimeError("用户取消")

        try:
            written = self.doc.export_zip(target, progress=on_page)
        except Exception as exc:
            progress.close()
            if cancelled["flag"]:
                self.statusBar().showMessage("已取消整体导出")
                return
            notify.alert(self, "导出失败", str(exc), kind="error")
            return
        progress.setValue(self.doc.page_count)
        progress.close()
        size_mb = written.stat().st_size / (1024 * 1024)
        self.statusBar().showMessage(f"已导出 ZIP：{written}（{size_mb:.1f} MB）")
        self._show_toast(f"已导出 ZIP · {self.doc.page_count} 页 · {size_mb:.1f} MB")

    # ------------------------------------------------------------------ misc

    def open_settings(self) -> None:
        before_lang = i18n.current_language()
        dialog = SettingsDialog(self.config, self)
        if dialog.exec() != SettingsDialog.Accepted:
            return
        dialog.apply_to_config()
        self.config.save()
        i18n.set_language(self.config.language)
        if self.config.language != before_lang:
            # Fully re-localising every widget would mean rebuilding the window,
            # so be explicit instead of leaving a half-translated UI.
            notify.alert(
                self, "语言已切换 / Language changed",
                "界面语言已保存，重启程序后完全生效。\n"
                "The language was saved and will fully apply after a restart.",
            )
        self.statusBar().showMessage("设置已保存")

    def show_help(self) -> None:
        # Two columns keep this list compact enough to fit without scrolling
        # even on a short window.
        col = ("<table width='100%' cellpadding='0' cellspacing='0'><tr>"
               "<td width='50%' valign='top'>{left}</td>"
               "<td width='50%' valign='top'>{right}</td></tr></table>")
        left = (
            "<p class='tight'><b>打开</b><br>"
            "Ctrl+O 压缩包 / 图片<br>Ctrl+Shift+O 文件夹</p>"
            "<p class='tight'><b>翻页</b><br>"
            "← → / PageUp PageDown<br>底部滑块 / 页码框</p>"
            "<p class='tight'><b>缩放</b><br>"
            "滚轮（以鼠标为中心）<br>+ / −<br>"
            "Ctrl+9 适应窗口<br>Ctrl+0 适应宽度<br>Ctrl+1 原始大小</p>"
            "<p class='tight'><b>平移</b><br>"
            "拖动空白处 / 中键拖动<br>Shift+滚轮</p>"
        )
        right = (
            "<p class='tight'><b>框选与翻译</b><br>"
            "左键长按约 0.3 秒后拖动<br>右击确认并打开翻译面板<br>"
            "面板内可批量识别 / 翻译、<br>调整范围、涂鸦、旋转</p>"
            "<p class='tight'><b>撤销</b><br>"
            "Ctrl+Z 翻译上一步<br>Ctrl+Y 翻译下一步<br>"
            "Alt+← / Alt+→ 视图上一步 / 下一步</p>"
            "<p class='tight'><b>导出</b><br>"
            "Ctrl+E 当前页<br>Ctrl+Shift+E 全部页面（文件夹）<br>"
            "Ctrl+Shift+Z 整体导出 ZIP</p>"
            "<p><b>取消</b><br>"
            "Esc 取消框选 / 取消吸管<br>Shift+Backspace 撤销最后一个选区</p>"
        )
        notify.alert(
            self, "快捷键与用法",
            col.format(left=left, right=right),
        )

    def show_about(self) -> None:
        notify.alert(
            self, "关于 MangaTrans",
            f"<p class='tight'><b>MangaTrans {APP_VERSION}</b><br>"
            "本地漫画汉化工作台：解压 → 阅读 → 框选 → OCR/翻译 → 改字 → 导出。</p>"
            "<p class='tight'><b>开源免费</b><br>"
            "本工具是开源软件，<b>无需登录、注册，也不需要任何账号</b>。"
            "除了配置翻译模型（本地运行时或云端 API）之外，"
            "不需要提供任何个人信息。</p>"
            "<p class='tight'><b>作者</b><br>DeepSeek-V4.1-Flash-1017</p>"
            "<p class='tight'><b>GitHub</b><br>"
            "<a href='https://github.com/qqwq112112'>"
            "github.com/qqwq112112</a></p>"
            "<p><b>邮箱</b><br>qqwq112112@Outlook.com</p>",
        )

    # ------------------------------------------------------------------ OCR model

    def check_ocr_model(self) -> None:
        """Offer to fetch the manga-ocr weights on first run.

        The weights are ~400 MB and deliberately not bundled, so a fresh install
        cannot do Japanese OCR until they arrive. Asking up front - with a clear
        size and an explanation - is far better than failing on the first
        selection with a network error.
        """
        from . import ocr

        status = ocr.model_status()
        if not status["library"]:
            # No engine at all: the OCR settings section explains how to add one.
            return
        if status["model_cached"]:
            return

        ok = notify.confirm(
            self, "首次运行：需要下载日文 OCR 模型",
            "日文文字识别需要 manga-ocr 模型（约 "
            f"{ocr.MANGA_MODEL_SIZE_MB} MB），它没有随程序打包，\n"
            "所以需要联网下载一次。\n\n"
            f"下载位置：{ocr.endpoint_hint()}\n\n"
            "· 点「立即下载」会用镜像站加速（约 1–3 分钟）\n"
            "· 点「以后再说」可跳过，届时请在「原文」框手打日文\n"
            "· 之后也可在 设置 → 文字识别 里重新触发下载",
            kind="info", yes_text="立即下载", no_text="以后再说")

        if ok:
            self.start_model_download()

    def start_model_download(self) -> None:
        """Run the download in the background with a progress dialog."""
        from .workers import ModelDownloadTask, start_task

        dlg = QProgressDialog("正在下载 OCR 模型…", "取消", 0, 0, self)
        dlg.setWindowTitle("下载日文 OCR 模型")
        dlg.setWindowModality(Qt.WindowModal)
        dlg.setMinimumDuration(0)
        dlg.setAutoClose(False)
        dlg.setAutoReset(False)
        dlg.setValue(0)

        task = ModelDownloadTask(use_mirror=True)
        self._model_download_task = task

        def on_progress(event: dict) -> None:
            if event.get("kind") != "download":
                return
            label = event.get("label") or ""
            total = int(event.get("total") or 0)
            done = int(event.get("done") or 0)
            if total > 1:
                dlg.setRange(0, total)
                dlg.setValue(done)
            dlg.setLabelText(label or "正在下载…")
            QApplication.processEvents()

        def on_finished(result) -> None:
            ok, message = result
            dlg.close()
            if ok:
                self._show_toast("OCR 模型已就绪", "success", 3000)
                self.statusBar().showMessage("日文 OCR 模型下载完成")
            else:
                notify.alert(self, "下载失败",
                             f"{message}\n\n"
                             "可以稍后重试，或先手动输入日文原文。",
                             kind="error")

        task.signals.progress.connect(on_progress)
        task.signals.finished.connect(on_finished)
        start_task(task)
        dlg.exec()

    def show_contact(self) -> None:
        notify.alert(
            self, "联系作者",
            "<p class='tight'><b>作者</b><br>DeepSeek-V4.1-Flash-1017</p>"
            "<p class='tight'><b>GitHub</b><br>"
            "<a href='https://github.com/qqwq112112'>"
            "github.com/qqwq112112</a></p>"
            "<p class='tight'><b>邮箱</b><br>"
            "<a href='mailto:qqwq112112@Outlook.com'>qqwq112112@Outlook.com</a></p>"
            "<p class='tight'><b>报问题时请附上</b></p>"
            "<ul>"
            "<li>使用的供应商与模型名</li>"
            "<li>错误日志（若有）：<br>"
            "%LOCALAPPDATA%\\MangaTrans\\cache\\last_error.txt</li>"
            "<li>能复现问题的操作步骤</li>"
            "</ul>",
        )

    def show_license(self) -> None:
        notify.alert(
            self, "开源声明",
            "<p class='tight'><b>MangaTrans 是开源工具</b></p>"
            "<ul>"
            "<li><b>无需登录 / 注册</b>：本程序没有账号体系，"
            "不会收集、上传任何个人信息。</li>"
            "<li><b>只配置翻译模型</b>：用本地运行时数据不出本机；"
            "用云端 API 时，仅台词文本会发送到你选择的那家平台，"
            "API Key 只保存在本机配置文件里。</li>"
            "<li><b>无遥测</b>：不含统计、埋点或自动更新上传。</li>"
            "<li><b>可完全离线</b>：配合本地 OCR 与本地模型时全程离线运行。</li>"
            "</ul>",
        )

    # ------------------------------------------------------------------ drag & drop

    def dragEnterEvent(self, event) -> None:
        if event.mimeData().hasUrls() or event.mimeData().hasText():
            event.acceptProposedAction()

    def dropEvent(self, event) -> None:
        urls = event.mimeData().urls()
        if not urls:
            return
        path = Path(urls[0].toLocalFile())
        if not path.exists():
            return
        if path.is_dir() or path.suffix.lower() in IMAGE_EXTS or path.suffix.lower() in (".zip", ".cbz"):
            self.open_path(path)
        else:
            notify.alert(
                self, "不支持的文件",
                "请拖入 .zip / .cbz 压缩包、图片文件夹或单张图片。\n"
                "（.rar / .7z 请先用解压软件转为 zip）")
        event.acceptProposedAction()

    # ------------------------------------------------------------------ close

    def keyPressEvent(self, event) -> None:
        """Window-level shortcuts that must work regardless of widget focus.

        The canvas only receives Esc when it holds focus, which it frequently
        does not (after clicking a toolbar button, for example), so cancelling
        a selection is handled here as a fallback.
        """
        key = event.key()
        if key == Qt.Key_Escape:
            if self.canvas.pending_count:
                self.cancel_selection()
                event.accept()
                return
        elif key == Qt.Key_Backspace and event.modifiers() & Qt.ShiftModifier:
            # Shift+Backspace: drop just the last selection box.
            if self.canvas.pending_count:
                self.undo_last_selection()
                event.accept()
                return
        super().keyPressEvent(event)

    def showEvent(self, event) -> None:
        super().showEvent(event)
        # The QSS font is only applied once the widget is polished, so the
        # first measurement (taken during __init__) can be a few pixels short
        # and leave the last button elided. Re-fit after showing.
        if not getattr(self, "_buttons_refit", False):
            self._buttons_refit = True
            self._ensure_buttons_fit()
            # Checked after the window is visible: the prompt mentions a
            # download, and a modal over a blank window looks broken.
            QTimer.singleShot(600, self.check_ocr_model)

    def closeEvent(self, event) -> None:
        if self.doc is not None and self.project_id:
            self._save_timer.stop()
            self.save_progress(silent=True)
        self.config.last_width = self.width()
        self.config.last_height = self.height()
        self.config.save()
        # Flush the store explicitly: a crash before the next autosave would
        # otherwise lose the page position the user actually stopped on.
        self.store.save()
        super().closeEvent(event)
