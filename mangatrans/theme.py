# -*- coding: utf-8 -*-
"""Dark, low-contrast UI theme."""

from __future__ import annotations

from PySide6.QtGui import QColor, QPalette
from PySide6.QtWidgets import QApplication

BG = "#0f1319"
PANEL = "#151b24"
PANEL_ALT = "#1b2230"
BORDER = "#28313f"
TEXT = "#dbe3ee"
TEXT_DIM = "#8b97a8"
ACCENT = "#2dd4bf"
ACCENT_DIM = "#1f9c8d"
DANGER = "#f2707f"

QSS = f"""
* {{
    font-family: "Microsoft YaHei UI", "Microsoft YaHei", "Noto Sans SC";
    font-size: 13px;
    outline: none;
}}
QWidget {{
    background: {BG};
    color: {TEXT};
}}
QMainWindow, QDialog {{ background: {BG}; }}

QFrame#Panel, QWidget#Panel {{
    background: {PANEL};
    border: 1px solid {BORDER};
    border-radius: 10px;
}}

QLabel {{ background: transparent; }}
QLabel#Title {{ font-size: 15px; font-weight: 600; }}
QLabel#SubTitle {{ color: {TEXT_DIM}; font-size: 12px; }}
QLabel#Hint {{ color: {TEXT_DIM}; font-size: 12px; }}
QLabel#Badge {{
    background: {PANEL_ALT};
    color: {TEXT_DIM};
    border: 1px solid {BORDER};
    border-radius: 9px;
    padding: 2px 9px;
    font-size: 12px;
}}

QPushButton {{
    background: {PANEL_ALT};
    border: 1px solid {BORDER};
    border-radius: 8px;
    /* Horizontal padding kept modest so narrow windows still fit the text. */
    padding: 7px 10px;
    color: {TEXT};
}}
QPushButton:hover {{ background: #232c3b; border-color: #37445a; }}
QPushButton:pressed {{ background: #1a2130; }}
QPushButton:disabled {{ color: #5a6474; background: #171d27; border-color: #222a36; }}
QPushButton#Primary {{
    background: {ACCENT_DIM};
    border: 1px solid {ACCENT};
    color: #04110f;
    font-weight: 600;
}}
QPushButton#Primary:hover {{ background: {ACCENT}; }}
QPushButton#Primary:disabled {{ background: #1d3a37; color: #5d7b78; border-color: #244a46; }}
QPushButton#Ghost {{ background: transparent; border: 1px solid {BORDER}; }}
QPushButton#Ghost:hover {{ background: {PANEL_ALT}; }}
QPushButton:checked {{
    background: #14312e;
    border: 1px solid {ACCENT_DIM};
    color: #9ff3e8;
}}
QPushButton#Primary:checked {{ background: {ACCENT}; color: #04110f; }}
QPushButton#Danger {{ color: {DANGER}; border-color: #43303a; }}
QPushButton#Danger:hover {{ background: #2a1d24; }}

QLineEdit, QTextEdit, QPlainTextEdit, QSpinBox, QDoubleSpinBox, QComboBox {{
    background: #10151d;
    border: 1px solid {BORDER};
    border-radius: 8px;
    padding: 6px 9px;
    selection-background-color: {ACCENT_DIM};
    selection-color: #04110f;
}}
QLineEdit:focus, QTextEdit:focus, QPlainTextEdit:focus, QSpinBox:focus,
QDoubleSpinBox:focus, QComboBox:focus {{
    border-color: {ACCENT_DIM};
}}
QSpinBox, QDoubleSpinBox {{
    padding: 6px 9px;
}}
QSpinBox::up-button, QSpinBox::down-button,
QDoubleSpinBox::up-button, QDoubleSpinBox::down-button {{
    width: 0px;
    border: none;
}}
QComboBox::drop-down {{ border: none; width: 22px; }}
QComboBox QAbstractItemView {{
    background: {PANEL_ALT};
    border: 1px solid {BORDER};
    selection-background-color: {ACCENT_DIM};
    selection-color: #04110f;
    padding: 4px;
}}

QCheckBox {{ spacing: 7px; background: transparent; }}
QCheckBox::indicator {{
    width: 16px; height: 16px;
    border-radius: 4px;
    border: 1px solid {BORDER};
    background: #10151d;
}}
QCheckBox::indicator:checked {{
    background: {ACCENT};
    border-color: {ACCENT};
    image: none;
}}

QSlider::groove:horizontal {{
    height: 4px; background: #232c3b; border-radius: 2px;
}}
QSlider::handle:horizontal {{
    background: {ACCENT}; width: 14px; height: 14px;
    margin: -5px 0; border-radius: 7px;
}}
QSlider::handle:horizontal:hover {{ background: #4ff0da; }}

QScrollArea {{ border: none; background: transparent; }}
QScrollBar:vertical {{
    background: transparent; width: 10px; margin: 2px;
}}
QScrollBar::handle:vertical {{
    background: #2c3646; border-radius: 5px; min-height: 30px;
}}
QScrollBar::handle:vertical:hover {{ background: #3b475a; }}
QScrollBar:horizontal {{
    background: transparent; height: 10px; margin: 2px;
}}
QScrollBar::handle:horizontal {{
    background: #2c3646; border-radius: 5px; min-width: 30px;
}}
QScrollBar::add-line, QScrollBar::sub-line {{ width: 0; height: 0; }}
QScrollBar::add-page, QScrollBar::sub-page {{ background: transparent; }}

QListWidget {{
    background: {PANEL};
    border: 1px solid {BORDER};
    border-radius: 10px;
    padding: 6px;
}}
QListWidget::item {{
    background: {PANEL_ALT};
    border: 1px solid transparent;
    border-radius: 8px;
    padding: 9px 10px;
    margin: 3px 1px;
    color: {TEXT};
}}
QListWidget::item:hover {{ border-color: #37445a; }}
QListWidget::item:selected {{
    border-color: {ACCENT_DIM};
    background: #14312e;
    color: #d7fff9;
}}

QTabWidget::pane {{
    border: 1px solid {BORDER};
    border-radius: 10px;
    background: {PANEL};
    top: -1px;
}}
QTabBar::tab {{
    background: transparent;
    color: {TEXT_DIM};
    padding: 7px 16px;
    margin-right: 4px;
    border-radius: 8px;
}}
QTabBar::tab:selected {{ background: {PANEL_ALT}; color: {TEXT}; }}
QTabBar::tab:hover {{ color: {TEXT}; }}

QMenuBar {{ background: {BG}; }}
QMenuBar::item {{ padding: 6px 12px; background: transparent; }}
QMenuBar::item:selected {{ background: {PANEL_ALT}; border-radius: 6px; }}
QMenu {{
    background: {PANEL_ALT};
    border: 1px solid {BORDER};
    border-radius: 10px;
    padding: 6px;
}}
QMenu::item {{ padding: 7px 24px 7px 14px; border-radius: 6px; }}
QMenu::item:selected {{ background: {ACCENT_DIM}; color: #04110f; }}
QMenu::separator {{ height: 1px; background: {BORDER}; margin: 5px 8px; }}

QToolBar {{ background: transparent; border: none; spacing: 6px; padding: 4px; }}
QStatusBar {{ background: {PANEL}; border-top: 1px solid {BORDER}; color: {TEXT_DIM}; }}
QStatusBar::item {{ border: none; }}

QProgressBar {{
    background: #10151d; border: 1px solid {BORDER};
    border-radius: 6px; height: 8px; text-align: center; color: transparent;
}}
QProgressBar::chunk {{ background: {ACCENT_DIM}; border-radius: 5px; }}

QSplitter::handle {{ background: transparent; }}
QToolTip {{
    background: {PANEL_ALT};
    color: {TEXT};
    border: 1px solid {BORDER};
    padding: 5px 8px;
    border-radius: 6px;
}}
"""


def apply_theme(app: QApplication) -> None:
    app.setStyle("Fusion")
    palette = QPalette()
    palette.setColor(QPalette.Window, QColor(BG))
    palette.setColor(QPalette.WindowText, QColor(TEXT))
    palette.setColor(QPalette.Base, QColor("#10151d"))
    palette.setColor(QPalette.AlternateBase, QColor(PANEL))
    palette.setColor(QPalette.Text, QColor(TEXT))
    palette.setColor(QPalette.Button, QColor(PANEL_ALT))
    palette.setColor(QPalette.ButtonText, QColor(TEXT))
    palette.setColor(QPalette.Highlight, QColor(ACCENT_DIM))
    palette.setColor(QPalette.HighlightedText, QColor("#04110f"))
    palette.setColor(QPalette.ToolTipBase, QColor(PANEL_ALT))
    palette.setColor(QPalette.ToolTipText, QColor(TEXT))
    palette.setColor(QPalette.Disabled, QPalette.Text, QColor("#5a6474"))
    palette.setColor(QPalette.Disabled, QPalette.ButtonText, QColor("#5a6474"))
    app.setPalette(palette)
    app.setStyleSheet(QSS)
