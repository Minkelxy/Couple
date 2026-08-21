"""系统托盘：下一张/上一张/暂停/放大/边框/水印/选目录/退出。"""
from __future__ import annotations

from PySide6.QtCore import QObject, QSize, Qt, Signal
from PySide6.QtGui import (
    QAction,
    QColor,
    QFont,
    QIcon,
    QMouseEvent,
    QPainter,
    QPen,
    QPixmap,
)
from PySide6.QtWidgets import (
    QApplication,
    QFileDialog,
    QMenu,
    QSystemTrayIcon,
)

from . import config


def _make_heart_icon(size: int = 64) -> QIcon:
    """没有图标文件时，用 QPainter 画一个粉色爱心。"""
    pm = QPixmap(size, size)
    pm.fill(Qt.transparent)
    p = QPainter(pm)
    p.setRenderHint(QPainter.Antialiasing, True)
    p.setPen(Qt.NoPen)
    p.setBrush(QColor(236, 90, 122))
    # 用两个圆 + 一个三角形拼爱心
    r = size / 4.0
    cx, cy = size / 2.0, size / 2.0
    p.drawEllipse(int(cx - r * 0.55), int(cy - r * 0.45), int(r), int(r))
    p.drawEllipse(int(cx - r * 0.05), int(cy - r * 0.45), int(r), int(r))
    from PySide6.QtGui import QPolygonF
    from PySide6.QtCore import QPointF
    tri = QPolygonF([
        QPointF(cx - r * 1.05, cy - r * 0.05),
        QPointF(cx + r * 1.05, cy - r * 0.05),
        QPointF(cx, cy + r * 1.15),
    ])
    p.drawPolygon(tri)
    p.end()
    return QIcon(pm)


class TrayController(QObject):
    """托盘与窗口之间的中介：避免窗口反向依赖托盘。"""

    next_requested = Signal()
    prev_requested = Signal()
    pause_toggled = Signal()
    zoom_toggled = Signal()
    polaroid_toggled = Signal()
    watermark_toggled = Signal()
    ken_burns_toggled = Signal()
    shuffle_requested = Signal()
    image_dir_changed = Signal(str)
    quit_requested = Signal()

    def __init__(self, window) -> None:
        super().__init__()
        self._window = window
        self._tray = QSystemTrayIcon(_make_heart_icon())
        self._tray.setToolTip("桌面相册")
        self._build_menu()
        self._tray.activated.connect(self._on_activated)
        window.status_message.connect(self._show_toast)
        self._tray.show()

    def _build_menu(self) -> None:
        menu = QMenu()

        self._act_next = QAction("下一张  →", menu)
        self._act_next.triggered.connect(self.next_requested)
        menu.addAction(self._act_next)

        self._act_prev = QAction("上一张  ←", menu)
        self._act_prev.triggered.connect(self.prev_requested)
        menu.addAction(self._act_prev)

        self._act_shuffle = QAction("随机一张", menu)
        self._act_shuffle.triggered.connect(self.shuffle_requested)
        menu.addAction(self._act_shuffle)

        menu.addSeparator()

        self._act_pause = QAction("暂停", menu)
        self._act_pause.triggered.connect(self._on_pause)
        menu.addAction(self._act_pause)

        self._act_zoom = QAction("放大/缩小  (双击)", menu)
        self._act_zoom.triggered.connect(self.zoom_toggled)
        menu.addAction(self._act_zoom)

        menu.addSeparator()

        self._act_polaroid = QAction("拍立得边框", menu)
        self._act_polaroid.setCheckable(True)
        self._act_polaroid.setChecked(config.load()["polaroid_frame"])
        self._act_polaroid.triggered.connect(self._on_polaroid)
        menu.addAction(self._act_polaroid)

        self._act_watermark = QAction("日期水印", menu)
        self._act_watermark.setCheckable(True)
        self._act_watermark.setChecked(config.load()["show_watermark"])
        self._act_watermark.triggered.connect(self._on_watermark)
        menu.addAction(self._act_watermark)

        self._act_kenburns = QAction("Ken Burns 动画", menu)
        self._act_kenburns.setCheckable(True)
        self._act_kenburns.setChecked(config.load().get("ken_burns", True))
        self._act_kenburns.triggered.connect(self._on_ken_burns)
        menu.addAction(self._act_kenburns)

        menu.addSeparator()

        self._act_dir = QAction("选择图片目录…", menu)
        self._act_dir.triggered.connect(self._choose_dir)
        menu.addAction(self._act_dir)

        self._act_quit = QAction("退出", menu)
        self._act_quit.triggered.connect(self.quit_requested.emit)
        menu.addAction(self._act_quit)

        self._menu = menu
        self._tray.setContextMenu(menu)

    # ---------- 事件处理 ----------

    def _on_activated(self, reason) -> None:
        # 双击托盘：切换窗口可见
        if reason == QSystemTrayIcon.DoubleClick:
            w = self._window
            if w.isVisible():
                w.hide()
            else:
                w.show()
                w.raise_()

    def _on_pause(self) -> None:
        paused = self._window.toggle_pause()
        self._act_pause.setText("继续" if paused else "暂停")

    def _on_polaroid(self) -> None:
        # 让窗口真正执行切换并更新状态
        self._window.toggle_polaroid()

    def _on_watermark(self) -> None:
        self._window.toggle_watermark()

    def _on_ken_burns(self) -> None:
        self._window.toggle_ken_burns()

    def _choose_dir(self) -> None:
        cur = config.load()["image_dir"]
        path = QFileDialog.getExistingDirectory(
            self._window, "选择图片目录", cur
        )
        if path:
            self.image_dir_changed.emit(path)
            self._window.set_image_dir(path)

    def _show_toast(self, msg: str) -> None:
        self._tray.showMessage("桌面相册", msg, QSystemTrayIcon.Information, 1500)

    # 同步菜单勾选状态（窗口内切换后调用）
    def sync_polaroid(self, on: bool) -> None:
        self._act_polaroid.setChecked(on)

    def sync_watermark(self, on: bool) -> None:
        self._act_watermark.setChecked(on)

    def sync_ken_burns(self, on: bool) -> None:
        self._act_kenburns.setChecked(on)

    def update_pause_text(self, paused: bool) -> None:
        self._act_pause.setText("继续" if paused else "暂停")
