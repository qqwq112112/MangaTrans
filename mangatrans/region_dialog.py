# -*- coding: utf-8 -*-
"""Region editing dialog: fill colour, font, source text, translation, preview."""

from __future__ import annotations

from PySide6.QtCore import QEvent, QRectF, Qt, QThreadPool, QTimer, Signal
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QButtonGroup,
    QCheckBox,
    QColorDialog,
    QComboBox,
    QDialog,
    QDoubleSpinBox,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QPushButton,
    QScrollArea,
    QSlider,
    QSizePolicy,
    QSpinBox,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from . import ocr, textrender
from .config import AppConfig
from .constants import FILL_PRESETS, TEXT_COLORS
from .document import Document
from .fill import dominant_color
from .fonts import available_presets, available_presets_extra, default_font_family
from .textrender import RegionOp
from .widgets import ColorWell, RegionPreview, SwatchButton
from .workers import OCRTask, TranslateTask, start_task

PREVIEW_PAGE_WIDTH = 1500


def _section(title: str) -> QLabel:
    lab = QLabel(title)
    lab.setObjectName("SubTitle")
    lab.setStyleSheet("color:#8b97a8; font-size:12px; font-weight:600; margin-top:2px;")
    return lab


def _hline() -> QFrame:
    line = QFrame()
    line.setFrameShape(QFrame.HLine)
    line.setStyleSheet("color:#28313f; background:#28313f; max-height:1px;")
    return line


class _RegionState:
    __slots__ = ("draft", "op", "source_text", "ocr_state", "translate_state",
                 "has_translation", "overwritten")

    def __init__(self, draft, op: RegionOp):
        self.draft = draft
        self.op = op
        self.source_text = ""
        self.ocr_state = "idle"        # idle | running | done | failed | skipped
        self.translate_state = "idle"  # idle | running | done | failed
        # Whether op.text holds a translation rather than a copy of the source.
        self.has_translation = False
        # Set once 单独覆写 has painted this region (drives replace-vs-append).
        self.overwritten = False


