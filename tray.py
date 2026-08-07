"""统一托盘：合并相框与信箱的菜单控制，一个爱心图标管全部。"""
from __future__ import annotations

from PySide6.QtCore import QObject, QPointF, Signal
from PySide6.QtGui import (
    QAction,
    QColor,
    QIcon,
    QPainter,
    QPen,
    QPolygonF,
    QPixmap,
    Qt,
)
from PySide6.QtWidgets import QFileDialog, QMenu, QSystemTrayIcon

from DesktopPhotoFrame import config as pf_config


def _make_heart_icon(size: int = 64) -> QIcon:
    """粉色爱心图标。"""
    pm = QPixmap(size, size)
    pm.fill(Qt.transparent)
    p = QPainter(pm)
    p.setRenderHint(QPainter.Antialiasing, True)
    p.setPen(Qt.NoPen)
    p.setBrush(QColor(236, 90, 122))
    r = size / 4.0
    cx, cy = size / 2.0, size / 2.0
    p.drawEllipse(int(cx - r * 0.55), int(cy - r * 0.45), int(r), int(r))
    p.drawEllipse(int(cx - r * 0.05), int(cy - r * 0.45), int(r), int(r))
    tri = QPolygonF([
        QPointF(cx - r * 1.05, cy - r * 0.05),
        QPointF(cx + r * 1.05, cy - r * 0.05),
        QPointF(cx, cy + r * 1.15),
    ])
    p.drawPolygon(tri)
    p.end()
    return QIcon(pm)


