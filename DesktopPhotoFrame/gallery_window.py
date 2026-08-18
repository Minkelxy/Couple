"""全屏画廊 + 缩略图网格浏览。

GalleryWindow: 无边框全屏沉浸式查看大图，键盘左右切换、ESC 退出、滚轮缩放。
GalleryGridWindow: 4 列缩略图网格，顶部相册下拉切换，双击全屏查看。
"""
from __future__ import annotations

import time
import random
from pathlib import Path

import app_paths
from PIL import Image, ImageEnhance, ImageOps
from PySide6.QtCore import (
    QEasingCurve,
    QObject,
    QPropertyAnimation,
    QSize,
    Qt,
    QThread,
    QTimer,
    Signal,
)
from PySide6.QtGui import QAction, QIcon, QPixmap, QWheelEvent
from PySide6.QtWidgets import (
    QComboBox,
    QCheckBox,
    QFrame,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QMainWindow,
    QMenu,
    QMessageBox,
    QProgressBar,
    QPushButton,
    QLineEdit,
    QVBoxLayout,
    QWidget,
)

from common_utils import (
    atomic_write_bytes,
    check_attachment_size,
    log_exception,
    log_warning,
    safe_filename,
)

from . import config
from . import image_processor as ip

PINK = "#e65a7a"


def _apply_gallery_effect(img: Image.Image, mode: str) -> Image.Image:
    """Apply a lightweight preview effect without changing the source file."""
    img = img.convert("RGBA")
    if mode == "mono":
        return ImageOps.grayscale(img).convert("RGBA")
    if mode == "warm":
        img = ImageEnhance.Color(img).enhance(1.12)
        img = ImageEnhance.Contrast(img).enhance(1.06)
        overlay = Image.new("RGBA", img.size, (255, 170, 80, 34))
        return Image.alpha_composite(img, overlay)
    return img


def _stop_anim(anim: QPropertyAnimation | None) -> None:
    if anim is not None:
        try:
            anim.stop()
        except RuntimeError:
            pass


