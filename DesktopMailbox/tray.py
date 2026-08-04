"""系统托盘：写信 / 收件箱 / 退出；显示未读数。"""
from __future__ import annotations

from PySide6.QtCore import QObject, Signal
from PySide6.QtGui import QAction, QIcon, QPainter, QPen, QColor, QPolygonF, QPixmap, Qt
from PySide6.QtCore import QPointF
from PySide6.QtWidgets import QMenu, QSystemTrayIcon


def _make_envelope_icon(size: int = 64) -> QIcon:
    """无图标文件时，用 QPainter 画一个信封。"""
    pm = QPixmap(size, size)
    pm.fill(Qt.transparent)
    p = QPainter(pm)
    p.setRenderHint(QPainter.Antialiasing, True)
    # 信封主体
    p.setPen(Qt.NoPen)
    p.setBrush(Qt.white)
    p.drawRect(int(size * 0.1), int(size * 0.25), int(size * 0.8), int(size * 0.55))
    # 红色边
    p.setPen(QPen(QColor(230, 90, 122), 3))
    p.setBrush(Qt.NoBrush)
    p.drawRect(int(size * 0.1), int(size * 0.25), int(size * 0.8), int(size * 0.55))
    # V 形信封盖
    p.setPen(QPen(QColor(230, 90, 122), 3))
    poly = QPolygonF([
        QPointF(size * 0.1, size * 0.27),
        QPointF(size * 0.5, size * 0.55),
        QPointF(size * 0.9, size * 0.27),
    ])
    p.drawPolyline(poly)
    p.end()
    return QIcon(pm)


class TrayController(QObject):
    compose_requested = Signal()
    inbox_requested = Signal()
    quit_requested = Signal()

    def __init__(self) -> None:
        super().__init__()
        self._tray = QSystemTrayIcon(_make_envelope_icon())
        self._tray.setToolTip("信箱")
        self._build_menu()
        self._tray.activated.connect(self._on_activated)
        self._tray.show()

    def _build_menu(self) -> None:
        menu = QMenu()

        act_compose = QAction("✍ 写信…", menu)
        act_compose.triggered.connect(self.compose_requested)
        menu.addAction(act_compose)

        act_inbox = QAction("📬 信件箱…", menu)
        act_inbox.triggered.connect(self.inbox_requested)
        menu.addAction(act_inbox)

        menu.addSeparator()

        act_quit = QAction("退出", menu)
        act_quit.triggered.connect(self.quit_requested)
        menu.addAction(act_quit)

        self._menu = menu
        self._tray.setContextMenu(menu)

    def _on_activated(self, reason) -> None:
        if reason == QSystemTrayIcon.DoubleClick:
            self.inbox_requested.emit()

    def show_toast(self, title: str, msg: str) -> None:
        self._tray.showMessage(title, msg, QSystemTrayIcon.Information, 2500)

    def set_unread_count(self, n: int) -> None:
        self._tray.setToolTip(
            f"信箱 · {n} 封未读" if n else "信箱"
        )
