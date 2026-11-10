# -*- coding: utf-8 -*-
"""Settings dialog: LM Studio endpoint, OCR backend, default region style."""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QThreadPool, Qt
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QCheckBox,
    QFileDialog,
    QColorDialog,
    QComboBox,
    QDialog,
    QDoubleSpinBox,
    QFormLayout,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QScrollArea,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from . import i18n, lmstudio, ocr
from .config import AppConfig
from .constants import FILL_PRESETS, OCR_LANGUAGES, TEXT_COLORS
from .fonts import available_presets, available_presets_extra
from .widgets import ColorWell
from .workers import ProviderProbeTask, start_task


class SettingsDialog(QDialog):
    def __init__(self, config: AppConfig, parent=None):
        super().__init__(parent)
        self.setWindowTitle("设置")
        self.setModal(True)
        self.resize(700, 700)
        self.config = config
        self._pool = QThreadPool.globalInstance()

        root = QVBoxLayout(self)
        root.setContentsMargins(18, 16, 18, 14)
        root.setSpacing(12)

        title = QLabel("设置")
        title.setObjectName("Title")
        root.addWidget(title)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        host = QWidget()
        body = QVBoxLayout(host)
        body.setContentsMargins(0, 0, 16, 0)
        body.setSpacing(14)

        # ------------- translation provider
        body.addWidget(self._section("翻译模型"))
        prov_form = QFormLayout()
        prov_form.setLabelAlignment(Qt.AlignRight | Qt.AlignVCenter)
        prov_form.setFieldGrowthPolicy(QFormLayout.AllNonFixedFieldsGrow)
        prov_form.setRowWrapPolicy(QFormLayout.DontWrapRows)
        prov_form.setSpacing(8)

        prov_row = QHBoxLayout()
        self.provider_combo = QComboBox()
        # Two groups so the list reads as "local runtimes" vs "cloud APIs".
        self.provider_combo.addItem("── 本地运行时 ──", "__local__")
        for spec in lmstudio.local_providers():
            self.provider_combo.addItem(f"  {spec.name}", spec.key)
        self.provider_combo.addItem("── 云端 API ──", "__cloud__")
        for spec in lmstudio.cloud_providers():
            self.provider_combo.addItem(f"  {spec.name}", spec.key)
        for row in (0, self.provider_combo.count() - len(lmstudio.cloud_providers()) - 1):
            item = self.provider_combo.model().item(row)
            if item is not None:
                item.setEnabled(False)
        idx = self.provider_combo.findData(config.provider)
        self.provider_combo.setCurrentIndex(max(0, idx))
        self.provider_combo.currentIndexChanged.connect(self._provider_changed)
        prov_row.addWidget(self.provider_combo, 1)
        self.btn_probe = QPushButton("测试连接")
        self.btn_probe.clicked.connect(self._probe)
        prov_row.addWidget(self.btn_probe)
        prov_form.addRow("供应商", self._wrap(prov_row))

        self.provider_hint = QLabel("")
        self.provider_hint.setObjectName("Hint")
        self.provider_hint.setWordWrap(True)
        prov_form.addRow("", self.provider_hint)

        lang_label = QLabel("简体中文（固定）")
        lang_label.setObjectName("Hint")
        lang_label.setToolTip("翻译结果统一为简体中文，并会对模型输出再做一次繁转简")
        prov_form.addRow("目标语言", lang_label)

        self.auto_translate = QCheckBox("识别完成后自动翻译")
        self.auto_translate.setChecked(config.auto_translate)
        prov_form.addRow("", self.auto_translate)
        body.addLayout(prov_form)

        # --- one settings block, reused for every provider ----------------
        self.prov_group = QWidget()
        pf = QFormLayout(self.prov_group)
        pf.setContentsMargins(0, 6, 0, 0)
        pf.setLabelAlignment(Qt.AlignRight | Qt.AlignVCenter)
        pf.setFormAlignment(Qt.AlignLeft | Qt.AlignTop)
        pf.setFieldGrowthPolicy(QFormLayout.AllNonFixedFieldsGrow)
        pf.setRowWrapPolicy(QFormLayout.DontWrapRows)
        pf.setSpacing(8)

        self.base_url_edit = QLineEdit("")
        self.base_url_edit.setPlaceholderText("http://127.0.0.1:1234/v1")
        pf.addRow("接口地址", self.base_url_edit)

        key_row = QHBoxLayout()
        self.api_key_edit = QLineEdit("")
        self.api_key_edit.setEchoMode(QLineEdit.Password)
        self.api_key_edit.setPlaceholderText("本地运行时留空；云端填 API Key")
        key_row.addWidget(self.api_key_edit, 1)
        self.show_key = QCheckBox("显示")
        self.show_key.toggled.connect(
            lambda on: self.api_key_edit.setEchoMode(
                QLineEdit.Normal if on else QLineEdit.Password))
        key_row.addWidget(self.show_key)
        self.key_host = self._wrap(key_row)
        self.key_label = QLabel("API Key")
        pf.addRow(self.key_label, self.key_host)

        self.model_combo = QComboBox()
        self.model_combo.setEditable(True)
        pf.addRow("模型", self.model_combo)

        self.temp_spin = QDoubleSpinBox()
        self.temp_spin.setRange(0.0, 1.5)
        self.temp_spin.setSingleStep(0.1)
        self.temp_spin.setDecimals(2)
        pf.addRow("温度", self.temp_spin)

        self.lm_status = QLabel("")
        self.lm_status.setObjectName("Hint")
        self.lm_status.setWordWrap(True)
        pf.addRow("", self.lm_status)
        body.addWidget(self.prov_group)

        # --- autosave -----------------------------------------------------
        auto_form = QFormLayout()
        auto_form.setLabelAlignment(Qt.AlignRight | Qt.AlignVCenter)
        self.autosave_spin = QSpinBox()
        self.autosave_spin.setRange(1, 120)
        self.autosave_spin.setSuffix(" 分钟")
        self.autosave_spin.setValue(max(1, int(config.autosave_seconds) // 60))
        self.autosave_spin.setToolTip(
            "翻译进度会定期写入本机；改动、翻页时还会立即保存一次")
        auto_form.addRow(i18n.tr("自动保存进度"), self.autosave_spin)

        self.lang_combo = QComboBox()
        for code, label in i18n.LANGS:
            self.lang_combo.addItem(label, code)
        idx = self.lang_combo.findData(config.language)
        self.lang_combo.setCurrentIndex(max(0, idx))
        self.lang_combo.setToolTip(
            "切换界面语言；长文本（帮助 / 关于）保持中英对照")
        auto_form.addRow(i18n.tr("界面语言"), self.lang_combo)
        body.addLayout(auto_form)

        self._load_provider_into_form()
        self._provider_changed()

        body.addWidget(self._hline())

        # ------------- OCR
        body.addWidget(self._section("文字识别（OCR）"))
        ocr_form = QFormLayout()
        ocr_form.setLabelAlignment(Qt.AlignRight | Qt.AlignVCenter)
        ocr_form.setSpacing(8)

        self.ocr_backend = QComboBox()
        self.ocr_backend.addItem("自动选择（优先 manga-ocr）", "auto")
        self.ocr_backend.addItem("manga-ocr（日文漫画专用）", "manga")
        self.ocr_backend.addItem("Windows OCR（中文 / 英文）", "windows")
        self.ocr_backend.addItem("不使用（仅手动输入）", "manual")
        idx = self.ocr_backend.findData(config.ocr_backend)
        self.ocr_backend.setCurrentIndex(max(0, idx))
        ocr_form.addRow("识别引擎", self.ocr_backend)

        self.ocr_lang = QComboBox()
        for code, label in OCR_LANGUAGES:
            self.ocr_lang.addItem(f"{label}（{code}）", code)
        idx = self.ocr_lang.findData(config.ocr_language)
        self.ocr_lang.setCurrentIndex(max(0, idx))
        ocr_form.addRow("Windows OCR 语言", self.ocr_lang)

        self.auto_ocr = QCheckBox("打开选区时自动识别原文")
        self.auto_ocr.setChecked(config.auto_ocr)
        ocr_form.addRow("", self.auto_ocr)

        # The main exe does not bundle torch; Japanese OCR runs in an external
        # Python. Let the user point at one explicitly when detection fails.
        python_row = QHBoxLayout()
        self.python_edit = QLineEdit(config.ocr_python)
        self.python_edit.setPlaceholderText("留空 = 自动探测（推荐）")
        python_row.addWidget(self.python_edit, 1)
        btn_browse = QPushButton("浏览…")
        btn_browse.clicked.connect(self._pick_python)
        python_row.addWidget(btn_browse)
        self.btn_probe_py = QPushButton("检测")
        self.btn_probe_py.setToolTip("检查该 Python 是否装了 manga-ocr")
        self.btn_probe_py.clicked.connect(self._probe_python)
        python_row.addWidget(self.btn_probe_py)
        ocr_form.addRow("OCR Python", self._wrap(python_row))
        body.addLayout(ocr_form)

        self.python_status = QLabel("")
        self.python_status.setObjectName("Hint")
        self.python_status.setWordWrap(True)
        body.addWidget(self.python_status)
        self._refresh_python_status()

        note = "当前可用引擎：" + ocr.describe_backends() + "。"
        if ocr.manga_ocr_available():
            note += (
                "\n日文漫画请保持「自动选择」或选 manga-ocr：它会自动把竖排气泡"
                "切成单列再逐列识别，整块送进去会漏行。首次识别需要加载模型，约需几秒。"
            )
        elif ocr.manga_backend_available():
            note += (
                "\n主程序未内置 manga-ocr，将调用外部 Python（torch 等重依赖不打包进 exe，"
                "因此改 OCR 逻辑不需要重新打包）。"
            )
        else:
            note += (
                "\nWindows 自带 OCR 不含日文语言包。识别日文漫画请安装 manga-ocr"
                "（pip install manga-ocr）；也可以直接手打原文。"
            )
        ocr_note = QLabel(note)
        ocr_note.setObjectName("Hint")
        ocr_note.setWordWrap(True)
        body.addWidget(ocr_note)

        body.addWidget(self._hline())

        # ------------- default style
        body.addWidget(self._section("默认文字样式"))
        style_form = QFormLayout()
        style_form.setLabelAlignment(Qt.AlignRight | Qt.AlignVCenter)
        style_form.setSpacing(8)

        self.font_combo = QComboBox()
        used: set[str] = set()
        for family, label in available_presets():
            self.font_combo.addItem(f"{label}  ·  {family}", family)
            used.add(family)
        for family, label in available_presets_extra():
            if family in used:
                continue
            self.font_combo.addItem(f"{label}  ·  {family}", family)
        idx = self.font_combo.findData(config.font_family)
        self.font_combo.setCurrentIndex(max(0, idx))
        style_form.addRow("字体", self.font_combo)

        self.spacing_spin = QDoubleSpinBox()
        self.spacing_spin.setRange(0.85, 2.5)
        self.spacing_spin.setSingleStep(0.05)
        self.spacing_spin.setDecimals(2)
        self.spacing_spin.setValue(config.line_spacing)
        style_form.addRow("行距", self.spacing_spin)

        self.padding_spin = QDoubleSpinBox()
        self.padding_spin.setRange(0.0, 0.30)
        self.padding_spin.setSingleStep(0.01)
        self.padding_spin.setDecimals(2)
        self.padding_spin.setValue(config.padding)
        style_form.addRow("边距", self.padding_spin)

        shape_row = QHBoxLayout()
        self.shape_combo = QComboBox()
        self.shape_combo.addItem("方形填充", "rect")
        self.shape_combo.addItem("椭圆填充（圆形气泡）", "ellipse")
        idx = self.shape_combo.findData(config.fill_shape)
        self.shape_combo.setCurrentIndex(max(0, idx))
        shape_row.addWidget(self.shape_combo, 1)
        shape_row.addWidget(QLabel("羽化"))
        self.soft_spin = QSpinBox()
        self.soft_spin.setRange(0, 60)
        self.soft_spin.setSuffix(" px")
        self.soft_spin.setValue(int(config.fill_soft))
        shape_row.addWidget(self.soft_spin)
        style_form.addRow("填充形状", self._wrap(shape_row))

        fill_row = QHBoxLayout()
        self.fill_well = ColorWell(config.fill_color)
        fill_row.addWidget(self.fill_well, 1)
        btn_fill = QPushButton("选择…")
        btn_fill.clicked.connect(
            lambda: self._pick_color(self.fill_well, "选择默认底色"))
        fill_row.addWidget(btn_fill)
        presets_row = QHBoxLayout()
        presets_row.setSpacing(4)
        for label, value in FILL_PRESETS[:6]:
            btn = QPushButton()
            btn.setFixedSize(20, 20)
            btn.setToolTip(label)
            btn.setStyleSheet(
                f"background:{value}; border:1px solid #3b475a; border-radius:5px;")
            btn.clicked.connect(
                lambda _c=False, v=value: self.fill_well.set_color(QColor(v)))
            presets_row.addWidget(btn)
        presets_row.addStretch(1)
        fill_host = QWidget()
        fill_layout = QVBoxLayout(fill_host)
        fill_layout.setContentsMargins(0, 0, 0, 0)
        fill_layout.setSpacing(4)
        fill_layout.addLayout(fill_row)
        fill_layout.addLayout(presets_row)
        style_form.addRow("默认底色", fill_host)

        text_row = QHBoxLayout()
        self.text_well = ColorWell(config.text_color)
        text_row.addWidget(self.text_well, 1)
        btn_text = QPushButton("选择…")
        btn_text.clicked.connect(
            lambda: self._pick_color(self.text_well, "选择默认文字颜色"))
        text_row.addWidget(btn_text)
        for _label, value in TEXT_COLORS:
            btn = QPushButton()
            btn.setFixedSize(20, 20)
            btn.setStyleSheet(
                f"background:{value}; border:1px solid #3b475a; border-radius:5px;")
            btn.clicked.connect(
                lambda _c=False, v=value: self.text_well.set_color(QColor(v)))
            text_row.addWidget(btn)
        style_form.addRow("默认文字色", self._wrap(text_row))
        body.addLayout(style_form)
        body.addStretch(1)

        scroll.setWidget(host)
        root.addWidget(scroll, 1)

        footer = QHBoxLayout()
        footer.addStretch(1)
        btn_cancel = QPushButton("取消")
        btn_cancel.clicked.connect(self.reject)
        footer.addWidget(btn_cancel)
        btn_save = QPushButton("保存")
        btn_save.setObjectName("Primary")
        btn_save.clicked.connect(self.accept)
        footer.addWidget(btn_save)
        root.addLayout(footer)

    # ------------------------------------------------------------------ helpers

    @staticmethod
    def _section(text: str) -> QLabel:
        lab = QLabel(text)
        lab.setObjectName("SubTitle")
        return lab

    @staticmethod
    def _hline() -> QFrame:
        line = QFrame()
        line.setFrameShape(QFrame.HLine)
        line.setStyleSheet("color:#28313f; background:#28313f; max-height:1px;")
        return line

    @staticmethod
    def _wrap(layout) -> QWidget:
        widget = QWidget()
        widget.setLayout(layout)
        layout.setContentsMargins(0, 0, 0, 0)
        return widget

    def _pick_color(self, well: ColorWell, title: str) -> None:
        color = QColorDialog.getColor(well.color(), self, title)
        if color.isValid():
            well.set_color(color)

    def _pick_python(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self, "选择已安装 manga-ocr 的 Python", "",
            "Python (python.exe);;所有文件 (*.*)")
        if path:
            self.python_edit.setText(path)
            self._probe_python()

    def _probe_python(self) -> None:
        """Check the configured interpreter can actually do manga OCR."""
        from .ocr_worker_client import _probe, find_worker_python

        configured = self.python_edit.text().strip()
        if configured:
            info = _probe(configured)
            if info and info.get("manga_ocr"):
                self.python_status.setText(
                    f"✅ {Path(configured).name} 可用"
                    f"（Python {info.get('version', '?')}，"
                    f"模型{'已缓存' if info.get('model_cached') else '未下载'}）")
                return
            self.python_status.setText(
                f"❌ 该 Python 不可用：{configured}\n"
                "请确认已执行 pip install manga-ocr")
            return

        python, info = find_worker_python(force=True)
        if python:
            self.python_status.setText(
                f"✅ 自动探测到：{python}"
                f"（模型{'已缓存' if info.get('model_cached') else '未下载'}）")
        else:
            self.python_status.setText(
                "❌ 未探测到可用的 Python。请安装 manga-ocr，"
                "或在此填入 python.exe 的完整路径。")

    def _refresh_python_status(self) -> None:
        from .ocr_worker_client import find_worker_python

        if ocr.manga_ocr_available():
            self.python_status.setText(
                "✅ 当前运行环境已内置 manga-ocr，无需外部 Python。")
            self.python_edit.setEnabled(False)
            self.btn_probe_py.setEnabled(False)
            return
        python, info = find_worker_python()
        if python:
            self.python_status.setText(
                f"✅ 外部 OCR 就绪：{python}"
                f"（模型{'已缓存' if info.get('model_cached') else '未下载'}）")
        else:
            self.python_status.setText(
                "⚠️ 未找到可用的外部 Python；日文 OCR 会退化为手动输入。")

    def _current_provider(self) -> "lmstudio.ProviderSpec":
        key = self.provider_combo.currentData() or "lmstudio"
        if key.startswith("__"):
            # A section header was selected; fall back to the first real entry.
            key = "lmstudio"
        return lmstudio.provider_spec(key)

    def _load_provider_into_form(self) -> None:
        """Fill the settings block from the saved profile of this provider."""
        spec = self._current_provider()
        prof = lmstudio.provider_profile(self.config, spec.key)

        self.base_url_edit.setText(prof["base_url"] or spec.base_url)
        self.api_key_edit.setText(prof["api_key"])
        self.temp_spin.setValue(prof["temperature"])

        self.model_combo.clear()
        for name in spec.models:
            self.model_combo.addItem(name)
        current = prof["model"] or spec.default_model
        if current:
            self.model_combo.setCurrentText(current)

        # Local runtimes do not use an API key: hide the label too, otherwise
        # an orphan "API Key" text sits above a missing field.
        show_key = not spec.is_local
        self.key_host.setVisible(show_key)
        self.key_label.setVisible(show_key)

    def _provider_changed(self, *_args) -> None:
        """Switch the form over to the newly selected provider."""
        spec = self._current_provider()
        self._load_provider_into_form()

        bits = []
        if spec.hint:
            bits.append(spec.hint)
        bits.append("本地运行时：数据不出本机" if spec.is_local
                    else "云端 API：文本会发送到该平台")
        if spec.api_style == "anthropic":
            bits.append("使用 Anthropic 原生 Messages 接口")
        self.provider_hint.setText(" · ".join(bits))
        self.lm_status.setText("")
        self.base_url_edit.setPlaceholderText(
            "http://127.0.0.1:1234/v1" if spec.is_local
            else (spec.base_url or "https://…/v1"))

    def _collect_form(self) -> dict:
        return {
            "base_url": lmstudio.normalize_base_url(self.base_url_edit.text()),
            "model": self.model_combo.currentText().strip(),
            "api_key": self.api_key_edit.text().strip(),
            "temperature": float(self.temp_spin.value()),
        }

    def _probe(self) -> None:
        spec = self._current_provider()
        self.btn_probe.setEnabled(False)
        self.lm_status.setText("正在连接…")

        # Probe the values currently in the form, not the saved ones, so the
        # user can validate an edit before pressing 保存.
        from mangatrans.config import AppConfig
        probe_cfg = AppConfig()
        probe_cfg.provider = spec.key
        probe_cfg.provider_profiles = {
            spec.key: self._collect_form(),
        }
        task = ProviderProbeTask(probe_cfg)
        task.signals.finished.connect(self._probe_done)
        start_task(task)

    def _probe_done(self, payload) -> None:
        self.btn_probe.setEnabled(True)
        ok, message, models = payload
        if not ok:
            self.lm_status.setText(message)
            return

        chat = [m for m in models if not lmstudio._looks_like_embedding(m)]
        skipped = [m for m in models if m not in chat]
        detail = message
        if chat:
            detail += f"，可用翻译模型 {len(chat)} 个"
            if skipped:
                detail += f"（已隐藏 {len(skipped)} 个 embedding 模型）"
        elif models:
            detail = "已连接，但只有 embedding 模型，请换一个对话模型。"
        else:
            detail = "已连接，但没有可用的对话模型。"
        self.lm_status.setText(detail)

        if not chat:
            return
        current = self.model_combo.currentText().strip()
        self.model_combo.clear()
        self.model_combo.addItems(chat)
        self.model_combo.setCurrentText(
            current if current in chat else lmstudio.pick_chat_model(chat))

    # ------------------------------------------------------------------ result

    def apply_to_config(self) -> None:
        cfg = self.config
        lmstudio.clear_label_cache()
        spec = self._current_provider()
        cfg.provider = spec.key
        lmstudio.save_provider_profile(cfg, spec.key, **self._collect_form())
        # Keep the legacy mirror fields pointing at the active provider so old
        # code paths (and older saved files) keep working.
        prof = lmstudio.provider_profile(cfg, spec.key)
        if spec.is_local:
            cfg.lm_base_url = prof["base_url"]
            cfg.lm_model = prof["model"]
            cfg.lm_temperature = prof["temperature"]
        else:
            cfg.api_base_url = prof["base_url"]
            cfg.api_key = prof["api_key"]
            cfg.api_model = prof["model"]
            cfg.api_temperature = prof["temperature"]
        cfg.autosave_seconds = int(self.autosave_spin.value()) * 60
        cfg.language = self.lang_combo.currentData() or "zh"
        cfg.auto_translate = self.auto_translate.isChecked()
        cfg.ocr_backend = self.ocr_backend.currentData()
        cfg.ocr_language = self.ocr_lang.currentData()
        cfg.ocr_python = self.python_edit.text().strip()
        cfg.auto_ocr = self.auto_ocr.isChecked()
        cfg.font_family = self.font_combo.currentData() or cfg.font_family
        cfg.line_spacing = float(self.spacing_spin.value())
        cfg.padding = float(self.padding_spin.value())
        cfg.fill_color = self.fill_well.color().name()
        cfg.fill_shape = self.shape_combo.currentData() or "rect"
        cfg.fill_soft = int(self.soft_spin.value())
        cfg.text_color = self.text_well.color().name()
