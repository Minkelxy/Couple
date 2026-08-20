"""Shared visual language for the CoupleSuite desktop application."""
from __future__ import annotations

from PySide6.QtGui import QColor, QFont, QFontDatabase, QPalette
from PySide6.QtWidgets import QApplication


def _install_font(app: QApplication) -> None:
    """Choose a CJK-capable UI font when the platform provides one."""
    available = set(QFontDatabase.families())
    for family in (
        "Microsoft YaHei UI",
        "Microsoft YaHei",
        "Noto Sans CJK SC",
        "Noto Sans CJK TC",
        "Noto Sans SC",
        "Droid Sans Fallback",
        "AR PL UMing CN",
        "WenQuanYi Zen Hei",
        "Segoe UI",
    ):
        if family in available:
            app.setFont(QFont(family, 10))
            return
    app.setFont(QFont("Sans Serif", 10))


def apply_theme(app: QApplication) -> None:
    """Install the application palette and shared widget styling."""
    _install_font(app)
    palette = QPalette()
    palette.setColor(QPalette.ColorRole.Window, QColor("#f5f7fa"))
    palette.setColor(QPalette.ColorRole.Base, QColor("#ffffff"))
    palette.setColor(QPalette.ColorRole.AlternateBase, QColor("#f0f3f7"))
    palette.setColor(QPalette.ColorRole.Text, QColor("#263238"))
    palette.setColor(QPalette.ColorRole.WindowText, QColor("#263238"))
    palette.setColor(QPalette.ColorRole.Button, QColor("#ffffff"))
    palette.setColor(QPalette.ColorRole.ButtonText, QColor("#263238"))
    palette.setColor(QPalette.ColorRole.Highlight, QColor("#e85d75"))
    palette.setColor(QPalette.ColorRole.HighlightedText, QColor("#ffffff"))
    palette.setColor(QPalette.ColorRole.PlaceholderText, QColor("#9aa5b1"))
    app.setPalette(palette)
    app.setStyleSheet(
        """
        QWidget { color: #263238; font-size: 13px; }
        QMainWindow, QDialog { background: #f5f7fa; }
        QLabel { background: transparent; }
        QLineEdit, QTextEdit, QPlainTextEdit, QSpinBox, QDoubleSpinBox,
        QComboBox, QDateEdit {
            min-height: 30px; padding: 3px 9px; border: 1px solid #d7dee8;
            border-radius: 6px; background: #ffffff;
            selection-background-color: #e85d75;
        }
        QLineEdit:focus, QTextEdit:focus, QPlainTextEdit:focus,
        QSpinBox:focus, QDoubleSpinBox:focus, QComboBox:focus, QDateEdit:focus {
            border: 1px solid #e85d75;
        }
        QComboBox::drop-down { width: 24px; border: none; }
        QComboBox QAbstractItemView {
            padding: 4px; border: 1px solid #dfe5ec; border-radius: 6px;
            background: #ffffff; selection-background-color: #ffe8ed;
            selection-color: #263238;
        }
        QLineEdit:read-only { background: #eef2f6; color: #5d6b78; }
        QPushButton {
            min-height: 30px; padding: 4px 13px; border: 1px solid #d3dbe5;
            border-radius: 6px; background: #ffffff;
        }
        QPushButton:hover { background: #fff0f3; border-color: #e8a0ad; }
        QPushButton:pressed { background: #fbdde4; }
        QPushButton:disabled {
            color: #aab3bd; background: #edf0f3; border-color: #e1e5ea;
        }
        QToolButton {
            min-height: 28px; padding: 3px 8px; border: 1px solid transparent;
            border-radius: 5px; background: transparent; color: #52616d;
        }
        QToolButton:hover { background: #fff0f3; color: #d84f68; }
        QScrollArea { border: none; background: transparent; }
        QMessageBox, QInputDialog { background: #f5f7fa; }
        QMessageBox QLabel, QInputDialog QLabel { color: #263238; }
        QMessageBox QPushButton, QInputDialog QPushButton {
            min-width: 72px; padding-left: 14px; padding-right: 14px;
        }
        QTextBrowser {
            border: 1px solid #dfe5ec; border-radius: 7px; background: #ffffff;
            selection-background-color: #e85d75;
        }
        QAbstractItemView:focus { outline: none; border-color: #e8a0ad; }
        QSplitter::handle:horizontal { width: 7px; background: #eef2f6; }
        QSplitter::handle:vertical { height: 7px; background: #eef2f6; }
        QSplitter::handle:hover { background: #f1a1af; }
        QHeaderView::section {
            padding: 6px 8px; border: none; border-bottom: 1px solid #dfe5ec;
            background: #f7f9fb; color: #52616d; font-weight: 600;
        }
        QCalendarWidget QWidget { alternate-background-color: #f7f9fb; }
        QCalendarWidget QToolButton {
            min-height: 28px; padding: 3px 8px; color: #52616d;
            background: #ffffff; border: none;
        }
        QCalendarWidget QToolButton:hover { color: #d84f68; background: #fff0f3; }
        QCalendarWidget QMenu { border-radius: 6px; }
        QCalendarWidget QSpinBox {
            min-height: 26px; padding: 2px 6px; border: 1px solid #d7dee8;
            border-radius: 5px; background: #ffffff;
        }
        QCalendarWidget QAbstractItemView {
            selection-background-color: #e85d75; selection-color: #ffffff;
            outline: none;
        }
        QStatusBar {
            min-height: 24px; padding: 2px 8px; border-top: 1px solid #dfe5ec;
            background: #eef2f6; color: #687582;
        }
        QTabWidget::pane {
            border: 1px solid #dfe5ec; border-radius: 8px; background: #ffffff;
            top: -1px;
        }
        QTabBar::tab {
            min-width: 84px; min-height: 30px; padding: 5px 12px;
            color: #687582; background: transparent; border: none;
            border-bottom: 2px solid transparent;
        }
        QTabBar::tab:hover { color: #d84f68; }
        QTabBar::tab:selected {
            color: #d84f68; border-bottom: 2px solid #e85d75; font-weight: 600;
        }
        QGroupBox {
            margin-top: 12px; padding: 14px 10px 10px;
            border: 1px solid #dfe5ec; border-radius: 8px;
            background: #ffffff; font-weight: 600;
        }
        QGroupBox::title {
            subcontrol-origin: margin; left: 12px; padding: 0 6px;
            color: #52616d; background: #f5f7fa;
        }
        QListWidget, QTreeWidget, QTableWidget {
            border: 1px solid #dfe5ec; border-radius: 7px; background: #ffffff;
            alternate-background-color: #f7f9fb;
        }
        QListWidget::item, QTreeWidget::item { padding: 6px; border-radius: 4px; }
        QListWidget::item:hover, QTreeWidget::item:hover { background: #f7f9fb; }
        QListWidget::item:selected, QTreeWidget::item:selected {
            color: #263238; background: #ffe8ed;
        }
        QCheckBox, QRadioButton { spacing: 7px; min-height: 26px; }
        QSlider::groove:horizontal {
            height: 6px; border-radius: 3px; background: #e2e8ee;
        }
        QSlider::handle:horizontal {
            width: 16px; height: 16px; margin: -5px 0;
            border-radius: 8px; background: #e85d75; border: 2px solid #ffffff;
        }
        QSlider::sub-page:horizontal { background: #f1a1af; border-radius: 3px; }
        QProgressBar {
            min-height: 8px; border: none; border-radius: 4px;
            background: #e8edf2; text-align: center;
        }
        QProgressBar::chunk { border-radius: 4px; background: #e85d75; }
        QMenu {
            padding: 6px; border: 1px solid #dfe5ec; border-radius: 7px;
            background: #ffffff;
        }
        QMenu::item { padding: 7px 28px 7px 12px; border-radius: 4px; }
        QMenu::item:selected { color: #263238; background: #ffe8ed; }
        QMenu::item:disabled { color: #9aa5b1; font-weight: 600; }
        QMenu::separator { height: 1px; margin: 5px 8px; background: #dfe5ec; }
        QToolTip {
            padding: 5px 8px; color: #ffffff; border: none;
            border-radius: 4px; background: #263238;
        }
        QScrollBar:vertical {
            width: 10px; margin: 2px; border: none; background: transparent;
        }
        QScrollBar:horizontal {
            height: 10px; margin: 2px; border: none; background: transparent;
        }
        QScrollBar::handle:vertical {
            min-height: 28px; border-radius: 5px; background: #c7d0da;
        }
        QScrollBar::handle:horizontal {
            min-width: 28px; border-radius: 5px; background: #c7d0da;
        }
        QScrollBar::handle:vertical:hover { background: #aebbc8; }
        QScrollBar::handle:horizontal:hover { background: #aebbc8; }
        QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical,
        QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical {
            height: 0; background: transparent;
        }
        QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal,
        QScrollBar::add-page:horizontal, QScrollBar::sub-page:horizontal {
            width: 0; background: transparent;
        }
        """
    )
