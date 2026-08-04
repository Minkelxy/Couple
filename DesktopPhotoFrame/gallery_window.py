"""全屏画廊 + 缩略图网格浏览。

GalleryWindow: 无边框全屏沉浸式查看大图，键盘左右切换、ESC 退出、滚轮缩放。
GalleryGridWindow: 4 列缩略图网格，顶部相册下拉切换，双击全屏查看。
"""
from __future__ import annotations

import time
from pathlib import Path

import app_paths
from PIL import Image
from PySide6.QtCore import (
    QEasingCurve,
    QPropertyAnimation,
    QSize,
    Qt,
    QTimer,
    Signal,
)
from PySide6.QtGui import QAction, QIcon, QPixmap, QWheelEvent
from PySide6.QtWidgets import (
    QComboBox,
    QFrame,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QMainWindow,
    QMenu,
    QMessageBox,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from . import config
from . import image_processor as ip

PINK = "#e65a7a"


def _fit_to_screen(img: Image.Image, max_w: int, max_h: int, zoom: float = 1.0) -> QPixmap:
    """等比缩放到屏幕内（contain），zoom>1 时放大查看细节。"""
    img = img.convert("RGBA")
    w, h = img.size
    scale = min(max_w / w, max_h / h, 1.0) * zoom
    nw, nh = max(1, int(w * scale)), max(1, int(h * scale))
    img = img.resize((nw, nh), Image.LANCZOS)
    return ip.pil_to_pixmap(img)


class GalleryWindow(QMainWindow):
    """全屏画廊窗口。"""

    show_grid_requested = Signal()

    def __init__(self, image_dir: str, start_index: int = 0) -> None:
        super().__init__()
        self.setWindowFlags(
            Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint
        )
        self.setStyleSheet("QMainWindow{background:#000;}")

        self._images: list[Path] = ip.list_images(image_dir)
        self._index = max(0, min(start_index, len(self._images) - 1)) if self._images else 0
        self._zoom = 1.0
        self._fade_anim: QPropertyAnimation | None = None

        screen = self.screen().availableGeometry()
        self.resize(screen.width(), screen.height())
        self.move(screen.topLeft())

        self._build_ui()
        if self._images:
            self._show_current()
        else:
            self._label.setText("相册为空")
            self._label.setAlignment(Qt.AlignCenter)

        # 悬浮层自动隐藏
        self._hide_timer = QTimer(self)
        self._hide_timer.setSingleShot(True)
        self._hide_timer.setInterval(3000)
        self._hide_timer.timeout.connect(self._hide_overlays)
        self._hide_timer.start()

    def _build_ui(self) -> None:
        central = QWidget(self)
        self.setCentralWidget(central)
        layout = QVBoxLayout(central)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        self._label = QLabel(central)
        self._label.setAlignment(Qt.AlignCenter)
        self._label.setStyleSheet("background:#000;")
        layout.addWidget(self._label, 1)

        # 顶部悬浮工具栏
        self._toolbar = QFrame(central)
        self._toolbar.setStyleSheet(
            "QFrame{background:rgba(0,0,0,140);border:none;}"
            "QPushButton{background:rgba(255,255,255,30);color:#fff;border:none;"
            "border-radius:6px;padding:8px 14px;font-size:13px;}"
            "QPushButton:hover{background:rgba(255,255,255,60);}"
        )
        tb_layout = QHBoxLayout(self._toolbar)
        tb_layout.setContentsMargins(16, 10, 16, 10)
        btn_prev = QPushButton("← 上一张")
        btn_next = QPushButton("下一张 →")
        btn_grid = QPushButton("🗂 网格")
        btn_exit = QPushButton("✕ 退出")
        for btn in (btn_prev, btn_next, btn_grid, btn_exit):
            tb_layout.addWidget(btn)
        tb_layout.addStretch(1)
        btn_prev.clicked.connect(self.show_prev)
        btn_next.clicked.connect(self.show_next)
        btn_grid.clicked.connect(self._on_grid)
        btn_exit.clicked.connect(self.close)
        self._toolbar.setParent(central)
        self._toolbar.move(0, 0)
        self._toolbar.setFixedWidth(self.width())

        # 底部状态栏
        self._status = QLabel(central)
        self._status.setStyleSheet(
            "QLabel{background:rgba(0,0,0,140);color:#fff;padding:8px 16px;"
            "font-size:12px;border:none;}"
        )
        self._status.setParent(central)
        self._status.move(0, self.height() - 40)
        self._status.setFixedWidth(self.width())

    def _show_current(self) -> None:
        if not self._images:
            return
        src = self._images[self._index]
        try:
            img = Image.open(src)
            img.load()
        except Exception:
            self._label.setText(f"无法加载：{src.name}")
            return
        pm = _fit_to_screen(img, self.width(), self.height(), self._zoom)
        self._fade_switch(pm)
        self._status.setText(
            f"  {self._index + 1} / {len(self._images)}  ·  {src.name}"
        )

    def _fade_switch(self, pixmap: QPixmap) -> None:
        fade_out = QPropertyAnimation(self, b"windowOpacity", self)
        fade_out.setDuration(120)
        fade_out.setStartValue(self.windowOpacity() or 1.0)
        fade_out.setEndValue(0.0)
        fade_out.finished.connect(lambda: self._apply_pixmap(pixmap))
        fade_out.start()
        self._fade_anim = fade_out

    def _apply_pixmap(self, pixmap: QPixmap) -> None:
        self._label.setPixmap(pixmap)
        fade_in = QPropertyAnimation(self, b"windowOpacity", self)
        fade_in.setDuration(180)
        fade_in.setStartValue(0.0)
        fade_in.setEndValue(1.0)
        fade_in.setEasingCurve(QEasingCurve.InOutSine)
        fade_in.start()
        self._fade_anim = fade_in

    # ---------- 导航 ----------
    def show_next(self) -> None:
        if not self._images:
            return
        self._index = (self._index + 1) % len(self._images)
        self._zoom = 1.0
        self._show_current()

    def show_prev(self) -> None:
        if not self._images:
            return
        self._index = (self._index - 1) % len(self._images)
        self._zoom = 1.0
        self._show_current()

    def _on_grid(self) -> None:
        self.show_grid_requested.emit()
        self.close()

    # ---------- 悬浮层 ----------
    def _show_overlays(self) -> None:
        self._toolbar.show()
        self._status.show()
        self._hide_timer.start()

    def _hide_overlays(self) -> None:
        self._toolbar.hide()
        self._status.hide()

    # ---------- 事件 ----------
    def keyPressEvent(self, e) -> None:
        key = e.key()
        if key in (Qt.Key_Right, Qt.Key_Down, Qt.Key_Space):
            self.show_next()
        elif key in (Qt.Key_Left, Qt.Key_Up):
            self.show_prev()
        elif key == Qt.Key_Escape:
            self.close()
        else:
            super().keyPressEvent(e)

    def wheelEvent(self, e: QWheelEvent) -> None:
        delta = e.angleDelta().y()
        if delta == 0:
            return
        step = 0.1 if delta > 0 else -0.1
        self._zoom = max(1.0, min(3.0, round(self._zoom + step, 2)))
        self._show_current()

    def mouseMoveEvent(self, e) -> None:
        self._show_overlays()
        super().mouseMoveEvent(e)

    def resizeEvent(self, e) -> None:
        self._toolbar.setFixedWidth(self.width())
        self._status.move(0, self.height() - 40)
        self._status.setFixedWidth(self.width())
        super().resizeEvent(e)


class GalleryGridWindow(QMainWindow):
    """缩略图网格浏览窗口。"""

    def __init__(self, hub=None) -> None:
        super().__init__()
        self.setWindowTitle("相册浏览 🖼")
        self.resize(900, 650)
        self.setStyleSheet("QMainWindow{background:#fafafa;}")
        self._gallery_win: GalleryWindow | None = None
        self._hub = hub
        self._build_ui()
        self._populate_albums()
        # 接收对方共享的照片：photo 事件落盘并刷新相册下拉
        if self._hub is not None:
            try:
                self._hub.event_received.connect(self._on_hub_event)
            except (AttributeError, RuntimeError):
                pass

    def _build_ui(self) -> None:
        central = QWidget(self)
        self.setCentralWidget(central)
        layout = QVBoxLayout(central)
        layout.setContentsMargins(16, 14, 16, 14)
        layout.setSpacing(10)

        # 顶部相册选择
        top_row = QHBoxLayout()
        top_row.addWidget(QLabel("相册："))
        self._album_combo = QComboBox()
        self._album_combo.setStyleSheet(
            "QComboBox{padding:6px;border:1px solid #ddd;border-radius:6px;font-size:14px;}"
            "QComboBox::drop-down{border:none;}"
        )
        self._album_combo.currentIndexChanged.connect(self._on_album_changed)
        top_row.addWidget(self._album_combo, 1)
        layout.addLayout(top_row)

        # 网格
        self._grid = QListWidget()
        self._grid.setViewMode(QListWidget.IconMode)
        self._grid.setIconSize(QSize(200, 200))
        self._grid.setResizeMode(QListWidget.Adjust)
        self._grid.setGridSize(QSize(210, 240))
        self._grid.setFlow(QListWidget.LeftToRight)
        self._grid.setWrapping(True)
        self._grid.setSpacing(8)
        self._grid.setStyleSheet(
            "QListWidget{background:#fff;border:1px solid #eee;border-radius:8px;}"
            "QListWidget::item{border-radius:6px;}"
            "QListWidget::item:selected{background:#fdf2f5;}"
        )
        self._grid.itemDoubleClicked.connect(self._on_item_double_clicked)
        # 右键菜单：共享当前相册给对方
        self._grid.setContextMenuPolicy(Qt.CustomContextMenu)
        self._grid.customContextMenuRequested.connect(self._on_grid_context_menu)
        layout.addWidget(self._grid, 1)

    def _populate_albums(self) -> None:
        """填充相册下拉。"""
        self._album_combo.blockSignals(True)
        prev_path = self._album_combo.currentData()
        self._album_combo.clear()
        cfg = config.load()
        cur_dir = cfg.get("image_dir", "")
        # "当前目录"项
        self._album_combo.addItem("当前目录", cur_dir)
        # 已配置相册
        for a in config.list_albums():
            name = a.get("name", a.get("path", ""))
            path = a.get("path", "")
            if path and path != cur_dir:
                self._album_combo.addItem(name, path)
        # 对方共享相册
        for a in config.get_partner_albums():
            name = a.get("name", "对方共享")
            path = a.get("path", "")
            if path and path != cur_dir:
                self._album_combo.addItem(name, path)
        # 恢复之前的选择
        if prev_path is not None:
            idx = self._album_combo.findData(prev_path)
            if idx >= 0:
                self._album_combo.setCurrentIndex(idx)
        self._album_combo.blockSignals(False)
        self._refresh_grid()

    def _on_album_changed(self, _idx: int) -> None:
        self._refresh_grid()

    def _refresh_grid(self) -> None:
        """刷新网格缩略图。"""
        self._grid.clear()
        path = self._album_combo.currentData() or ""
        images = ip.list_images(path)
        if not images:
            item = QListWidgetItem("把照片放进目录：\n" + path)
            item.setFlags(Qt.NoItemFlags)
            item.setTextAlignment(Qt.AlignCenter)
            self._grid.addItem(item)
            return
        for src in images:
            try:
                img = Image.open(src)
                img.load()
                thumb = ip.fit_into(img, 200, 200)
                pm = ip.pil_to_pixmap(thumb)
                item = QListWidgetItem(QIcon(pm), src.name)
                item.setData(Qt.UserRole, str(src))
                self._grid.addItem(item)
            except Exception:
                item = QListWidgetItem("📷 " + src.name)
                self._grid.addItem(item)

    def _on_item_double_clicked(self, item: QListWidgetItem) -> None:
        path_str = item.data(Qt.UserRole)
        if not path_str:
            return
        # 找到双击项的索引
        images = ip.list_images(self._album_combo.currentData() or "")
        try:
            idx = images.index(Path(path_str))
        except ValueError:
            idx = 0
        if self._gallery_win is not None:
            self._gallery_win.close()
        self._gallery_win = GalleryWindow(
            self._album_combo.currentData() or "", start_index=idx
        )
        self._gallery_win.destroyed.connect(lambda *_: setattr(self, "_gallery_win", None))
        self._gallery_win.show()

    # ---------- 共享给对方 ----------
    def _on_grid_context_menu(self, pos) -> None:
        """右键菜单：共享当前相册给对方。"""
        menu = QMenu(self)
        act_share = menu.addAction("共享给对方")
        chosen = menu.exec(self._grid.mapToGlobal(pos))
        if chosen is act_share:
            self._share_current_album()

    def _share_current_album(self) -> None:
        """把当前相册的所有照片逐张通过同步中枢发给对方。"""
        if self._hub is None:
            QMessageBox.information(self, "共享", "同步服务未启动，无法共享。")
            return
        path = self._album_combo.currentData() or ""
        images = ip.list_images(path)
        if not images:
            self.statusBar().showMessage("当前相册没有照片", 3000)
            return
        current_album_name = self._album_combo.currentText()
        total = len(images)
        self.statusBar().showMessage(f"正在共享 {total} 张照片给对方…", 0)
        sent = 0
        for img in images:
            try:
                data = Path(img).read_bytes()
                self._hub.send_event(
                    "photo",
                    {"filename": img.name, "album_name": current_album_name},
                    attachment=data,
                    att_ext=Path(img).suffix,
                )
                sent += 1
            except (OSError, AttributeError):
                continue
        self.statusBar().showMessage(f"已共享 {sent}/{total} 张照片给对方", 5000)
        QMessageBox.information(self, "共享", f"已共享 {sent}/{total} 张照片给对方。")

    # ---------- 接收对方共享 ----------
    def _on_hub_event(
        self, etype: str, meta: dict, content: str, attachment: bytes, att_ext: str
    ) -> None:
        """处理同步中枢事件：photo 类型保存为对方共享照片并刷新下拉。"""
        if etype == "photo":
            handle_partner_event(meta, content, attachment, att_ext)
            self._populate_albums()


def handle_partner_event(
    meta: dict, content: str, attachment: bytes, att_ext: str
) -> None:
    """接收对方共享的照片：保存到 shared_photos 目录并注册为对方共享相册。

    被画廊窗口的事件分发调用（也可由 launcher 路由器直接调用）。
    """
    if not attachment:
        return
    shared_dir = app_paths.DATA_DIR / "shared_photos"
    shared_dir.mkdir(parents=True, exist_ok=True)
    filename = f"{int(time.time())}_{meta.get('filename', 'photo')}"
    (shared_dir / filename).write_bytes(attachment)
    config.add_partner_album_path(str(shared_dir))
