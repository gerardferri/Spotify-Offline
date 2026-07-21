from __future__ import annotations

from PySide6.QtGui import QFont, QPalette
from PySide6.QtWidgets import QApplication


LIGHT = """
QWidget { color: #17201b; background: #f5f7f5; font-family: "Segoe UI Variable", "Segoe UI"; font-size: 14px; }
QMainWindow, QWidget#appShell, QStackedWidget { background: #f5f7f5; }
QFrame#sidebar { background: #ffffff; border-right: 1px solid #e1e7e3; }
QLabel#brandMark { color: #0f7a43; background: #dff7e9; border-radius: 10px; font-size: 22px; font-weight: 900; }
QLabel#brandName { color: #111814; background: transparent; font-size: 17px; font-weight: 800; }
QLabel#sidebarSectionLabel { color: #89958e; background: transparent; font-size: 10px; font-weight: 800; padding: 0 12px; }
QLabel#localStatus { color: #177c49; font-weight: 700; }
QFrame#card, QFrame#player, QFrame#settingsCard, QFrame#profileCard { background: #ffffff; border: 1px solid #dfe6e1; border-radius: 13px; }
QFrame#driveCard { background: #edf9f2; border: 1px solid #bfe5ce; border-radius: 13px; }
QFrame#card QLabel, QFrame#card QCheckBox, QFrame#player QLabel, QFrame#settingsCard QLabel, QFrame#profileCard QLabel, QFrame#driveCard QLabel { background: transparent; border: 0; }
QFrame#card:hover { border-color: #c8d4cd; }
QLabel[heading="true"] { color: #101713; font-size: 29px; font-weight: 800; }
QLabel[subheading="true"] { color: #101713; font-size: 18px; font-weight: 700; }
QLabel[eyebrow="true"] { color: #16834c; font-size: 10px; font-weight: 800; }
QLabel[muted="true"] { color: #68756d; }
QLabel[accent="true"] { color: #16834c; }
QLineEdit, QComboBox, QSpinBox { background: #ffffff; color: #17201b; border: 1px solid #bdc9c1; border-radius: 9px; padding: 9px 11px; min-height: 22px; selection-background-color: #1eaa63; selection-color: #ffffff; }
QLineEdit:hover, QComboBox:hover, QSpinBox:hover { border-color: #8fa196; }
QLineEdit:focus, QComboBox:focus, QSpinBox:focus { border: 2px solid #1a9b59; padding: 8px 10px; }
QComboBox QAbstractItemView { background: #ffffff; color: #17201b; border: 1px solid #cdd6d0; selection-background-color: #e2f6eb; selection-color: #0c5f35; outline: 0; }
QPushButton { background: #1faa63; color: #ffffff; border: 1px solid #1faa63; border-radius: 9px; padding: 9px 16px; font-weight: 700; min-height: 22px; }
QPushButton:hover { background: #178f52; border-color: #178f52; } QPushButton:pressed { background: #117543; border-color: #117543; }
QPushButton:focus { border: 2px solid #0f683a; padding: 8px 15px; }
QPushButton:disabled { background: #e3e8e5; border-color: #e3e8e5; color: #8a958e; }
QPushButton[secondary="true"] { background: #ffffff; color: #344139; border: 1px solid #cfd8d2; }
QPushButton[secondary="true"]:hover { background: #f0f4f1; border-color: #aebdb4; }
QPushButton[secondary="true"]:pressed { background: #e5ebe7; }
QPushButton[playerControl="true"] { border-radius: 20px; min-width: 40px; max-width: 40px; min-height: 40px; max-height: 40px; padding: 0; }
QListWidget { background: transparent; border: 0; outline: 0; }
QListWidget#navigation { background: transparent; color: #59665e; padding: 0; }
QListWidget#navigation::item { padding: 0 13px; margin: 2px 0; border-radius: 9px; font-weight: 600; }
QListWidget#navigation::item:hover { background: #f1f5f2; color: #17201b; }
QListWidget#navigation::item:selected { background: #e4f6eb; color: #116f40; border-left: 3px solid #1faa63; }
QListWidget#navigation::item:focus { outline: none; }
QCheckBox { spacing: 8px; color: #46534b; }
QCheckBox::indicator { width: 17px; height: 17px; border: 1px solid #aebbb3; border-radius: 4px; background: #ffffff; }
QCheckBox::indicator:hover { border-color: #1faa63; }
QCheckBox::indicator:checked { background: #1faa63; border-color: #1faa63; }
QProgressBar { border: 0; border-radius: 4px; text-align: center; background: #dfe7e2; min-height: 7px; max-height: 7px; color: transparent; }
QProgressBar::chunk { background: #1faa63; border-radius: 4px; }
QSlider::groove:horizontal { height: 4px; background: #d8e1db; border-radius: 2px; }
QSlider::sub-page:horizontal { background: #1faa63; border-radius: 2px; }
QSlider::handle:horizontal { background: #168c51; border: 2px solid #ffffff; width: 14px; height: 14px; margin: -6px 0; border-radius: 8px; }
QLabel[error="true"] { color: #a62c2c; background: #fff0f0; border: 1px solid #efb4b4; border-radius: 8px; padding: 8px; }
QTableWidget { background: #ffffff; alternate-background-color: #f5f8f6; border: 1px solid #dce5df; border-radius: 10px; gridline-color: transparent; outline: 0; }
QTableWidget::item { padding: 9px; border-bottom: 1px solid #edf1ee; }
QTableWidget::item:selected { background: #dcf5e7; color: #102017; }
QHeaderView::section { background: #f0f3f1; color: #536159; padding: 10px; border: 0; border-bottom: 1px solid #dce5df; font-weight: 700; }
QScrollBar:vertical { background: transparent; width: 10px; margin: 2px; }
QScrollBar::handle:vertical { background: #c7d1cb; border-radius: 5px; min-height: 28px; }
QScrollBar::handle:vertical:hover { background: #aab8b0; }
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical { height: 0; }
QStatusBar { background: #ffffff; border-top: 1px solid #dce5df; color: #65736b; padding-left: 8px; }
QToolTip { background: #17201b; color: #ffffff; border: 0; padding: 6px; }
"""