class RegionDialog(QDialog):
    # Emitted when "单独覆写" writes straight to the page without closing the
    # panel: (page_index, RegionOp). The main window applies it and repaints.
    overwriteRequested = Signal(int, object)

    def __init__(self, document: Document, drafts: list,
                 config: AppConfig, canvas, parent=None,
                 preset_ops: list | None = None):
        super().__init__(parent)
        self.setWindowTitle("选区翻译")
        self.setModal(True)
        self.resize(1360, 940)
        self.setMinimumSize(1200, 820)

        self.doc = document
        self.config = config
        self.canvas = canvas
        self.states: list[_RegionState] = []
        self.current = 0
        self.preset_mode = bool(preset_ops)
        self._chips: list[QPushButton] = []
        self._loading_ui = False
        self._ocr_queue: list[int] = []
        self._ocr_busy = False
        self._quick_active = False
        self._pool = QThreadPool.globalInstance()

        for i, draft in enumerate(drafts):
            width = max(1, draft.page_size.width())
            font_ratio = (config.font_size_px / width) if config.font_size_px else 0.032
            op = RegionOp(
                rect=QRectF(draft.rect),
                fill_color=QColor(config.fill_color),
                text="",
                font_family=config.font_family or default_font_family(),
                font_ratio=font_ratio,
                bold=config.bold,
                text_color=QColor(config.text_color),
                line_spacing=config.line_spacing,
                padding=config.padding,
                auto_fit=config.font_size_px <= 0,
                fill_shape=config.fill_shape,
                fill_soft=float(config.fill_soft) / width,
                rotation=config.rotation,
                letter_spacing=config.letter_spacing,
                column_gap=config.column_gap,
                vertical=config.vertical_text,
            )
            state = _RegionState(draft, op)
            if preset_ops and i < len(preset_ops) and preset_ops[i] is not None:
                state.op = preset_ops[i].cloned()
                state.source_text = state.op.text
                state.ocr_state = "done"
                state.translate_state = "done"
                state.has_translation = True
            self.states.append(state)

        self._build_ui()
        self._fit_buttons()
        self._select(0)
        if not preset_ops:
            self._schedule_auto_ocr()

    # ------------------------------------------------------------------ UI

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(18, 16, 18, 14)
        root.setSpacing(12)

        header = QHBoxLayout()
        title = QLabel("编辑已有翻译" if self.preset_mode else "选区翻译")
        title.setObjectName("Title")
        header.addWidget(title)
        self.badge = QLabel(f"共 {len(self.states)} 处选区")
        self.badge.setObjectName("Badge")
        header.addWidget(self.badge)

        # Which model will actually answer. Filled from the active provider so
        # the user can see "硅基流动 · Qwen2.5-7B" instead of guessing.
        self.model_badge = QLabel("")
        self.model_badge.setObjectName("Badge")
        self.model_badge.setToolTip("当前用于翻译的 AI 模型（可在 设置 → 翻译模型 更改）")
        header.addWidget(self.model_badge)
        header.addStretch(1)
        hint = QLabel("左键长按框选 → 右击确认进入此界面")
        hint.setObjectName("Hint")
        header.addWidget(hint)
        root.addLayout(header)

        body = QHBoxLayout()
        body.setSpacing(14)

        # left: chips + preview
        left = QVBoxLayout()
        left.setSpacing(9)
        self.chip_row = QHBoxLayout()
        self.chip_row.setSpacing(6)
        self.chip_group = QButtonGroup(self)
        self.chip_group.setExclusive(True)
        self.chip_row.addStretch(1)
        chip_host = QWidget()
        chip_host.setLayout(self.chip_row)
        chip_host.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        left.addWidget(chip_host)
        self._rebuild_chips()

        # Overview list: every selection with its page, status and a glimpse of
        # the text. Chips are fine for two regions but useless for twelve, so
        # this is what makes batch work practical.
        self.overview = QListWidget()
        self.overview.setFixedHeight(96)
        self.overview.setToolTip("双击切换到该选区；勾选状态显示是否已有译文")
        self.overview.itemDoubleClicked.connect(
            lambda item: self._select(self.overview.row(item)))
        self.overview.currentRowChanged.connect(self._overview_row_changed)
        left.addWidget(self.overview)

        self.preview = RegionPreview()
        self.preview.setToolTip(
            "拖动框内移动选区，拖动边或角调整大小\n"
            "改完点「应用到画面」生效")
        self.preview.rectChanged.connect(self._rect_dragged)
        self.preview.rectCommitted.connect(self._rect_committed)
        self.preview.strokesChanged.connect(self._on_strokes_changed)
        self.preview.polygonChanged.connect(self._on_polygon_changed)
        left.addWidget(self.preview, 1)

        self.detail = QLabel("")
        self.detail.setObjectName("Hint")
        left.addWidget(self.detail)

        # Numeric rect editor: pairs with the drag handles on the preview so a
        # selection can be adjusted exactly, before or after applying.
        rect_row = QGridLayout()
        rect_row.setHorizontalSpacing(8)
        rect_row.setVerticalSpacing(5)
        rect_row.setContentsMargins(2, 2, 2, 0)
        self._rect_spins: dict[str, QDoubleSpinBox] = {}
        for col, (key, label_text) in enumerate(
                (("x", "左"), ("y", "上"), ("w", "宽"), ("h", "高"))):
            lab = QLabel(label_text)
            lab.setObjectName("Hint")
            spin = QDoubleSpinBox()
            spin.setRange(0.0, 100.0)
            spin.setDecimals(1)
            spin.setSingleStep(0.5)
            spin.setSuffix(" %")
            spin.setMinimumWidth(84)
            spin.valueChanged.connect(self._rect_spin_changed)
            rect_row.addWidget(lab, col // 2 * 2, (col % 2) * 2)
            rect_row.addWidget(spin, col // 2 * 2, (col % 2) * 2 + 1)
            self._rect_spins[key] = spin
        self.rect_hint = QLabel("拖动预览框可移动/缩放")
        self.rect_hint.setObjectName("Hint")
        rect_row.addWidget(self.rect_hint, 0, 4, 2, 1)
        rect_row.setColumnStretch(4, 1)
        left.addLayout(rect_row)
        body.addLayout(left, 1)

        # right: settings
        panel = QFrame()
        panel.setObjectName("Panel")
        panel.setFixedWidth(470)
        panel_layout = QVBoxLayout(panel)
        panel_layout.setContentsMargins(14, 12, 10, 12)
        panel_layout.setSpacing(8)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        scroll.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOn)
        scroll.setFrameShape(QFrame.NoFrame)
        # A wide, always-visible scrollbar on the right of the panel: the
        # settings column is long, and a 10px hairline is hard to grab with a
        # mouse. 18px also gives the wheel a comfortable gutter to work over.
        vbar = scroll.verticalScrollBar()
        vbar.setFixedWidth(18)
        vbar.setStyleSheet(
            "QScrollBar:vertical{background:#10151d;width:18px;margin:0;"
            "border-radius:9px;}"
            "QScrollBar::handle:vertical{background:#3b475a;"
            "border-radius:9px;min-height:40px;margin:2px;}"
            "QScrollBar::handle:vertical:hover{background:#2dd4bf;}"
            "QScrollBar::add-line,QScrollBar::sub-line{height:0;}"
            "QScrollBar::add-page,QScrollBar::sub-page{background:transparent;}")
        host = QWidget()
        host.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Preferred)
        form = QVBoxLayout(host)
        form.setContentsMargins(0, 0, 6, 0)
        form.setSpacing(7)

        # ---- fill colour
        form.addWidget(_section("底色"))
        swatch_row = QHBoxLayout()
        swatch_row.setSpacing(5)
        for label, value in FILL_PRESETS:
            btn = SwatchButton(value, label)
            btn.picked.connect(self._set_fill_color)
            swatch_row.addWidget(btn)
        swatch_row.addStretch(1)
        form.addLayout(swatch_row)

        fill_row = QHBoxLayout()
        fill_row.setSpacing(6)
        self.fill_well = ColorWell(self._op.fill_color)
        fill_row.addWidget(self.fill_well, 1)
        self.btn_dominant = QPushButton("取主色")
        self.btn_dominant.setToolTip("取选区里出现最多的颜色作为底色")
        self.btn_dominant.clicked.connect(self._use_dominant_color)
        fill_row.addWidget(self.btn_dominant)
        self.btn_pick = QPushButton("吸管")
        self.btn_pick.setToolTip("从画面上任意位置吸取颜色")
        self.btn_pick.clicked.connect(self._pick_color_from_canvas)
        fill_row.addWidget(self.btn_pick)
        btn_custom = QPushButton("调色…")
        btn_custom.clicked.connect(self._custom_fill_color)
        fill_row.addWidget(btn_custom)
        form.addLayout(fill_row)

        shape_row = QHBoxLayout()
        shape_row.setSpacing(6)
        self.shape_combo = QComboBox()
        self.shape_combo.addItem("方形", "rect")
        self.shape_combo.addItem("圆角", "rounded")
        self.shape_combo.addItem("椭圆（圆形气泡）", "ellipse")
        self.shape_combo.addItem("自定义描边", "polygon")
        self.shape_combo.addItem("不填充（只写字）", "none")
        self.shape_combo.setToolTip(
            "圆形气泡用方形填充会露出四个白角；\n"
            "「自定义描边」可在预览区沿气泡轮廓点出多边形")
        self.shape_combo.currentIndexChanged.connect(self._shape_changed)
        shape_row.addWidget(self.shape_combo, 1)
        form.addLayout(shape_row)

        shape_row2 = QHBoxLayout()
        shape_row2.setSpacing(6)
        shape_row2.addWidget(QLabel("圆角"))
        self.corner_spin = QDoubleSpinBox()
        self.corner_spin.setRange(0.0, 0.5)
        self.corner_spin.setSingleStep(0.02)
        self.corner_spin.setDecimals(2)
        self.corner_spin.setToolTip("仅「圆角」形状生效，相对选区短边")
        self.corner_spin.valueChanged.connect(self._corner_changed)
        shape_row2.addWidget(self.corner_spin)
        shape_row2.addWidget(QLabel("羽化"))
        self.soft_spin = QSpinBox()
        self.soft_spin.setRange(0, 60)
        self.soft_spin.setSuffix(" px")
        self.soft_spin.setToolTip("让填充边缘柔和过渡，0 为硬边")
        self.soft_spin.valueChanged.connect(self._soft_changed)
        shape_row2.addWidget(self.soft_spin)
        form.addLayout(shape_row2)

        form.addWidget(_hline())

        # ---- text style
        form.addWidget(_section("字体"))
        self.font_combo = QComboBox()
        self._fill_font_combo()
        self.font_combo.currentIndexChanged.connect(self._font_changed)
        form.addWidget(self.font_combo)

        size_grid = QGridLayout()
        size_grid.setHorizontalSpacing(8)
        size_grid.setVerticalSpacing(6)
        size_grid.addWidget(QLabel("字号"), 0, 0)
        self.size_spin = QSpinBox()
        self.size_spin.setRange(6, 400)
        self.size_spin.setSuffix(" px")
        self.size_spin.setToolTip(
            "按原图像素计算。直接改这个数会自动取消「自动适配」，"
            "改回勾选即可重新自适应。")
        self.size_spin.valueChanged.connect(self._size_changed)
        size_grid.addWidget(self.size_spin, 0, 1)
        self.auto_fit = QCheckBox("自动适配选区")
        self.auto_fit.setChecked(True)
        self.auto_fit.toggled.connect(self._auto_fit_changed)
        size_grid.addWidget(self.auto_fit, 0, 2)
        size_grid.setColumnStretch(1, 1)
        form.addLayout(size_grid)

        style_row = QGridLayout()
        style_row.setHorizontalSpacing(8)
        style_row.setVerticalSpacing(6)
        style_row.addWidget(QLabel("行距"), 0, 0)
        self.spacing_spin = QDoubleSpinBox()
        self.spacing_spin.setRange(0.85, 2.5)
        self.spacing_spin.setSingleStep(0.05)
        self.spacing_spin.setDecimals(2)
        self.spacing_spin.valueChanged.connect(self._spacing_changed)
        style_row.addWidget(self.spacing_spin, 0, 1)
        style_row.addWidget(QLabel("边距"), 0, 2)
        self.padding_spin = QDoubleSpinBox()
        self.padding_spin.setRange(0.0, 0.30)
        self.padding_spin.setSingleStep(0.01)
        self.padding_spin.setDecimals(2)
        self.padding_spin.valueChanged.connect(self._padding_changed)
        style_row.addWidget(self.padding_spin, 0, 3)
        self.bold_check = QCheckBox("加粗")
        self.bold_check.toggled.connect(self._bold_changed)
        style_row.addWidget(self.bold_check, 0, 4)
        style_row.setColumnStretch(1, 1)
        style_row.setColumnStretch(3, 1)
        form.addLayout(style_row)

        # --- typography: letter spacing / column gap / vertical layout -----
        type_row = QGridLayout()
        type_row.setHorizontalSpacing(8)
        type_row.setVerticalSpacing(6)
        type_row.addWidget(QLabel("字间距"), 0, 0)
        self.letter_spin = QDoubleSpinBox()
        self.letter_spin.setRange(-0.10, 0.60)
        self.letter_spin.setSingleStep(0.02)
        self.letter_spin.setDecimals(2)
        self.letter_spin.setToolTip("相对字号的比例：0.10 = 字号的 10%")
        self.letter_spin.valueChanged.connect(self._letter_changed)
        type_row.addWidget(self.letter_spin, 0, 1)

        type_row.addWidget(QLabel("列间距"), 0, 2)
        self.colgap_spin = QDoubleSpinBox()
        self.colgap_spin.setRange(0.0, 1.5)
        self.colgap_spin.setSingleStep(0.05)
        self.colgap_spin.setDecimals(2)
        self.colgap_spin.setToolTip("竖排时列与列的间隔，相对字号")
        self.colgap_spin.valueChanged.connect(self._colgap_changed)
        type_row.addWidget(self.colgap_spin, 0, 3)

        # Explicit two-state switch instead of a checkbox: the current direction
        # is the thing users care about, so show both options and highlight the
        # active one.
        layout_box = QHBoxLayout()
        layout_box.setSpacing(5)
        self.btn_horizontal = QPushButton("横排 ←")
        self.btn_horizontal.setCheckable(True)
        self.btn_horizontal.setToolTip("从左到右、由上到下（默认）")
        self.btn_horizontal.setMinimumWidth(88)
        self.btn_vertical = QPushButton("竖排 ↓")
        self.btn_vertical.setCheckable(True)
        self.btn_vertical.setToolTip("縦書き：字符自上而下、列从右往左（日文漫画常用）")
        self.btn_vertical.setMinimumWidth(78)
        self.layout_group = QButtonGroup(self)
        self.layout_group.setExclusive(True)
        self.layout_group.addButton(self.btn_horizontal, 0)
        self.layout_group.addButton(self.btn_vertical, 1)
        self.btn_horizontal.clicked.connect(lambda: self._set_layout_direction(False))
        self.btn_vertical.clicked.connect(lambda: self._set_layout_direction(True))
        layout_box.addWidget(self.btn_horizontal)
        layout_box.addWidget(self.btn_vertical)
        layout_box.addStretch(1)
        # Put the direction switch on its own row so nothing gets clipped when
        # the panel is narrower than the ideal width.
        type_row.addLayout(layout_box, 1, 0, 1, 5)
        type_row.setColumnStretch(1, 1)
        type_row.setColumnStretch(3, 1)
        form.addLayout(type_row)

        # --- rotation: rotates the fill, strokes and text as one unit --------
        rot_row = QHBoxLayout()
        rot_row.setSpacing(6)
        rot_row.addWidget(QLabel("旋转"))
        self.rotation_spin = QSpinBox()
        self.rotation_spin.setRange(-180, 180)
        self.rotation_spin.setSingleStep(5)
        self.rotation_spin.setSuffix(" °")
        self.rotation_spin.setFixedWidth(78)
        self.rotation_spin.setToolTip(
            "选区内容（底色/涂鸦/文字）一起绕选区中心旋转；可超出选区边界")
        self.rotation_spin.valueChanged.connect(self._rotation_changed)
        rot_row.addWidget(self.rotation_spin)
        self.rotation_slider = QSlider(Qt.Horizontal)
        self.rotation_slider.setRange(-180, 180)
        self.rotation_slider.setFixedWidth(120)
        self.rotation_slider.setToolTip("拖动快速旋转")
        self.rotation_slider.valueChanged.connect(self.rotation_spin.setValue)
        self.rotation_spin.valueChanged.connect(
            lambda v: self.rotation_slider.setValue(v)
            if self.rotation_slider.value() != v else None)
        rot_row.addWidget(self.rotation_slider)
        btn_rot_reset = QPushButton("正")
        btn_rot_reset.setFixedWidth(34)
        btn_rot_reset.setToolTip("恢复水平（0°）")
        btn_rot_reset.clicked.connect(lambda: self.rotation_spin.setValue(0))
        rot_row.addWidget(btn_rot_reset)
        rot_row.addStretch(1)
        form.addLayout(rot_row)

        # Live read-out so the effect of resizing the box is visible.
        self.metrics_label = QLabel("")
        self.metrics_label.setObjectName("Hint")
        self.metrics_label.setWordWrap(True)
        form.addWidget(self.metrics_label)

        form.addWidget(_section("文字颜色"))
        text_color_row = QHBoxLayout()
        text_color_row.setSpacing(5)
        for label, value in TEXT_COLORS:
            btn = SwatchButton(value, label)
            btn.picked.connect(self._set_text_color)
            text_color_row.addWidget(btn)
        text_color_row.addStretch(1)
        self.text_well = ColorWell(self._op.text_color)
        text_color_row.addWidget(self.text_well)
        btn_text_custom = QPushButton("调色…")
        btn_text_custom.clicked.connect(self._custom_text_color)
        text_color_row.addWidget(btn_text_custom)
        form.addLayout(text_color_row)

        form.addWidget(_hline())

        # ---- freehand: redraw hidden lines / cover leftover text -----------
        form.addWidget(_section("涂鸦（补画线条 / 盖住残留原文）"))
        brush_row = QHBoxLayout()
        brush_row.setSpacing(6)
        self.btn_brush = QPushButton("画笔")
        self.btn_brush.setCheckable(True)
        self.btn_brush.setToolTip(
            "开启后在预览区按住左键涂抹：\n"
            "· 用白色（或底色）涂掉没盖干净的原文\n"
            "· 用线条色补画被遮住的边框/网点")
        self.btn_brush.toggled.connect(self._toggle_brush)
        brush_row.addWidget(self.btn_brush)

        self.brush_well = ColorWell("#FFFFFF")
        brush_row.addWidget(self.brush_well, 1)
        btn_brush_color = QPushButton("颜色…")
        btn_brush_color.clicked.connect(self._pick_brush_color)
        brush_row.addWidget(btn_brush_color)

        brush_row.addWidget(QLabel("粗细"))
        self.brush_spin = QDoubleSpinBox()
        self.brush_spin.setRange(1.0, 80.0)
        self.brush_spin.setSingleStep(1.0)
        self.brush_spin.setDecimals(0)
        self.brush_spin.setSuffix(" px")
        self.brush_spin.setValue(6)
        self.brush_spin.setToolTip("按原图像素计算")
        self.brush_spin.valueChanged.connect(self._brush_width_changed)
        brush_row.addWidget(self.brush_spin)
        form.addLayout(brush_row)

        brush_actions = QHBoxLayout()
        brush_actions.setSpacing(6)
        self.btn_brush_clear = QPushButton("清空涂鸦")
        self.btn_brush_clear.clicked.connect(self._clear_strokes)
        brush_actions.addWidget(self.btn_brush_clear)
        self.btn_polygon_clear = QPushButton("清除自定义描边")
        self.btn_polygon_clear.clicked.connect(self._clear_polygon)
        brush_actions.addWidget(self.btn_polygon_clear)
        brush_actions.addStretch(1)
        form.addLayout(brush_actions)

        form.addWidget(_hline())

        # ---- content
        form.addWidget(_section("原文（OCR / 手动输入）"))
        self.source_edit = QTextEdit()
        self.source_edit.setFixedHeight(66)
        self.source_edit.setPlaceholderText("在此粘贴或输入日文原文，也可以点「识别」自动 OCR")
        self.source_edit.textChanged.connect(self._source_changed)
        form.addWidget(self.source_edit)

        src_btns = QHBoxLayout()
        src_btns.setSpacing(6)
        self.btn_ocr = QPushButton("识别本选区")
        self.btn_ocr.clicked.connect(self._ocr_current)
        src_btns.addWidget(self.btn_ocr)
        self.btn_ocr_all = QPushButton("全部识别")
        self.btn_ocr_all.clicked.connect(self._ocr_all)
        src_btns.addWidget(self.btn_ocr_all)
        src_btns.addStretch(1)
        form.addLayout(src_btns)

        self.ocr_hint = QLabel(f"OCR：{ocr.describe_backends()}")
        self.ocr_hint.setObjectName("Hint")
        self.ocr_hint.setWordWrap(True)
        form.addWidget(self.ocr_hint)

        form.addWidget(_section("译文"))
        self.translated_edit = QTextEdit()
        self.translated_edit.setFixedHeight(80)
        self.translated_edit.setPlaceholderText("译文会显示在画面上；也可直接手改")
        self.translated_edit.textChanged.connect(self._translated_changed)
        form.addWidget(self.translated_edit)

        self.sync_style = QCheckBox("样式修改同步到全部选区")
        self.sync_style.setChecked(len(self.states) > 1)
        if len(self.states) > 1:
            form.addWidget(self.sync_style)
        form.addStretch(1)

        scroll.setWidget(host)

        self._settings_scroll = scroll
        # Wheel over a QLabel/QCheckBox does nothing by default; route it to the
        # scroll area so the whole settings column responds to the wheel.
        for child in host.findChildren(QWidget):
            if isinstance(child, (QComboBox, QSpinBox, QDoubleSpinBox,
                                  QTextEdit, QSlider, QListWidget)):
                continue          # these use the wheel themselves
            child.installEventFilter(self)

        panel_layout.addWidget(scroll, 1)

        # Pinned action area: always visible regardless of scroll position.
        pin = QFrame()
        pin.setStyleSheet("QFrame { border:none; background:transparent; }")
        pin_layout = QVBoxLayout(pin)
        pin_layout.setContentsMargins(0, 6, 4, 0)
        pin_layout.setSpacing(6)

        tr_row = QHBoxLayout()
        tr_row.setSpacing(6)
        self.btn_translate = QPushButton("翻译（…）")
        self.btn_translate.setObjectName("Primary")
        self.btn_translate.setMinimumHeight(34)
        self.btn_translate.clicked.connect(self._translate_current)
        tr_row.addWidget(self.btn_translate, 1)
        self.btn_translate_all = QPushButton("全部翻译")
        self.btn_translate_all.setMinimumHeight(34)
        self.btn_translate_all.setMinimumWidth(88)
        self.btn_translate_all.clicked.connect(self._translate_all)
        tr_row.addWidget(self.btn_translate_all)
        pin_layout.addLayout(tr_row)

        # One-click path: OCR -> translate -> auto fill -> write to the page.
        # This is the "extract, translate, overwrite with background" flow in a
        # single action, for when the user does not want to touch the controls.
        self.btn_quick = QPushButton("一键直通：识别 → 翻译 → 覆写")
        self.btn_quick.setMinimumHeight(32)
        self.btn_quick.setToolTip(
            "自动完成：识别原文 → 翻译为中文 → 取气泡主色作底色 → 直接写到画面")
        self.btn_quick.clicked.connect(self._quick_apply)
        pin_layout.addWidget(self.btn_quick)

        # Standalone overwrite: only paints what is already in the 译文 box.
        # No OCR, no model call, and the panel stays open so the user can keep
        # tweaking the text or the box and re-apply while looking at the page.
        self.btn_overwrite = QPushButton("单独覆写（不改面板，只写文字）")
        self.btn_overwrite.setMinimumHeight(30)
        self.btn_overwrite.setToolTip(
            "用「译文」框里现有的文字 + 当前底色/字体直接写到画面，不重新识别也不翻译；"
            "面板保持打开，可反复微调后再次覆写")
        self.btn_overwrite.clicked.connect(self._overwrite_only)
        pin_layout.addWidget(self.btn_overwrite)

        self.status = QLabel("")
        self.status.setObjectName("Hint")
        self.status.setWordWrap(True)
        self.status.setMinimumHeight(18)
        pin_layout.addWidget(self.status)
        panel_layout.addWidget(pin)

        body.addWidget(panel)
        root.addLayout(body, 1)

        # footer
        footer = QHBoxLayout()
        self.summary = QLabel("")
        self.summary.setObjectName("Hint")
        footer.addWidget(self.summary, 1)
        if self.preset_mode:
            btn_delete = QPushButton("删除此区域")
            btn_delete.setObjectName("Danger")
            btn_delete.clicked.connect(self._delete_current)
            footer.addWidget(btn_delete)
        btn_cancel = QPushButton("取消")
        btn_cancel.clicked.connect(self.reject)
        footer.addWidget(btn_cancel)
        btn_apply = QPushButton("应用到画面")
        btn_apply.setObjectName("Primary")
        btn_apply.setMinimumWidth(128)
        btn_apply.clicked.connect(self.accept)
        footer.addWidget(btn_apply)
        root.addLayout(footer)

    def _fit_buttons(self) -> None:
        """Widen every button to fit its label.

        The panel is a fixed-width column, so a label that is 4px too long gets
        elided ("清空涂鸦" -> "清空…"). Measuring against the real font and
        setting a minimum width keeps every label intact.
        """
        from PySide6.QtGui import QFontMetrics
        from PySide6.QtWidgets import QPushButton

        for btn in self.findChildren(QPushButton):
            label = btn.text()
            if not label:
                continue
            fm = QFontMetrics(btn.font())
            needed = fm.horizontalAdvance(label) + 26
            if btn.minimumWidth() < needed:
                btn.setMinimumWidth(needed)

    def eventFilter(self, obj, event) -> bool:
        """Scroll the settings column when the wheel turns over inert widgets."""
        if event.type() == QEvent.Wheel:
            scroll = getattr(self, "_settings_scroll", None)
            if scroll is not None:
                bar = scroll.verticalScrollBar()
                if bar.maximum() > 0:
                    delta = event.angleDelta().y()
                    bar.setValue(bar.value() - delta // 2)
                    return True
        return super().eventFilter(obj, event)

    def _fill_font_combo(self) -> None:
        from PySide6.QtGui import QFontDatabase

        used: set[str] = set()
        for family, label in available_presets():
            self.font_combo.addItem(f"{label}  ·  {family}", family)
            used.add(family)

        extra = [p for p in available_presets_extra() if p[0] not in used]
        if extra:
            self.font_combo.insertSeparator(self.font_combo.count())
            for family, label in extra:
                self.font_combo.addItem(f"{label}  ·  {family}", family)
                used.add(family)

        self.font_combo.insertSeparator(self.font_combo.count())
        for family in sorted(QFontDatabase.families()):
            if family in used:
                continue
            self.font_combo.addItem(family, family)

    def _rebuild_chips(self) -> None:
        for btn in self._chips:
            self.chip_group.removeButton(btn)
            btn.deleteLater()
        self._chips.clear()
        for i, st in enumerate(self.states):
            btn = QPushButton(f"选区 {i + 1}")
            btn.setMinimumWidth(78)
            btn.setCheckable(True)
            btn.setCursor(Qt.PointingHandCursor)
            btn.setProperty("page", st.draft.page_index)
            btn.clicked.connect(lambda _c=False, idx=i: self._select(idx))
            self.chip_group.addButton(btn, i)
            self.chip_row.insertWidget(i, btn)
            self._chips.append(btn)
        if self._chips:
            self._chips[0].setChecked(True)

    def _refresh_overview(self) -> None:
        """Rebuild the selection overview list from current state."""
        if not hasattr(self, "overview"):
            return
        row = self.current
        self.overview.blockSignals(True)
        self.overview.clear()
        for i, st in enumerate(self.states):
            page = st.draft.page_index + 1
            if st.has_translation:
                status = "✓"
            elif st.translate_state == "running":
                status = "…"
            elif st.translate_state == "failed":
                status = "✗"
            else:
                status = "·"
            preview = (st.source_text or st.op.text or "").replace("\n", " ")
            if len(preview) > 28:
                preview = preview[:26] + "…"
            if not preview:
                preview = "（空）"
            label = f"{status} 选区 {i + 1}  ·  第 {page} 页  ·  {preview}"
            self.overview.addItem(label)
        if 0 <= row < self.overview.count():
            self.overview.setCurrentRow(row)
        self.overview.blockSignals(False)

    def _overview_row_changed(self, row: int) -> None:
        if row >= 0 and row != self.current:
            self._select(row)

    # ------------------------------------------------------------------ state <-> UI

    @property
    def _op(self) -> RegionOp:
        return self.states[self.current].op

    def _select(self, index: int) -> None:
        if not self.states:
            return
        index = max(0, min(len(self.states) - 1, index))
        self.current = index
        if index < len(self._chips):
            self._chips[index].setChecked(True)
        if hasattr(self, "overview") and self.overview.currentRow() != index:
            self.overview.blockSignals(True)
            self.overview.setCurrentRow(index)
            self.overview.blockSignals(False)
        self._load_state_into_ui()

    def _load_state_into_ui(self) -> None:
        st = self.states[self.current]
        op = st.op
        self._loading_ui = True

        pixmap = self.doc.pages[st.draft.page_index].raw_pixmap(PREVIEW_PAGE_WIDTH)
        self.preview.set_scene(pixmap, op)

        self.fill_well.set_color(op.fill_color)
        self.text_well.set_color(op.text_color)

        idx = self.font_combo.findData(op.font_family)
        if idx < 0:
            self.font_combo.addItem(op.font_family, op.font_family)
            idx = self.font_combo.count() - 1
        self.font_combo.setCurrentIndex(idx)

        orig_w = max(1, st.draft.page_size.width())
        self.auto_fit.setChecked(op.auto_fit)
        # Never lock the size box: users expect to be able to type a size at any
        # time, and doing so simply switches auto-fit off.
        self.size_spin.setEnabled(True)
        self.size_spin.setValue(max(6, int(round(op.font_ratio * orig_w))))
        self.spacing_spin.setValue(op.line_spacing)
        self.padding_spin.setValue(op.padding)
        self.bold_check.setChecked(op.bold)

        idx = self.shape_combo.findData(op.fill_shape)
        self.shape_combo.setCurrentIndex(max(0, idx))
        self.soft_spin.setValue(int(round(op.fill_soft * orig_w)))
        self.corner_spin.setValue(op.corner_radius)
        self.corner_spin.setEnabled((op.fill_shape or "rect") == "rounded")
        # Leaving the brush on when switching regions would make the next click
        # paint instead of moving the box.
        self.btn_brush.setChecked(False)
        self.preview.set_mode(self.preview.MODE_RECT)

        self.letter_spin.setValue(op.letter_spacing)
        self.colgap_spin.setValue(op.column_gap)
        self.rotation_spin.setValue(int(round(op.rotation or 0)))
        self._sync_layout_buttons(op.vertical)

        self.source_edit.setPlainText(st.source_text)
        self.translated_edit.setPlainText(op.text)

        rect = op.rect
        self._sync_rect_spins(rect)
        self.detail.setText(
            f"选区 {self.current + 1}/{len(self.states)} · 第 {st.draft.page_index + 1} 页 · "
            f"位置 ({rect.x():.2f}, {rect.y():.2f}) 尺寸 ({rect.width():.2f} × {rect.height():.2f})"
        )
        self._sync_effective_size()
        self._update_summary()
        self._loading_ui = False
        self._update_buttons()
        self._refresh_model_badge()
        self._refresh_overview()

    def _current_font_size(self, op, page_w: int) -> int:
        """The size the renderer would actually use right now."""
        if not op.auto_fit:
            return max(5, int(round(op.font_ratio * max(1, page_w))))
        st = self.states[self.current]
        orig_w = max(1, st.draft.page_size.width())
        orig_h = max(1, st.draft.page_size.height())
        rect = QRectF(op.rect.x() * orig_w, op.rect.y() * orig_h,
                      op.rect.width() * orig_w, op.rect.height() * orig_h)
        return textrender.fit_font_size(op, textrender.text_bounds(rect, op))

    def _sync_effective_size(self) -> None:
        """Show the real fitted font size, in both auto and manual mode."""
        st = self.states[self.current]
        op = st.op
        orig_w = max(1, st.draft.page_size.width())
        size = self._current_font_size(op, orig_w)
        self.size_spin.blockSignals(True)
        self.size_spin.setValue(size)
        self.size_spin.blockSignals(False)
        self._update_metrics()

    def _update_metrics(self) -> None:
        """Read out the real pixel values, so box resizing is verifiable at a glance."""
        st = self.states[self.current]
        op = st.op
        if not op.text.strip():
            self.metrics_label.setText("填入译文后这里会显示实际字号与间距")
            return
        orig_w = max(1, st.draft.page_size.width())
        orig_h = max(1, st.draft.page_size.height())
        size = self._current_font_size(op, orig_w)

        rect = QRectF(op.rect.x() * orig_w, op.rect.y() * orig_h,
                      op.rect.width() * orig_w, op.rect.height() * orig_h)
        inner = textrender.text_bounds(rect, op)
        pad = max(1.0, min(rect.width(), rect.height()) * max(0.0, op.padding))
        m = textrender.typing_metrics(op, size, inner)

        if op.vertical:
            text = (f"字号 {size}px · 字距 {m['letter_px']:.1f}px · "
                    f"列距 {m['column_gap_px']:.1f}px · 列数 {m['columns']} · "
                    f"边界内缩 {pad:.1f}px")
        else:
            text = (f"字号 {size}px · 字距 {m['letter_px']:.1f}px · "
                    f"行距 {m['line_pitch_px']:.1f}px · 行数 {m['lines']} · "
                    f"边界内缩 {pad:.1f}px")
        self.metrics_label.setText(text)

    def _update_buttons(self) -> None:
        st = self.states[self.current]
        self.btn_ocr.setEnabled(st.ocr_state != "running")
        self.btn_translate.setEnabled(st.translate_state != "running")
        # Keep the one-click button disabled while its own chain is running,
        # otherwise a status refresh would make it clickable again.
        self.btn_quick.setEnabled(not self._quick_active)
        if self._quick_active:
            self.btn_quick.setText("一键直通中…")
        else:
            self.btn_quick.setText("一键直通：识别 → 翻译 → 覆写")
        if st.ocr_state == "running":
            self.btn_ocr.setText("识别中…")
        else:
            self.btn_ocr.setText("识别本选区")
        if st.translate_state == "running":
            self.btn_translate.setText("翻译中…")
        else:
            self.btn_translate.setText(f"翻译（{self._model_short()}）")

    def _model_short(self) -> str:
        """Short model name for the translate button's parentheses."""
        try:
            from . import lmstudio
            label = lmstudio.cached_model_label(self.config)
        except Exception:
            label = None
        if label and "·" in label:
            model = label.split("·", 1)[1].strip()
            if model:
                return model if len(model) <= 26 else model[:24] + "…"
        return "当前模型"

    def _refresh_model_badge(self) -> None:
        """Show the current model without ever blocking the UI thread."""
        try:
            from . import lmstudio
            label = lmstudio.cached_model_label(self.config)
        except Exception:
            label = None

        if label:
            self.model_badge.setText(f"翻译模型：{label}")
            self.btn_translate.setToolTip(f"使用 {label} 翻译当前选区")
            self._update_buttons()
            return

        # Unknown yet (local server not probed): show a generic label now and
        # resolve it in the background, then update in place.
        fallback = "翻译模型：本地 LM Studio · 探测中…"
        self.model_badge.setText(fallback)
        self._start_model_probe()

    def _start_model_probe(self) -> None:
        if getattr(self, "_model_probe_task", None) is not None:
            return
        from .workers import ModelLabelTask
        task = ModelLabelTask(self.config)
        # Keep a reference on self: the dialog owns the task lifetime, which is
        # more robust than relying on the pool's keep-alive list.
        self._model_probe_task = task

        # Poll the task's plain attribute. Signals from this short-lived task
        # were unreliable ("Signal source has been deleted"), and polling works
        # regardless of when the dialog's event loop starts.
        self._model_probe_timer = QTimer(self)
        self._model_probe_timer.setInterval(150)
        self._model_probe_timer.timeout.connect(self._poll_model_probe)
        self._model_probe_timer.start()
        start_task(task)

    def _poll_model_probe(self) -> None:
        task = getattr(self, "_model_probe_task", None)
        if task is None or not getattr(task, "done", False):
            return
        self._model_probe_timer.stop()
        self._apply_model_label(getattr(task, "result", "") or "")

    def _apply_model_label(self, label: str) -> None:
        if not label:
            self.model_badge.setText("翻译模型：未连接")
            self._update_buttons()
            return
        self.model_badge.setText(f"翻译模型：{label}")
        self.btn_translate.setToolTip(f"使用 {label} 翻译当前选区")
        self._update_buttons()

    def _update_summary(self) -> None:
        done = sum(1 for s in self.states if s.has_translation)
        pages = sorted({s.draft.page_index + 1 for s in self.states})
        page_text = f"第 {', '.join(str(p) for p in pages)} 页" if pages else ""
        self.summary.setText(f"{page_text} · {len(self.states)} 处选区 · 已有译文 {done} 处")

    def _refresh_preview(self) -> None:
        self.preview.set_op(self._op)
        self._sync_effective_size()
        self._update_summary()

    # ------------------------------------------------------------------ rect editing

    def _sync_rect_spins(self, rect: QRectF) -> None:
        """Push a rect into the numeric fields without echoing events back."""
        values = {"x": rect.x(), "y": rect.y(),
                  "w": rect.width(), "h": rect.height()}
        for key, spin in self._rect_spins.items():
            spin.blockSignals(True)
            spin.setValue(values[key] * 100.0)
            spin.blockSignals(False)

    def _rect_dragged(self, rect: QRectF) -> None:
        """Live feedback while dragging the preview box."""
        st = self.states[self.current]
        st.op.rect = QRectF(rect)
        self._sync_rect_spins(rect)
        self._sync_effective_size()
        self._update_detail(rect)

    def _rect_committed(self, rect: QRectF) -> None:
        st = self.states[self.current]
        st.op.rect = QRectF(rect)
        self._sync_rect_spins(rect)
        self.preview.set_op(self._op)
        self._sync_effective_size()
        self._update_detail(rect)
        self.status.setText(
            f"选区已调整为 左 {rect.x():.0%} 上 {rect.y():.0%} "
            f"宽 {rect.width():.0%} 高 {rect.height():.0%}")

    def _rect_spin_changed(self, _value: float) -> None:
        if self._loading_ui:
            return
        values = {key: spin.value() / 100.0 for key, spin in self._rect_spins.items()}
        x = min(max(0.0, values["x"]), 1.0 - 0.01)
        y = min(max(0.0, values["y"]), 1.0 - 0.01)
        w = min(max(0.01, values["w"]), 1.0 - x)
        h = min(max(0.01, values["h"]), 1.0 - y)
        rect = QRectF(x, y, w, h)
        self.states[self.current].op.rect = rect
        self.preview.set_op(self._op)
        self._sync_effective_size()
        self._update_detail(rect)

    def _letter_changed(self, value: float) -> None:
        if self._loading_ui:
            return
        self._apply_style(letter_spacing=float(value))

    def _colgap_changed(self, value: float) -> None:
        if self._loading_ui:
            return
        self._apply_style(column_gap=float(value))

    def _set_layout_direction(self, vertical: bool) -> None:
        """Switch horizontal (left-to-right) / vertical (top-down) layout."""
        if self._loading_ui:
            return
        self._apply_style(vertical=bool(vertical))
        self.colgap_spin.setEnabled(bool(vertical))
        self.status.setText(
            "已切换为竖排：字符自上而下，列从右往左"
            if vertical else "已切换为横排：从左到右，由上到下")

    def _sync_layout_buttons(self, vertical: bool) -> None:
        self.btn_vertical.setChecked(bool(vertical))
        self.btn_horizontal.setChecked(not vertical)
        self.colgap_spin.setEnabled(bool(vertical))

    def _update_detail(self, rect: QRectF) -> None:
        st = self.states[self.current]
        self.detail.setText(
            f"选区 {self.current + 1}/{len(self.states)} · "
            f"第 {st.draft.page_index + 1} 页 · "
            f"位置 ({rect.x():.2f}, {rect.y():.2f}) "
            f"尺寸 ({rect.width():.2f} × {rect.height():.2f})"
        )

    # ------------------------------------------------------------------ style changes

    def _targets(self) -> list[_RegionState]:
        if self.sync_style.isChecked():
            return self.states
        return [self.states[self.current]]

    def _apply_style(self, **attrs) -> None:
        for st in self._targets():
            for key, value in attrs.items():
                setattr(st.op, key, value)
        self._refresh_preview()

    def _set_fill_color(self, color: QColor) -> None:
        if color is None or not color.isValid():
            return
        self.fill_well.set_color(color)
        self._apply_style(fill_color=QColor(color))
        self._sync_fill_widgets()

    def _sync_fill_widgets(self) -> None:
        op = self._op
        self.fill_well.set_color(op.fill_color)
        self.text_well.set_color(op.text_color)

    def _custom_fill_color(self) -> None:
        color = QColorDialog.getColor(self._op.fill_color, self, "选择底色",
                                      QColorDialog.ShowAlphaChannel)
        if color.isValid():
            self._set_fill_color(color)

    def _set_text_color(self, color: QColor) -> None:
        if color is None or not color.isValid():
            return
        self.text_well.set_color(color)
        self._apply_style(text_color=QColor(color))

    def _custom_text_color(self) -> None:
        color = QColorDialog.getColor(self._op.text_color, self, "选择文字颜色")
        if color.isValid():
            self._set_text_color(color)

    def _use_dominant_color(self) -> None:
        st = self.states[self.current]
        pixmap = self.doc.page_pixmap(st.draft.page_index, PREVIEW_PAGE_WIDTH)
        color = dominant_color(pixmap.toImage(), st.op.rect)
        self._set_fill_color(color)
        self.status.setText(f"已取选区主色 {color.name().upper()}")

    def _pick_color_from_canvas(self) -> None:
        # exec() makes this dialog application-modal, which would swallow the
        # clicks we need on the canvas behind it. Drop to non-modal while picking.
        self.hide()
        self.setWindowModality(Qt.NonModal)

        def done(color):
            self.setWindowModality(Qt.ApplicationModal)
            self.show()
            self.raise_()
            self.activateWindow()
            if color is not None and color.isValid():
                self._set_fill_color(color)
                self.status.setText(f"已从画面吸取颜色 {color.name().upper()}")

        QTimer.singleShot(30, lambda: self.canvas.begin_color_pick(done))

    def _font_changed(self, _index: int) -> None:
        if self._loading_ui:
            return
        family = self.font_combo.currentData()
        if family:
            self._apply_style(font_family=family)

    def _size_changed(self, value: int) -> None:
        if self._loading_ui:
            return
        for st in self._targets():
            width = max(1, st.draft.page_size.width())
            st.op.font_ratio = value / width
            st.op.auto_fit = False
        self.auto_fit.blockSignals(True)
        self.auto_fit.setChecked(False)
        self.auto_fit.blockSignals(False)
        self.size_spin.setEnabled(True)
        self._refresh_preview()

    def _auto_fit_changed(self, checked: bool) -> None:
        if self._loading_ui:
            return
        # Keep the box enabled either way; it just becomes read-only output
        # while auto-fit is on (editing it turns auto-fit off).
        self.size_spin.setEnabled(True)
        self._apply_style(auto_fit=bool(checked))

    def _spacing_changed(self, value: float) -> None:
        if self._loading_ui:
            return
        self._apply_style(line_spacing=float(value))

    def _padding_changed(self, value: float) -> None:
        if self._loading_ui:
            return
        self._apply_style(padding=float(value))

    def _bold_changed(self, checked: bool) -> None:
        if self._loading_ui:
            return
        self._apply_style(bold=bool(checked))

    def _shape_changed(self, _index: int) -> None:
        if self._loading_ui:
            return
        shape = self.shape_combo.currentData() or "rect"
        self._apply_style(fill_shape=shape)
        self.corner_spin.setEnabled(shape == "rounded")
        # "自定义描边" needs the mouse, so switch the preview into polygon mode.
        if shape == "polygon":
            self.preview.set_mode(self.preview.MODE_POLYGON)
            self.status.setText(
                "自定义描边：在预览区依次点击气泡轮廓上的点（至少 3 个），"
                "点会自动连成填充区域")
        elif self.preview.mode == self.preview.MODE_POLYGON:
            self.preview.set_mode(self.preview.MODE_RECT)
            self.preview.clear_polygon()

    def _rotation_changed(self, value: int) -> None:
        if self._loading_ui:
            return
        self._apply_style(rotation=float(value))

    def _corner_changed(self, value: float) -> None:
        if self._loading_ui:
            return
        self._apply_style(corner_radius=float(value))

    # ------------------------------------------------------------------ freehand

    def _toggle_brush(self, on: bool) -> None:
        if on:
            self.preview.set_mode(self.preview.MODE_BRUSH)
            self._sync_brush()
            self.status.setText(
                "涂鸦模式：在预览区按住左键涂抹。用底色可盖住残留原文，"
                "用线条色可补画被遮住的边框")
        else:
            self.preview.set_mode(self.preview.MODE_RECT)
            self.status.setText("已退出涂鸦模式")

    def _sync_brush(self) -> None:
        """Push the brush colour/size (in page pixels) into the preview."""
        st = self.states[self.current]
        page_w = max(1, st.draft.page_size.width())
        px = float(self.brush_spin.value())
        self.preview.set_brush(self.brush_well.color(), px / page_w)

    def _brush_width_changed(self, _value: float) -> None:
        if self._loading_ui:
            return
        self._sync_brush()

    def _pick_brush_color(self) -> None:
        color = QColorDialog.getColor(self.brush_well.color(), self, "涂鸦颜色")
        if color.isValid():
            self.brush_well.set_color(color)
            self._sync_brush()

    def _on_strokes_changed(self) -> None:
        self.preview.update()
        count = len(self._op.strokes or [])
        self.status.setText(f"涂鸦已更新（本选区共 {count} 笔）")

    def _on_polygon_changed(self) -> None:
        op = self._op
        if len(op.fill_polygon or []) >= 3:
            op.fill_shape = "polygon"
            idx = self.shape_combo.findData("polygon")
            self.shape_combo.blockSignals(True)
            self.shape_combo.setCurrentIndex(max(0, idx))
            self.shape_combo.blockSignals(False)
            self.status.setText(
                f"自定义描边：已记录 {len(op.fill_polygon)} 个点（继续点可加点）")
        self.preview.update()

    def _clear_strokes(self) -> None:
        self.preview.clear_strokes()
        self.status.setText("已清空本选区的涂鸦")

    def _clear_polygon(self) -> None:
        self.preview.clear_polygon()
        if (self.states[self.current].op.fill_shape or "") == "polygon":
            self.states[self.current].op.fill_shape = "rect"
            idx = self.shape_combo.findData("rect")
            self.shape_combo.blockSignals(True)
            self.shape_combo.setCurrentIndex(max(0, idx))
            self.shape_combo.blockSignals(False)
        self.preview.update()
        self.status.setText("已清除自定义描边，恢复为方形填充")

    def _soft_changed(self, value: int) -> None:
        if self._loading_ui:
            return
        # Stored as a page-width ratio so preview and export match.
        for st in self._targets():
            width = max(1, st.draft.page_size.width())
            st.op.fill_soft = float(value) / width
        self._refresh_preview()

    # ------------------------------------------------------------------ content

    def _source_changed(self) -> None:
        if self._loading_ui:
            return
        st = self.states[self.current]
        st.source_text = self.source_edit.toPlainText()
        if not self.translated_edit.toPlainText().strip():
            st.op.text = st.source_text
            st.has_translation = False
            self.preview.set_op(st.op)
        self._update_summary()

    def _translated_changed(self) -> None:
        if self._loading_ui:
            return
        st = self.states[self.current]
        st.op.text = self.translated_edit.toPlainText()
        st.has_translation = bool(st.op.text.strip())
        self.preview.set_op(st.op)
        self._sync_effective_size()
        self._update_summary()

    # ------------------------------------------------------------------ OCR

    def _schedule_auto_ocr(self) -> None:
        if self.config.auto_ocr and ocr.available_backends():
            self._ocr_all(auto=True)
        elif not ocr.available_backends():
            self.status.setText(
                "本机没有可用的 OCR 后端，请手动输入原文；"
                "或安装 manga-ocr（pip install manga-ocr）以识别日文。"
            )

    def _ocr_all(self, auto: bool = False) -> None:
        self._ocr_queue = [i for i, s in enumerate(self.states)
                           if s.ocr_state in ("idle", "failed")]
        if not self._ocr_queue:
            if not auto:
                self.status.setText("所有选区都已识别过。")
            return
        if not auto:
            self.status.setText(f"开始识别 {len(self._ocr_queue)} 处选区…")
        self._pump_ocr()

    def _ocr_current(self) -> None:
        idx = self.current
        st = self.states[idx]
        if st.ocr_state == "running":
            return
        self._ocr_queue = [i for i in self._ocr_queue if i != idx]
        self._start_ocr(idx)

    def _pump_ocr(self) -> None:
        if self._ocr_busy or not self._ocr_queue:
            return
        idx = self._ocr_queue.pop(0)
        self._start_ocr(idx)

    def _start_ocr(self, index: int) -> None:
        st = self.states[index]
        if st.ocr_state == "running":
            return
        st.ocr_state = "running"
        self._ocr_busy = True
        if index == self.current:
            self._update_buttons()
        try:
            crop = self.doc.pages[st.draft.page_index].crop_raw(st.op.rect)
        except Exception as exc:
            st.ocr_state = "failed"
            self._ocr_busy = False
            self.status.setText(f"OCR 取图失败：{exc}")
            return

        task = OCRTask(crop, self.config.ocr_backend, self.config.ocr_language)
        task.signals.finished.connect(lambda result, i=index: self._ocr_done(i, result))
        start_task(task)

    def _ocr_done(self, index: int, result) -> None:
        st = self.states[index]
        self._ocr_busy = False
        if getattr(result, "ok", False):
            st.ocr_state = "done"
            text = result.text
            st.source_text = text
            # Keep showing the source until a translation exists.
            if not st.has_translation:
                st.op.text = text
        else:
            st.ocr_state = "failed"
        if index == self.current:
            self._loading_ui = True
            self.source_edit.setPlainText(st.source_text)
            self.translated_edit.setPlainText("" if not st.has_translation else st.op.text)
            self._loading_ui = False
            self.preview.set_op(st.op)
            self._sync_effective_size()
            self._update_buttons()
            self._update_summary()
            if getattr(result, "ok", False):
                self.status.setText(f"识别完成（{result.backend}）")
            else:
                self.status.setText(str(getattr(result, "error", "识别失败")))
        if self.config.auto_translate and st.source_text.strip() and not st.has_translation:
            self._translate_index(index)
        self._pump_ocr()
        if self._quick_active:
            self._quick_step()

    # ------------------------------------------------------------------ overwrite only

    def _overwrite_only(self) -> None:
        """Paint the current text onto the page, keeping the panel open.

        Skips OCR and translation entirely - it only renders whatever is in the
        译文 box with the current fill/font settings. Re-clicking replaces the
        previous overwrite of the same region instead of stacking a new one.
        """
        st = self.states[self.current]
        text = (self.translated_edit.toPlainText() or st.source_text).strip()
        if not text:
            self.status.setText(
                "「译文」框是空的：先识别/翻译，或手动输入文字再覆写")
            return

        st.op.text = text
        st.has_translation = True
        self._persist_defaults()

        page_index = st.draft.page_index
        first_time = not getattr(st, "overwritten", False)
        st.overwritten = True
        self.overwriteRequested.emit(page_index, st.op)
        if first_time:
            self.status.setText(
                f"已覆写选区 {self.current + 1} 到画面"
                "（面板未关闭，可继续微调后再次覆写）")
        else:
            self.status.setText(f"已更新选区 {self.current + 1} 的覆写")

    # ------------------------------------------------------------------ one-click

    def _quick_apply(self) -> None:
        """OCR -> translate -> dominant fill -> write to page, for every region.

        Runs as a chain because both OCR and translation are asynchronous. Each
        finished step calls _quick_step again; when the work list is empty the
        dialog accepts itself.
        """
        if self._quick_active:
            return
        self._quick_active = True
        self.btn_quick.setEnabled(False)
        self.btn_quick.setText("一键直通中…")
        # Take the bubble's dominant colour as the fill, unless the user has
        # deliberately picked something else.
        for st in self.states:
            if not st.has_translation:
                try:
                    pixmap = self.doc.pages[st.draft.page_index].raw_pixmap(PREVIEW_PAGE_WIDTH)
                    st.op.fill_color = dominant_color(pixmap.toImage(), st.op.rect)
                except Exception:
                    pass
        self._quick_step()

    def _quick_step(self) -> None:
        """Advance the one-click chain by one region."""
        if not self._quick_active:
            return

        for index, st in enumerate(self.states):
            if st.ocr_state == "running" or st.translate_state == "running":
                return                      # wait for the async result

            if not st.source_text.strip() and st.ocr_state != "failed":
                if not ocr.available_backends():
                    self._quick_finished("没有可用的 OCR 引擎，已切换到手动模式")
                    return
                self.status.setText(f"一键直通：识别选区 {index + 1}…")
                self._start_ocr(index)
                return

            if not st.has_translation and st.source_text.strip():
                self.status.setText(f"一键直通：翻译选区 {index + 1}…")
                self._translate_index(index, quiet=True)
                return

        # Nothing left to do.
        done = sum(1 for s in self.states if s.has_translation)
        failed = len(self.states) - done
        if done == 0:
            self._quick_finished("一键直通失败：没有可用的译文，请检查 OCR 或 LM Studio")
            return
        self._quick_active = False
        self.status.setText(
            f"一键直通完成：{done} 处已翻译"
            + (f"，{failed} 处失败" if failed else "")
            + "，正在写入画面…")
        self._persist_defaults()
        super().accept()

    def _quick_finished(self, message: str) -> None:
        self._quick_active = False
        self.btn_quick.setEnabled(True)
        self.btn_quick.setText("一键直通：识别 → 翻译 → 覆写")
        self.status.setText(message)
        self._update_buttons()
    # ------------------------------------------------------------------ translation

    def _translate_current(self) -> None:
        idx = self.current
        text = self.states[idx].source_text.strip() or self.source_edit.toPlainText().strip()
        if not text:
            self.status.setText("没有原文可翻译，请先识别或输入原文。")
            return
        self._translate_index(idx, text)

    def _translate_all(self) -> None:
        pending = [i for i, s in enumerate(self.states)
                   if (s.source_text.strip() or s.op.text.strip())
                   and not s.has_translation]
        if not pending:
            self.status.setText("没有需要翻译的选区。")
            return
        for i in pending:
            st = self.states[i]
            text = st.source_text.strip() or st.op.text.strip()
            self._translate_index(i, text, quiet=True)
        self.status.setText(f"已提交 {len(pending)} 处翻译请求…")

    def _translate_index(self, index: int, text: str = "", quiet: bool = False) -> None:
        st = self.states[index]
        if st.translate_state == "running":
            return
        text = text or st.source_text.strip() or st.op.text.strip()
        if not text:
            return
        st.translate_state = "running"
        if index == self.current:
            self._update_buttons()
        task = TranslateTask(text, self.config)
        task.signals.progress.connect(
            lambda ev, i=index: self._translate_progress(i, ev))
        task.signals.finished.connect(lambda res, i=index: self._translate_done(i, res))
        start_task(task)
        if not quiet:
            self.status.setText("正在调用模型翻译…")

    def _translate_progress(self, index: int, event: dict) -> None:
        """Live read-out while a model is generating."""
        if index != self.current:
            return
        kind = event.get("kind")
        if kind == "start":
            self.metrics_label.setText(
                f"{event.get('provider', '')} · {event.get('model', '')} · 等待首字…")
            return
        if kind != "delta":
            return
        # Character count is a better live indicator than a rough token guess
        # that jumps around as the estimate resamples.
        partial = (event.get("text") or "").replace("\n", " ")
        speed = float(event.get("speed") or 0.0)
        ttft = float(event.get("ttft") or 0.0)
        self.metrics_label.setText(
            f"生成中 · {len(partial)} 字 · {speed:.1f} tok/s · 首字 {ttft:.2f}s")

    def _translate_done(self, index: int, payload) -> None:
        ok, value, metrics = (list(payload) + [{}])[:3]
        st = self.states[index]
        st.translate_state = "done" if ok else "failed"
        if ok:
            st.op.text = value
            st.has_translation = True
            if index == self.current:
                self._loading_ui = True
                self.translated_edit.setPlainText(value)
                self._loading_ui = False
        if index == self.current:
            self.preview.set_op(st.op)
            self._sync_effective_size()
            self._update_buttons()
            self._update_summary()
            if ok:
                summary = (metrics or {}).get("summary")
                if summary:
                    self.metrics_label.setText(summary)
                    self.status.setText("翻译完成")
                else:
                    self.metrics_label.setText(
                        f"{(metrics or {}).get('provider', '')} · "
                        f"{(metrics or {}).get('model', '')}".strip(" ·"))
                    self.status.setText("翻译完成")
            else:
                self.status.setText(f"翻译失败：{value}")
        if self._quick_active:
            self._quick_step()

    # ------------------------------------------------------------------ result

    def result_ops(self) -> list[tuple[int, RegionOp]]:
        return [(s.draft.page_index, s.op) for s in self.states if s.op.text.strip()]

    def all_ops(self) -> list[tuple[int, RegionOp]]:
        """Every state, including ones the user emptied (used to delete a region)."""
        return [(s.draft.page_index, s.op) for s in self.states]

    def accept(self) -> None:
        if not self.result_ops() and not self.preset_mode:
            self.status.setText("所有选区都是空的：至少填入原文或译文再应用。")
            return
        self._persist_defaults()
        super().accept()

    def _delete_current(self) -> None:
        """In edit mode, clearing the text and applying removes the region."""
        for st in self.states:
            st.op.text = ""
            st.source_text = ""
        super().accept()

    def _persist_defaults(self) -> None:
        op = self.states[0].op
        self.config.font_family = op.font_family
        self.config.bold = op.bold
        self.config.line_spacing = op.line_spacing
        self.config.padding = op.padding
        self.config.fill_mode = "custom"
        self.config.fill_color = op.fill_color.name()
        self.config.text_color = op.text_color.name()
        self.config.fill_shape = op.fill_shape
        self.config.rotation = op.rotation
        self.config.letter_spacing = op.letter_spacing
        self.config.column_gap = op.column_gap
        self.config.vertical_text = op.vertical
        # Store the feather in page pixels so the settings field stays readable.
        width = max(1, self.states[0].draft.page_size.width())
        self.config.fill_soft = int(round(op.fill_soft * width))

    def closeEvent(self, event) -> None:
        if self.canvas is not None:
            try:
                self.canvas.cancel_color_pick()
            except Exception:
                pass
        super().closeEvent(event)
