from __future__ import annotations

from PySide6.QtGui import QFont, QPalette
from PySide6.QtWidgets import QApplication


LIGHT = """
QWidget { color: #17221c; background: #f4f7f5; font-family: "Segoe UI"; font-size: 14px; }
QMainWindow, QWidget#appShell, QStackedWidget { background: #f4f7f5; }
QFrame#sidebar { background: #ffffff; border-right: 1px solid #dce5df; }
QFrame#card, QFrame#player, QFrame#settingsCard, QFrame#profileCard { background: #ffffff; border: 1px solid #dce5df; border-radius: 12px; }
QFrame#card QLabel, QFrame#card QCheckBox, QFrame#player QLabel, QFrame#settingsCard QLabel, QFrame#profileCard QLabel { background: transparent; border: 0; }
QLabel[heading="true"] { color: #101814; font-size: 28px; font-weight: 800; }
QLabel[subheading="true"] { color: #101814; font-size: 18px; font-weight: 700; }
QLabel[eyebrow="true"] { color: #168c52; font-size: 11px; font-weight: 800; }
QLabel[muted="true"] { color: #65736b; }
QLabel[accent="true"] { color: #168c52; }
QLineEdit, QComboBox, QSpinBox { background: #ffffff; border: 1px solid #bfcac3; border-radius: 9px; padding: 9px 11px; min-height: 20px; }
QLineEdit:focus, QComboBox:focus, QSpinBox:focus { border: 2px solid #20b86b; }
QPushButton { background: #20b86b; color: #06140c; border: 0; border-radius: 9px; padding: 9px 15px; font-weight: 700; min-height: 20px; }
QPushButton:hover { background: #36ce80; } QPushButton:pressed { background: #169855; }
QPushButton:disabled { background: #c8d1cb; color: #7c8881; }
QPushButton[secondary="true"] { background: #edf2ef; color: #27342d; border: 1px solid #d6dfd9; }
QPushButton[secondary="true"]:hover { background: #e2eae5; border-color: #b8c8be; }
QPushButton[playerControl="true"] { border-radius: 18px; min-width: 36px; max-width: 36px; min-height: 36px; max-height: 36px; padding: 0; }
QListWidget { background: transparent; border: 0; outline: 0; }
QListWidget#navigation { background: transparent; color: #58675e; padding: 4px 10px; }
QListWidget#navigation::item { padding: 11px 14px; margin: 2px 0; border-radius: 8px; font-weight: 600; }
QListWidget#navigation::item:hover { background: #f0f5f2; color: #17221c; }
QListWidget#navigation::item:selected { background: #e5f6ec; color: #137a48; border-left: 3px solid #20b86b; }
QProgressBar { border: 0; border-radius: 4px; text-align: center; background: #dfe8e2; min-height: 7px; max-height: 7px; color: transparent; }
QProgressBar::chunk { background: #20b86b; border-radius: 4px; }
QSlider::groove:horizontal { height: 4px; background: #d8e1db; border-radius: 2px; }
QSlider::sub-page:horizontal { background: #20b86b; border-radius: 2px; }
QSlider::handle:horizontal { background: #20b86b; width: 12px; height: 12px; margin: -4px 0; border-radius: 6px; }
QLabel[error="true"] { color: #a62c2c; background: #fff0f0; border: 1px solid #efb4b4; border-radius: 8px; padding: 8px; }
QTableWidget { background: #ffffff; alternate-background-color: #f5f8f6; border: 1px solid #dce5df; border-radius: 10px; gridline-color: transparent; outline: 0; }
QTableWidget::item { padding: 8px; border-bottom: 1px solid #edf1ee; }
QTableWidget::item:selected { background: #dcf5e7; color: #102017; }
QHeaderView::section { background: #edf2ef; color: #536159; padding: 9px; border: 0; border-bottom: 1px solid #dce5df; font-weight: 700; }
QStatusBar { background: #ffffff; border-top: 1px solid #dce5df; color: #65736b; }
"""

DARK = """
QWidget { color: #f5f8f6; background: #090d0b; font-family: "Segoe UI"; font-size: 14px; }
QMainWindow, QWidget#appShell, QStackedWidget { background: #090d0b; }
QFrame#sidebar { background: #0f1512; border-right: 1px solid #202b25; }
QFrame#card, QFrame#player, QFrame#settingsCard, QFrame#profileCard { background: #151d19; border: 1px solid #2a3831; border-radius: 12px; }
QFrame#card QLabel, QFrame#card QCheckBox, QFrame#player QLabel, QFrame#settingsCard QLabel, QFrame#profileCard QLabel { background: transparent; border: 0; }
QFrame#card:hover { border-color: #3c5146; background: #18231d; }
QLabel[heading="true"] { color: #f7faf8; font-size: 28px; font-weight: 800; }
QLabel[subheading="true"] { color: #f7faf8; font-size: 18px; font-weight: 700; }
QLabel[eyebrow="true"] { color: #24c879; font-size: 11px; font-weight: 800; }
QLabel[muted="true"] { color: #93a39a; }
QLabel[accent="true"] { color: #24c879; }
QLineEdit, QComboBox, QSpinBox { background: #151d19; color: #f7faf8; border: 1px solid #34463d; border-radius: 9px; padding: 9px 11px; min-height: 20px; selection-background-color: #24c879; selection-color: #04140c; }
QLineEdit:hover, QComboBox:hover, QSpinBox:hover { border-color: #50665a; }
QLineEdit:focus, QComboBox:focus, QSpinBox:focus { border: 2px solid #24c879; }
QComboBox QAbstractItemView { background: #151d19; color: #f7faf8; border: 1px solid #34463d; selection-background-color: #24372d; }
QPushButton { background: #24c879; color: #04140c; border: 0; border-radius: 9px; padding: 9px 15px; font-weight: 800; min-height: 20px; }
QPushButton:hover { background: #4ade93; } QPushButton:pressed { background: #1eab67; }
QPushButton:disabled { background: #29342e; color: #6e7b74; }
QPushButton[secondary="true"] { background: #1b2520; color: #e9efeb; border: 1px solid #34463d; }
QPushButton[secondary="true"]:hover { background: #243129; border-color: #52675c; }
QPushButton[playerControl="true"] { border-radius: 18px; min-width: 36px; max-width: 36px; min-height: 36px; max-height: 36px; padding: 0; }
QListWidget { background: transparent; border: 0; outline: 0; }
QListWidget#navigation { background: transparent; color: #93a39a; padding: 4px 10px; }
QListWidget#navigation::item { padding: 11px 14px; margin: 2px 0; border-radius: 8px; font-weight: 600; }
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
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical { height: 0; }
QStatusBar { background: #0f1512; border-top: 1px solid #202b25; color: #93a39a; }
QToolTip { background: #1b2520; color: #f7faf8; border: 1px solid #34463d; padding: 5px; }
"""


def apply_theme(app: QApplication, theme: str) -> None:
    selected = theme
    if theme == "system":
        color = app.palette().color(QPalette.ColorRole.Window)
        selected = "dark" if color.lightness() < 128 else "light"
    app.setFont(QFont("Segoe UI", 10))
    app.setStyleSheet(DARK if selected == "dark" else LIGHT)