def _fit_to_screen(img: Image.Image, max_w: int, max_h: int, zoom: float = 1.0) -> QPixmap:
    """cover 模式：填满屏幕并居中裁剪，无黑边。zoom>1 时进一步放大查看细节。

    用 max(scale_w, scale_h) 保证两个维度都 ≥ 屏幕尺寸，再居中裁剪到屏幕大小。
    小图也会被放大填满（原 contain 模式 min(..., 1.0) 导致小图周围大黑边）。
    """
    img = img.convert("RGBA")
    w, h = img.size
    tw, th = max(1, int(max_w)), max(1, int(max_h))
    scale = max(tw / w, th / h) * zoom
    nw, nh = max(1, int(w * scale)), max(1, int(h * scale))
    img = img.resize((nw, nh), Image.LANCZOS)
    # 居中裁剪到 tw × th
    left = max(0, (nw - tw) // 2)
    top = max(0, (nh - th) // 2)
    img = img.crop((left, top, left + tw, top + th))
    return ip.pil_to_pixmap(img)


class GalleryWindow(QMainWindow):
    """全屏画廊窗口。"""

    show_grid_requested = Signal()

    def __init__(self, image_dir: str, start_index: int = 0, interval_sec: int = 5) -> None:
        super().__init__()
        self.setWindowFlags(
            Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint
        )
        self.setStyleSheet("QMainWindow{background:#000;}")

        self._images: list[Path] = ip.list_images(image_dir)
        self._index = max(0, min(start_index, len(self._images) - 1)) if self._images else 0
        self._zoom = 1.0
        self._effect_mode = "normal"
        self._fade_anim: QPropertyAnimation | None = None
        # 自动播放（幻灯片）
        self._auto_play = False
        self._auto_timer = QTimer(self)
        self._auto_timer.setTimerType(Qt.CoarseTimer)
        self._auto_timer.setInterval(max(3, int(interval_sec)) * 1000)
        self._auto_timer.timeout.connect(self.show_next)
        # 信息浮层引用（按需创建）
        self._info_label: QLabel | None = None

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
        btn_effect = QPushButton("Effect: Normal")
        btn_prev = QPushButton("← 上一张")
        btn_play = QPushButton("▶ 自动播放")
        btn_next = QPushButton("下一张 →")
        btn_info = QPushButton("ℹ 信息")
        btn_grid = QPushButton("🗂 网格")
        btn_exit = QPushButton("✕ 退出")
        for btn in (btn_prev, btn_play, btn_next, btn_info, btn_effect, btn_grid, btn_exit):
            tb_layout.addWidget(btn)
        tb_layout.addStretch(1)
        btn_prev.clicked.connect(self.show_prev)
        btn_play.clicked.connect(self._toggle_auto_play)
        btn_next.clicked.connect(self.show_next)
        btn_info.clicked.connect(self._toggle_info)
        btn_effect.clicked.connect(self._cycle_effect)
        btn_grid.clicked.connect(self._on_grid)
        btn_exit.clicked.connect(self.close)
        self._btn_play = btn_play
        self._btn_effect = btn_effect
        self._toolbar.setParent(central)
        self._toolbar.move(0, 0)
        self._toolbar.setFixedWidth(self.width())

        # 信息浮层（左上角，默认隐藏）
        self._info_label = QLabel(central)
        self._info_label.setStyleSheet(
            "QLabel{background:rgba(0,0,0,180);color:#fff;padding:12px 16px;"
            "font-size:13px;border-radius:8px;}"
        )
        self._info_label.setParent(central)
        self._info_label.move(16, 60)
        self._info_label.hide()

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
            with Image.open(src) as src_img:
                src_img.load()
                img = _apply_gallery_effect(
                    ImageOps.exif_transpose(src_img).copy(), self._effect_mode
                )
        except Exception:
            log_exception("画廊加载图片失败: %s", src)
            self._label.setText(f"无法加载：{src.name}")
            return
        pm = _fit_to_screen(img, self.width(), self.height(), self._zoom)
        self._fade_switch(pm)
        self._status.setText(
            f"  {self._index + 1} / {len(self._images)}  ·  {src.name}"
        )

    def _fade_switch(self, pixmap: QPixmap) -> None:
        _stop_anim(self._fade_anim)
        fade_out = QPropertyAnimation(self, b"windowOpacity", self)
        fade_out.setDuration(120)
        fade_out.setStartValue(self.windowOpacity() or 1.0)
        fade_out.setEndValue(0.0)
        fade_out.finished.connect(lambda: self._apply_pixmap(pixmap))
        fade_out.start()
        self._fade_anim = fade_out

    def _apply_pixmap(self, pixmap: QPixmap) -> None:
        self._label.setPixmap(pixmap)
        _stop_anim(self._fade_anim)
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
        # 切图时隐藏信息浮层（避免显示上一张的 EXIF）
        if self._info_label is not None and self._info_label.isVisible():
            self._info_label.hide()
        self._index = (self._index + 1) % len(self._images)
        self._zoom = 1.0
        self._show_current()

    def show_prev(self) -> None:
        if not self._images:
            return
        if self._info_label is not None and self._info_label.isVisible():
            self._info_label.hide()
        self._index = (self._index - 1) % len(self._images)
        self._zoom = 1.0
        self._show_current()

    def _on_grid(self) -> None:
        self.show_grid_requested.emit()
        self.close()

    # ---------- 自动播放 ----------
    def _toggle_auto_play(self) -> None:
        self._auto_play = not self._auto_play
        if self._auto_play:
            self._auto_timer.start()
            self._btn_play.setText("⏸ 停止")
        else:
            self._auto_timer.stop()
            self._btn_play.setText("▶ 自动播放")

    # ---------- 信息浮层 ----------
    def _cycle_effect(self) -> None:
        modes = ("normal", "warm", "mono")
        self._effect_mode = modes[(modes.index(self._effect_mode) + 1) % len(modes)]
        labels = {"normal": "Effect: Normal", "warm": "Effect: Warm", "mono": "Effect: Mono"}
        self._btn_effect.setText(labels[self._effect_mode])
        self._show_current()

    def _toggle_info(self) -> None:
        if self._info_label is None:
            return
        if self._info_label.isVisible():
            self._info_label.hide()
            return
        if not self._images:
            return
        src = self._images[self._index]
        info = ip.read_exif_details(src)
        if not info:
            self._info_label.setText(f"📷 {src.name}\n无 EXIF 信息")
        else:
            lines = [f"📷 {src.name}"]
            lines.extend(f"{k}：{v}" for k, v in info.items())
            self._info_label.setText("\n".join(lines))
        self._info_label.adjustSize()
        self._info_label.show()
        # 5 秒后自动隐藏
        QTimer.singleShot(5000, self._info_label.hide)

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

    def closeEvent(self, e) -> None:
        # 关闭时停止自动播放定时器
        if hasattr(self, "_auto_timer"):
            self._auto_timer.stop()
        super().closeEvent(e)


class _ThumbWorker(QThread):
    """后台生成缩略图，逐张 emit 结果，避免主线程大相册卡顿。

    主线程 _refresh_grid 先放占位项，worker 每生成一张就 emit (index, icon|None)。
    worker 在新一次刷新开始时会被请求停止（isInterruptionRequested）。
    """

    thumb_ready = Signal(int, object)  # (index, QPixmap) 或 (index, None) 表示失败

    def __init__(self, images: list[Path]) -> None:
        super().__init__()
        # 复制列表，避免外部修改影响遍历
        self._images = list(images)

    def run(self) -> None:
        for i, src in enumerate(self._images):
            if self.isInterruptionRequested():
                return
            pm: QPixmap | None = None
            try:
                with Image.open(src) as src_img:
                    src_img.load()
                    thumb = ip.fit_into(ImageOps.exif_transpose(src_img).copy(), 200, 200)
                pm = ip.pil_to_pixmap(thumb)
            except Exception:
                log_exception("生成缩略图失败: %s", src)
                pm = None
            if self.isInterruptionRequested():
                return
            self.thumb_ready.emit(i, pm)


class _ShareWorker(QThread):
    """后台逐张发送共享照片，避免大相册阻塞 UI。

    读取照片字节 + send_event 都在子线程；send_event 内部已是异步发送。
    """

    progress = Signal(int, int)  # (sent, total)
    finished_all = Signal(int, int)  # (sent, total)

    def __init__(self, hub, images: list[Path], album_name: str) -> None:
        super().__init__()
        self._hub = hub
        self._images = list(images)
        self._album_name = album_name

    def run(self) -> None:
        total = len(self._images)
        sent = 0
        for i, img in enumerate(self._images):
            if self.isInterruptionRequested():
                break
            try:
                data = Path(img).read_bytes()
                # 大小校验：超过上限的图片跳过并发警告
                err = check_attachment_size(data)
                if err is not None:
                    log_warning("跳过共享 %s: %s", img.name, err)
                else:
                    self._hub.send_event(
                        "photo",
                        {"filename": img.name, "album_name": self._album_name},
                        attachment=data,
                        att_ext=Path(img).suffix,
                        silent=True,
                    )
                    sent += 1
            except (OSError, AttributeError):
                log_exception("读取共享照片失败: %s", img)
                continue
            self.progress.emit(sent, total)
        self.finished_all.emit(sent, total)


class GalleryGridWindow(QMainWindow):
    """缩略图网格浏览窗口。"""

    def __init__(self, hub=None) -> None:
        super().__init__()
        self.setWindowTitle("相册浏览 🖼")
        self.resize(900, 650)
        self.setStyleSheet("QMainWindow{background:#fafafa;}")
        self._gallery_win: GalleryWindow | None = None
        self._hub = hub
        # 后台 worker 引用（用于生命周期管理 + 防重复）
        self._thumb_worker: _ThumbWorker | None = None
        self._share_worker: _ShareWorker | None = None
        # 当前网格的图片列表（与 thumb index 对齐）
        self._grid_images: list[Path] = []
        self._search_text = ""
        self._favorites_only = False
        self._sort_mode = "name"
        # 保留 _hub_event_conn 字段：用于向后兼容（当前版本事件由 launcher
        # 统一路由，窗口不再自行订阅 event_received，避免同一张照片被重复
        # 处理两次——launcher.on_event_received 中已经调用了 handle_photo_partner_event）。
        self._hub_event_conn = None
        self._build_ui()
        self._populate_albums()

    def set_hub(self, hub) -> None:
        """设置变更时热更新同步引用。
        事件由 launcher 统一路由分发，此处不再自行订阅 event_received，
        避免 photo 事件被重复处理两次（重复落盘同一张照片）。
        """
        if self._hub is not None and self._hub_event_conn is not None:
            try:
                self._hub.event_received.disconnect(self._hub_event_conn)
            except (AttributeError, RuntimeError, TypeError):
                pass
            self._hub_event_conn = None
        self._hub = hub

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
        self._search = QLineEdit()
        self._search.setPlaceholderText("Search photos")
        self._search.setClearButtonEnabled(True)
        self._search.setMaximumWidth(220)
        self._search.textChanged.connect(self._on_search_changed)
        top_row.addWidget(self._search)
        self._sort_combo = QComboBox()
        self._sort_combo.addItem("Name", "name")
        self._sort_combo.addItem("Newest", "newest")
        self._sort_combo.addItem("Oldest", "oldest")
        self._sort_combo.addItem("Random", "random")
        self._sort_combo.currentIndexChanged.connect(self._on_sort_changed)
        top_row.addWidget(self._sort_combo)
        self._favorites_check = QCheckBox("Favorites")
        self._favorites_check.toggled.connect(self._on_favorites_changed)
        top_row.addWidget(self._favorites_check)
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

    def _on_search_changed(self, text: str) -> None:
        self._search_text = text.strip().casefold()
        self._refresh_grid()

    def _on_sort_changed(self, _idx: int) -> None:
        self._sort_mode = self._sort_combo.currentData() or "name"
        self._refresh_grid()

    def _on_favorites_changed(self, checked: bool) -> None:
        self._favorites_only = checked
        self._refresh_grid()

    def _stop_thumb_worker(self) -> None:
        """请求停止并清理旧 thumb worker。"""
        if self._thumb_worker is not None:
            try:
                self._thumb_worker.requestInterruption()
                # 断开信号，避免旧 worker 在切换相册后仍 emit 旧索引结果到新网格
                self._thumb_worker.thumb_ready.disconnect(self._on_thumb_ready)
                # 不强行 quit/wait：worker 会自行检测并退出，由 deleteLater 清理
                self._thumb_worker.finished.connect(self._thumb_worker.deleteLater)
            except RuntimeError:
                pass
            self._thumb_worker = None

    def _refresh_grid(self) -> None:
        """刷新网格缩略图：先放占位项，再让后台 worker 填充图标。"""
        self._stop_thumb_worker()
        self._grid.clear()
        path = self._album_combo.currentData() or ""
        images = ip.list_images(path)
        if self._search_text:
            images = [img for img in images if self._search_text in img.name.casefold()]
        if self._favorites_only:
            favorites = set(config.list_favorites())
            images = [img for img in images if str(img) in favorites]
        if self._sort_mode == "newest":
            images.sort(key=lambda img: img.stat().st_mtime, reverse=True)
        elif self._sort_mode == "oldest":
            images.sort(key=lambda img: img.stat().st_mtime)
        elif self._sort_mode == "random":
            random.shuffle(images)
        self._grid_images = images
        if not images:
            item = QListWidgetItem("📭 把照片放到这个目录就会显示在这里\n" + path)
            item.setFlags(Qt.NoItemFlags)
            item.setTextAlignment(Qt.AlignCenter)
            self._grid.addItem(item)
            return
        # 先放占位项（无图标、显示文件名），保持位置与 images 索引对齐
        for src in images:
            it = QListWidgetItem("📷 " + src.name)
            it.setData(Qt.UserRole, str(src))
            self._grid.addItem(it)
        # 启动后台 worker 逐张生成缩略图
        worker = _ThumbWorker(images)
        worker.thumb_ready.connect(self._on_thumb_ready)
        worker.finished.connect(worker.deleteLater)
        self._thumb_worker = worker
        worker.start()

    def _on_thumb_ready(self, index: int, pm: object) -> None:
        """worker 每生成一张缩略图回调：更新对应项图标。"""
        # worker 可能在切换相册后还在 emit 旧结果，校验 index 范围
        if index < 0 or index >= self._grid.count():
            return
        if self._thumb_worker is None:
            return
        item = self._grid.item(index)
        if item is None:
            return
        if pm is not None and not pm.isNull():
            item.setIcon(QIcon(pm))
            # 去掉 "📷 " 前缀，只留文件名
            name = self._grid_images[index].name if index < len(self._grid_images) else item.text()
            item.setText(name)

    def _on_item_double_clicked(self, item: QListWidgetItem) -> None:
        path_str = item.data(Qt.UserRole)
        if not path_str:
            return
        # 找到双击项的索引（直接用已缓存的列表，避免重复枚举目录）
        try:
            idx = self._grid_images.index(Path(path_str))
        except ValueError:
            idx = 0
        if self._gallery_win is not None:
            self._gallery_win.close()
        self._gallery_win = GalleryWindow(
            self._album_combo.currentData() or "",
            start_index=idx,
            interval_sec=config.load().get("interval_sec", 5),
        )
        self._gallery_win.destroyed.connect(lambda *_: setattr(self, "_gallery_win", None))
        self._gallery_win.show()

    # ---------- 共享给对方 ----------
    def _on_grid_context_menu(self, pos) -> None:
        """右键菜单：共享当前相册给对方。"""
        menu = QMenu(self)
        item = self._grid.itemAt(pos)
        act_favorite = None
        if item is not None:
            path_str = item.data(Qt.UserRole)
            if path_str:
                act_favorite = menu.addAction(
                    "Remove favorite" if config.is_favorite(path_str) else "Add favorite"
                )
        act_share = menu.addAction("共享给对方")
        chosen = menu.exec(self._grid.mapToGlobal(pos))
        if chosen is act_favorite and item is not None:
            config.toggle_favorite(item.data(Qt.UserRole))
            self._refresh_grid()
        if chosen is act_share:
            self._share_current_album()

    def _share_current_album(self) -> None:
        """把当前相册的所有照片通过后台线程逐张发给对方，不阻塞 UI。"""
        if self._hub is None:
            QMessageBox.information(self, "共享", "同步服务未启动，无法共享。")
            return
        # 旧共享任务还在跑时拒绝重复触发
        if self._share_worker is not None and self._share_worker.isRunning():
            QMessageBox.information(self, "共享", "上一次共享还在进行中…")
            return
        path = self._album_combo.currentData() or ""
        images = ip.list_images(path)
        if not images:
            self.statusBar().showMessage("当前相册没有照片", 3000)
            return
        current_album_name = self._album_combo.currentText()
        total = len(images)
        # 进度条显示在状态栏区域
        self._share_progress = QProgressBar()
        self._share_progress.setRange(0, total)
        self._share_progress.setValue(0)
        self._share_progress.setFormat(f"共享中 %v/{total}")
        self._share_progress.setMaximumHeight(24)
        self.statusBar().addPermanentWidget(self._share_progress)
        worker = _ShareWorker(self._hub, images, current_album_name)
        worker.progress.connect(self._on_share_progress)
        worker.finished_all.connect(self._on_share_done)
        worker.finished.connect(worker.deleteLater)
        self._share_worker = worker
        worker.start()

    def _on_share_progress(self, sent: int, total: int) -> None:
        if hasattr(self, "_share_progress") and self._share_progress:
            self._share_progress.setValue(sent)

    def _on_share_done(self, sent: int, total: int) -> None:
        # 清理进度条
        if hasattr(self, "_share_progress") and self._share_progress:
            self.statusBar().removeWidget(self._share_progress)
            self._share_progress.deleteLater()
            self._share_progress = None
        # 用 statusBar 反馈而非模态弹窗
        if sent == total:
            self.statusBar().showMessage(f"已共享 {sent} 张照片给对方", 5000)
        else:
            self.statusBar().showMessage(
                f"已共享 {sent}/{total} 张（部分照片因过大被跳过）", 8000
            )
        self._share_worker = None

    def closeEvent(self, event) -> None:
        # 窗口关闭时停止后台 worker，避免向已销毁的 widget emit
        self._stop_thumb_worker()
        if self._share_worker is not None:
            try:
                # 断开信号，避免 worker 在窗口销毁后 emit 到已失效的槽
                self._share_worker.progress.disconnect()
                self._share_worker.finished_all.disconnect()
            except RuntimeError:
                pass
            if self._share_worker.isRunning():
                self._share_worker.requestInterruption()
        super().closeEvent(event)

    # ---------- 接收对方共享 ----------
    def refresh_albums(self) -> None:
        """刷新相册下拉（收到对方共享照片后由 launcher 调用）。"""
        self._populate_albums()


def handle_partner_event(
    meta: dict, content: str, attachment: bytes, att_ext: str
) -> None:
    """接收对方共享的照片：保存到 shared_photos 目录并注册为对方共享相册。

    安全：
    - filename 来自网络输入，先用 safe_filename 取纯文件名防止路径遍历
    - attachment 大小校验，超限拒绝并记录日志
    被画廊窗口的事件分发调用（也可由 launcher 路由器直接调用）。
    """
    if not attachment:
        return
    # 附件大小校验
    err = check_attachment_size(attachment)
    if err is not None:
        log_warning("拒绝接收共享照片: %s", err)
        return
    shared_dir = app_paths.DATA_DIR / "shared_photos"
    shared_dir.mkdir(parents=True, exist_ok=True)
    # 文件名安全化：去除任何路径分隔符
    raw_name = meta.get("filename", "photo")
    safe_name = safe_filename(raw_name, fallback="photo")
    filename = f"{int(time.time())}_{safe_name}"
    try:
        atomic_write_bytes(shared_dir / filename, attachment)
    except OSError:
        log_exception("写入共享照片失败: %s", filename)
        return
    config.add_partner_album_path(str(shared_dir))