class UnifiedTray(QObject):
    """统一托盘控制器：一个图标，菜单分相框/信箱两段。"""

    # 相框信号
    pf_next = Signal()
    pf_prev = Signal()
    pf_shuffle = Signal()
    pf_pause = Signal()
    pf_zoom = Signal()
    pf_polaroid = Signal()
    pf_watermark = Signal()
    pf_ken_burns = Signal()
    pf_blur_background = Signal()
    pf_image_dir = Signal(str)
    pf_switch_album = Signal(str)
    # 信箱信号
    mb_compose = Signal()
    mb_inbox = Signal()
    # 新模块信号
    open_checkin = Signal()
    open_movies = Signal()
    open_travel = Signal()
    open_gallery = Signal()
    # 互动信号（Task 8/9）
    send_heart = Signal()
    open_gomoku = Signal()
    # 工具
    settings_requested = Signal()
    stats_requested = Signal()
    backup_export_requested = Signal()
    backup_restore_requested = Signal()
    # 通用
    quit_requested = Signal()

    def __init__(self, pf_window) -> None:
        super().__init__()
        self._pf_window = pf_window
        self._tray = QSystemTrayIcon(_make_heart_icon())
        self._tray.setToolTip("桌面相册")
        self._build_menu()
        self._tray.activated.connect(self._on_activated)
        pf_window.status_message.connect(self.show_status)
        self._tray.show()
        self.refresh_albums()

    def _build_menu(self) -> None:
        menu = QMenu()

        # ===== 相框区 =====
        sec_pf = QAction("— 相册 —", menu)
        sec_pf.setEnabled(False)
        menu.addAction(sec_pf)

        self._act_next = QAction("下一张  →", menu)
        self._act_next.triggered.connect(self.pf_next)
        menu.addAction(self._act_next)

        self._act_prev = QAction("上一张  ←", menu)
        self._act_prev.triggered.connect(self.pf_prev)
        menu.addAction(self._act_prev)

        self._act_shuffle = QAction("随机一张  🎲", menu)
        self._act_shuffle.triggered.connect(self.pf_shuffle)
        menu.addAction(self._act_shuffle)

        menu.addSeparator()

        self._act_pause = QAction("暂停", menu)
        self._act_pause.triggered.connect(self._on_pause)
        menu.addAction(self._act_pause)

        self._act_zoom = QAction("放大/缩小  (双击)", menu)
        self._act_zoom.triggered.connect(self.pf_zoom)
        menu.addAction(self._act_zoom)

        menu.addSeparator()

        pf_cfg = pf_config.load()
        self._act_polaroid = QAction("拍立得边框", menu)
        self._act_polaroid.setCheckable(True)
        self._act_polaroid.setChecked(pf_cfg["polaroid_frame"])
        self._act_polaroid.triggered.connect(self._on_polaroid)
        menu.addAction(self._act_polaroid)

        self._act_watermark = QAction("日期水印", menu)
        self._act_watermark.setCheckable(True)
        self._act_watermark.setChecked(pf_cfg["show_watermark"])
        self._act_watermark.triggered.connect(self._on_watermark)
        menu.addAction(self._act_watermark)

        self._act_kenburns = QAction("Ken Burns 动画", menu)
        self._act_kenburns.setCheckable(True)
        self._act_kenburns.setChecked(pf_cfg.get("ken_burns", True))
        self._act_kenburns.triggered.connect(self._on_ken_burns)
        menu.addAction(self._act_kenburns)

        self._act_blur_bg = QAction("模糊背景填充", menu)
        self._act_blur_bg.setCheckable(True)
        self._act_blur_bg.setChecked(pf_cfg.get("blur_background", False))
        self._act_blur_bg.triggered.connect(self._on_blur_background)
        menu.addAction(self._act_blur_bg)

        self._album_menu = QMenu("切换相册 ▶", menu)
        menu.addMenu(self._album_menu)

        self._act_dir = QAction("选择图片目录…", menu)
        self._act_dir.triggered.connect(self._choose_image_dir)
        menu.addAction(self._act_dir)

        self._act_gallery = QAction("🖼 画廊浏览…", menu)
        self._act_gallery.triggered.connect(self.open_gallery)
        menu.addAction(self._act_gallery)

        menu.addSeparator()

        # ===== 信箱区 =====
        sec_mb = QAction("— 信箱 —", menu)
        sec_mb.setEnabled(False)
        menu.addAction(sec_mb)

        self._act_compose = QAction("✍ 写信…", menu)
        self._act_compose.triggered.connect(self.mb_compose)
        menu.addAction(self._act_compose)

        self._act_inbox = QAction("📬 信件箱…", menu)
        self._act_inbox.triggered.connect(self.mb_inbox)
        menu.addAction(self._act_inbox)

        menu.addSeparator()

        # ===== 日历区 =====
        sec_checkin = QAction("— 日历 —", menu)
        sec_checkin.setEnabled(False)
        menu.addAction(sec_checkin)

        act_checkin = QAction("📅 打卡日历…", menu)
        act_checkin.triggered.connect(self.open_checkin)
        menu.addAction(act_checkin)

        menu.addSeparator()

        # ===== 影视区 =====
        sec_movies = QAction("— 影视 —", menu)
        sec_movies.setEnabled(False)
        menu.addAction(sec_movies)

        act_movies = QAction("🎬 影视看板…", menu)
        act_movies.triggered.connect(self.open_movies)
        menu.addAction(act_movies)

        menu.addSeparator()

        # ===== 地图区 =====
        sec_travel = QAction("— 地图 —", menu)
        sec_travel.setEnabled(False)
        menu.addAction(sec_travel)

        act_travel = QAction("🗺 旅行地图…", menu)
        act_travel.triggered.connect(self.open_travel)
        menu.addAction(act_travel)

        menu.addSeparator()

        # ===== 互动区 =====
        sec_interact = QAction("— 互动 —", menu)
        sec_interact.setEnabled(False)
        menu.addAction(sec_interact)

        act_heart = QAction("💞 想你了", menu)
        act_heart.triggered.connect(self.send_heart)
        menu.addAction(act_heart)

        act_gomoku = QAction("♟ 五子棋", menu)
        act_gomoku.triggered.connect(self.open_gomoku)
        menu.addAction(act_gomoku)

        menu.addSeparator()

        # ===== 工具区 =====
        act_settings = QAction("⚙ 设置…", menu)
        act_settings.triggered.connect(self.settings_requested)
        menu.addAction(act_settings)

        act_stats = QAction("📊 统计看板…", menu)
        act_stats.triggered.connect(self.stats_requested)
        menu.addAction(act_stats)

        menu.addSeparator()

        act_export = QAction("💾 导出备份…", menu)
        act_export.triggered.connect(self.backup_export_requested)
        menu.addAction(act_export)

        act_restore = QAction("📂 恢复备份…", menu)
        act_restore.triggered.connect(self.backup_restore_requested)
        menu.addAction(act_restore)

        menu.addSeparator()

        # ===== 退出 =====
        self._act_quit = QAction("退出", menu)
        self._act_quit.triggered.connect(self.quit_requested)
        menu.addAction(self._act_quit)

        self._menu = menu
        self._tray.setContextMenu(menu)

    # ---------- 托盘交互 ----------

    def _on_activated(self, reason) -> None:
        if reason == QSystemTrayIcon.DoubleClick:
            # 双击托盘：切换相框可见
            w = self._pf_window
            if w.isVisible():
                w.hide()
            else:
                w.show()
                w.raise_()

    # ---------- 相框菜单处理 ----------

    def _on_pause(self) -> None:
        paused = self._pf_window.toggle_pause()
        self._act_pause.setText("继续" if paused else "暂停")

    def _on_polaroid(self) -> None:
        self._pf_window.toggle_polaroid()

    def _on_watermark(self) -> None:
        self._pf_window.toggle_watermark()

    def _on_ken_burns(self) -> None:
        self._pf_window.toggle_ken_burns()

    def _on_blur_background(self) -> None:
        self._pf_window.toggle_blur_background()

    def _choose_image_dir(self) -> None:
        cur = pf_config.load()["image_dir"]
        path = QFileDialog.getExistingDirectory(
            self._pf_window, "选择图片目录", cur
        )
        if path:
            self.pf_image_dir.emit(path)
            self._pf_window.set_image_dir(path)
            self.refresh_albums()

    def refresh_albums(self) -> None:
        """重建相册子菜单：每个相册一个 QAction，当前相册打勾。"""
        self._album_menu.clear()
        albums = pf_config.list_albums()
        cur_dir = pf_config.load().get("image_dir", "")
        for a in albums:
            name = a.get("name", a.get("path", ""))
            path = a.get("path", "")
            act = QAction(name, self._album_menu)
            act.setCheckable(True)
            act.setChecked(path == cur_dir)
            act.triggered.connect(
                lambda _checked=False, p=path: self._on_switch_album(p)
            )
            self._album_menu.addAction(act)

    def _on_switch_album(self, path: str) -> None:
        self.pf_switch_album.emit(path)
        self._pf_window.switch_album(path)
        self.refresh_albums()

    # 同步菜单勾选
    def sync_polaroid(self, on: bool) -> None:
        self._act_polaroid.setChecked(on)

    def sync_watermark(self, on: bool) -> None:
        self._act_watermark.setChecked(on)

    def sync_ken_burns(self, on: bool) -> None:
        self._act_kenburns.setChecked(on)

    def sync_blur_background(self, on: bool) -> None:
        self._act_blur_bg.setChecked(on)

    def update_pause_text(self, paused: bool) -> None:
        self._act_pause.setText("继续" if paused else "暂停")

    # ---------- 通知 ----------

    def show_toast(self, title: str, msg: str) -> None:
        """成功类通知（信息图标，3 秒）。"""
        self._tray.showMessage(title, msg, QSystemTrayIcon.Information, 3000)

    def show_success(self, msg: str, title: str = "") -> None:
        """成功反馈：3 秒，信息图标。"""
        self._tray.showMessage(title or "完成", msg, QSystemTrayIcon.Information, 3000)

    def show_warning(self, msg: str, title: str = "注意") -> None:
        """警告反馈：5 秒，警告图标。"""
        self._tray.showMessage(title, msg, QSystemTrayIcon.Warning, 5000)

    def show_error(self, msg: str, title: str = "出错了") -> None:
        """错误反馈：8 秒，关键图标。"""
        self._tray.showMessage(title, msg, QSystemTrayIcon.Critical, 8000)

    def show_status(self, msg: str) -> None:
        """相册状态消息（单参数，2 秒）。"""
        self._tray.showMessage("相册", msg, QSystemTrayIcon.Information, 2000)

    def set_unread_count(self, n: int) -> None:
        self._unread_count = n
        self._refresh_tooltip()

    def set_partner_online(self, online: bool) -> None:
        """更新对方在线状态（体现在 tooltip 末尾）。"""
        self._partner_online = online
        self._refresh_tooltip()

    def _refresh_tooltip(self) -> None:
        n = getattr(self, "_unread_count", 0)
        base = f"桌面相册 · {n} 封未读" if n else "桌面相册"
        if getattr(self, "_partner_online", False):
            base = f"{base}（对方在线）"
        self._tray.setToolTip(base)