DARK = """
QWidget { color: #f3f7f4; background: #0b100d; font-family: "Segoe UI Variable", "Segoe UI"; font-size: 14px; }
QMainWindow, QWidget#appShell, QStackedWidget { background: #0b100d; }
QFrame#sidebar { background: #101713; border-right: 1px solid #222d27; }
QLabel#brandMark { color: #62e49e; background: #173824; border-radius: 10px; font-size: 22px; font-weight: 900; }
QLabel#brandName { color: #f7faf8; background: transparent; font-size: 17px; font-weight: 800; }
QLabel#sidebarSectionLabel { color: #718078; background: transparent; font-size: 10px; font-weight: 800; padding: 0 12px; }
QLabel#localStatus { color: #62e49e; font-weight: 700; }
QFrame#card, QFrame#player, QFrame#settingsCard, QFrame#profileCard { background: #151d19; border: 1px solid #2a3831; border-radius: 12px; }
QFrame#driveCard { background: #13271c; border: 1px solid #28563a; border-radius: 12px; }
QFrame#card QLabel, QFrame#card QCheckBox, QFrame#player QLabel, QFrame#settingsCard QLabel, QFrame#profileCard QLabel, QFrame#driveCard QLabel { background: transparent; border: 0; }
QFrame#card:hover { border-color: #3c5146; background: #18231d; }
QLabel[heading="true"] { color: #f7faf8; font-size: 29px; font-weight: 800; }
QLabel[subheading="true"] { color: #f7faf8; font-size: 18px; font-weight: 700; }
QLabel[eyebrow="true"] { color: #4bd88d; font-size: 10px; font-weight: 800; }
QLabel[muted="true"] { color: #93a39a; }
QLabel[accent="true"] { color: #24c879; }
QLineEdit, QComboBox, QSpinBox { background: #121915; color: #f7faf8; border: 1px solid #3a4c42; border-radius: 9px; padding: 9px 11px; min-height: 22px; selection-background-color: #24c879; selection-color: #04140c; }
QLineEdit:hover, QComboBox:hover, QSpinBox:hover { border-color: #50665a; }
QLineEdit:focus, QComboBox:focus, QSpinBox:focus { border: 2px solid #39d586; padding: 8px 10px; }
QComboBox QAbstractItemView { background: #151d19; color: #f7faf8; border: 1px solid #34463d; selection-background-color: #24372d; }
QPushButton { background: #2bd27d; color: #04140c; border: 1px solid #2bd27d; border-radius: 9px; padding: 9px 16px; font-weight: 800; min-height: 22px; }
QPushButton:hover { background: #4ade93; } QPushButton:pressed { background: #1eab67; }
QPushButton:focus { border: 2px solid #a0f2c5; padding: 8px 15px; }
QPushButton:disabled { background: #29342e; border-color: #29342e; color: #748179; }
QPushButton[secondary="true"] { background: #1b2520; color: #e9efeb; border: 1px solid #34463d; }
QPushButton[secondary="true"]:hover { background: #243129; border-color: #52675c; }
QPushButton[playerControl="true"] { border-radius: 20px; min-width: 40px; max-width: 40px; min-height: 40px; max-height: 40px; padding: 0; }
QListWidget { background: transparent; border: 0; outline: 0; }
QListWidget#navigation { background: transparent; color: #9aa8a0; padding: 0; }
QListWidget#navigation::item { padding: 0 13px; margin: 2px 0; border-radius: 9px; font-weight: 600; }
QListWidget#navigation::item:hover { background: #151d19; color: #f7faf8; }
QListWidget#navigation::item:selected { background: #1b2520; color: #f7faf8; border-left: 3px solid #24c879; }
QListWidget#navigation::item:focus { outline: none; }
QCheckBox { spacing: 8px; color: #cbd5cf; }
QCheckBox::indicator { width: 17px; height: 17px; border: 1px solid #52675c; border-radius: 4px; background: #101713; }
QCheckBox::indicator:checked { background: #24c879; border-color: #24c879; }
QProgressBar { border: 0; border-radius: 4px; text-align: center; background: #27342d; min-height: 7px; max-height: 7px; color: transparent; }
QProgressBar::chunk { background: #24c879; border-radius: 4px; }
QSlider::groove:horizontal { height: 4px; background: #35443c; border-radius: 2px; }
QSlider::sub-page:horizontal { background: #24c879; border-radius: 2px; }
QSlider::handle:horizontal { background: #f7faf8; width: 12px; height: 12px; margin: -4px 0; border-radius: 6px; }
QLabel[error="true"] { color: #ffb8b8; background: #381d20; border: 1px solid #704047; border-radius: 8px; padding: 8px; }
QTableWidget { background: #111814; alternate-background-color: #151d19; border: 1px solid #2a3831; border-radius: 10px; gridline-color: transparent; outline: 0; }
QTableWidget::item { padding: 8px; border-bottom: 1px solid #202b25; }
QTableWidget::item:selected { background: #20372a; color: #f7faf8; }
QHeaderView::section { background: #1b2520; color: #93a39a; padding: 9px; border: 0; border-bottom: 1px solid #2a3831; font-weight: 700; }
QScrollBar:vertical { background: transparent; width: 10px; margin: 2px; }
QScrollBar::handle:vertical { background: #34463d; border-radius: 5px; min-height: 28px; }
QScrollBar::handle:vertical:hover { background: #4c6256; }
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical { height: 0; }
QStatusBar { background: #101713; border-top: 1px solid #202b25; color: #93a39a; padding-left: 8px; }
QToolTip { background: #1b2520; color: #f7faf8; border: 1px solid #34463d; padding: 5px; }
"""


def apply_theme(app: QApplication, theme: str) -> None:
    selected = theme
    if theme == "system":
        color = app.palette().color(QPalette.ColorRole.Window)
        selected = "dark" if color.lightness() < 128 else "light"
    app.setFont(QFont("Segoe UI", 10))
    app.setStyleSheet(DARK if selected == "dark" else LIGHT)
