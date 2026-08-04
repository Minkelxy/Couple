"""桌面相册统一入口。

一个 QApplication 同时运行：
- 桌面相册（透明置顶轮播窗口）
- 信箱（托盘常驻 + 延时信件 + 双机同步）

统一一个爱心托盘图标，右键菜单分"相册"/"信箱"两段。
"""
from __future__ import annotations

import sys
import time
from pathlib import Path

from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QGuiApplication
from PySide6.QtWidgets import QApplication

import app_paths
import migration

from DesktopPhotoFrame import config as pf_config
from DesktopPhotoFrame.frame_window import FrameWindow
from DesktopPhotoFrame.gallery_window import GalleryGridWindow

from DesktopMailbox import config as mb_config
from DesktopMailbox import anniversary, letter_store
from DesktopMailbox.compose_window import ComposeWindow
from DesktopMailbox.inbox_window import InboxWindow
from DesktopMailbox.notifier import DueChecker
from DesktopMailbox.read_letter_window import ReadLetterWindow
from DesktopMailbox.sync import SyncHub

from DailyCheckin.checkin_window import CheckinWindow, handle_partner_event
from MovieBoard.board_window import (
    BoardWindow,
    handle_partner_event as handle_movie_partner_event,
)
from TravelMap.map_window import (
    TravelMapWindow,
    handle_partner_event as handle_map_partner_event,
)
from DesktopPhotoFrame.gallery_window import (
    GalleryGridWindow,
    handle_partner_event as handle_photo_partner_event,
)
from Gomoku.game_window import (
    handle_partner_event as handle_gomoku_partner_event,
    open_window as open_gomoku_window,
    set_hub as set_gomoku_hub,
)

from tray import UnifiedTray
from settings_window import SettingsWindow
from stats_window import StatsWindow
from onboarding import OnboardingWindow
import backup
from PySide6.QtCore import QEventLoop


def main() -> int:
    QGuiApplication.setHighDpiScaleFactorRoundingPolicy(
        Qt.HighDpiScaleFactorRoundingPolicy.PassThrough
    )

    app = QApplication(sys.argv)
    app.setApplicationName("CoupleSuite")
    app.setQuitOnLastWindowClosed(False)  # 靠托盘退出

    # ===== 数据目录初始化与旧数据迁移 =====
    app_paths.ensure_dirs()
    migration.run_migration()

    # ===== 首次运行引导 =====
    if app_paths.is_first_run():
        loop = QEventLoop()
        ob = OnboardingWindow()
        ob.finished.connect(loop.quit)
        ob.show()
        loop.exec()

    # ===== 相框初始化 =====
    pf_cfg = pf_config.load()
    images_dir = Path(pf_cfg["image_dir"])
    images_dir.mkdir(parents=True, exist_ok=True)
    pf_window = FrameWindow(pf_cfg)
    pf_window.show()

    # ===== 信箱初始化 =====
    mb_config.ensure_dirs()
    anniv_created = anniversary.check_and_deliver()

    # ===== 统一托盘 =====
    tray = UnifiedTray(pf_window)

    # 信箱组件
    checker = DueChecker()
    checker.start()
    hub_holder = {"hub": SyncHub(mb_config.load())}
    hub_holder["hub"].start()
    set_gomoku_hub(hub_holder["hub"])

    # 窗口按需创建/复用
    compose_win: ComposeWindow | None = None
    inbox_win: InboxWindow | None = None
    read_windows: dict[str, ReadLetterWindow] = {}
    settings_win: SettingsWindow | None = None
    stats_win: StatsWindow | None = None
    checkin_win: CheckinWindow | None = None
    movies_win: BoardWindow | None = None
    travel_win: TravelMapWindow | None = None
    gallery_win: GalleryGridWindow | None = None

    # 对方最后一次心跳时间戳（用于在线状态判断）
    hub_holder["last_heartbeat"] = 0.0

    def update_unread() -> None:
        tray.set_unread_count(letter_store.count_unread())

    def open_compose(
        *, author: str = "", recipient: str = "", title: str = ""
    ) -> None:
        nonlocal compose_win
        if compose_win is None:
            compose_win = ComposeWindow(sync_hub=hub_holder["hub"])
            compose_win.sent.connect(update_unread)
        if author or recipient or title:
            compose_win.prefill(author=author, recipient=recipient, title=title)
        compose_win.show()
        compose_win.raise_()
        compose_win.activateWindow()

    def open_inbox() -> None:
        nonlocal inbox_win
        if inbox_win is None:
            inbox_win = InboxWindow()
            inbox_win.open_requested.connect(open_read_letter)
            inbox_win.destroyed.connect(lambda *_: _clear_inbox_ref())
        inbox_win.refresh()
        inbox_win.show()
        inbox_win.raise_()
        inbox_win.activateWindow()

    def _clear_inbox_ref() -> None:
        nonlocal inbox_win
        inbox_win = None

    def open_read_letter(letter_id: str) -> None:
        if letter_id in read_windows:
            w = read_windows[letter_id]
            if w.isVisible():
                w.raise_()
                w.activateWindow()
                return
        win = ReadLetterWindow(letter_id)
        read_windows[letter_id] = win
        win.reply_requested.connect(
            lambda a, r, t: open_compose(author=a, recipient=r, title=t)
        )
        win.show()
        win.raise_()
        win.activateWindow()
        win.destroyed.connect(lambda *_: read_windows.pop(letter_id, None))
        win.destroyed.connect(lambda *_: update_unread())
        if inbox_win is not None:
            inbox_win.refresh()
        update_unread()

    def on_letters_due(ids: list[str]) -> None:
        if not ids:
            return
        first_meta = next(
            (it for it in letter_store.list_letters() if it["id"] == ids[0]),
            None,
        )
        title = first_meta["title"] if first_meta else "新信件"
        author = first_meta["author"] if first_meta else "?"
        tray.show_toast("💌 收到一封信", f"来自 {author}：{title}")
        update_unread()
        open_read_letter(ids[0])

    def on_sync_received(letter_id: str) -> None:
        update_unread()
        if any(it["id"] == letter_id for it in letter_store.list_due_unread()):
            on_letters_due([letter_id])

    def on_event_received(evt_type: str, meta: dict, content: str,
                          attachment: bytes, att_ext: str) -> None:
        """按 type 分发同步事件到各模块。"""
        if evt_type == "checkin":
            handle_partner_event(meta, content, attachment, att_ext)
        elif evt_type == "movie":
            handle_movie_partner_event(meta, content, attachment, att_ext)
            if movies_win is not None:
                movies_win.refresh()
        elif evt_type == "map":
            handle_map_partner_event(meta, content, attachment, att_ext)
            if travel_win is not None:
                travel_win.refresh()
        elif evt_type == "photo":
            handle_photo_partner_event(meta, content, attachment, att_ext)
            if gallery_win is not None:
                gallery_win.refresh_albums()
        elif evt_type == "ping":
            kind = meta.get("kind", "")
            if kind == "miss_you":
                # 想你了：弹出爱心
                from DesktopPhotoFrame.heart_popup import HeartPopup
                HeartPopup.show_heart()
            elif kind == "heartbeat":
                # 心跳：更新在线时间戳，不弹窗
                hub_holder["last_heartbeat"] = time.time()
        elif evt_type in ("gomoku_move", "gomoku_ctrl"):
            handle_gomoku_partner_event(meta, content, attachment, att_ext)

    def open_settings() -> None:
        nonlocal settings_win
        if settings_win is None:
            settings_win = SettingsWindow()
            settings_win.settings_changed.connect(on_settings_changed)
        settings_win.show()
        settings_win.raise_()
        settings_win.activateWindow()

    def on_settings_changed() -> None:
        """设置保存后即时生效：重载相框配置、重启同步、刷新相册菜单。"""
        # 重载相框
        pf_window.reload(pf_config.load())
        # 重启同步服务
        hub_holder["hub"].stop()
        hub_holder["hub"] = SyncHub(mb_config.load())
        hub_holder["hub"].start()
        set_gomoku_hub(hub_holder["hub"])
        hub_holder["hub"].send_result.connect(
            lambda ok, msg: tray.show_toast("同步", msg)
        )
        hub_holder["hub"].letter_received.connect(on_sync_received)
        hub_holder["hub"].event_received.connect(on_event_received)
        # 更新 compose 窗口的 sync 引用（如果已创建）
        # ComposeWindow 持有旧 hub 引用，但下次创建新窗口时会用新 hub
        # 刷新托盘相册菜单
        tray.refresh_albums()
        tray.show_toast("设置", "已生效")

    def open_stats() -> None:
        nonlocal stats_win
        if stats_win is None:
            stats_win = StatsWindow()
        # 每次打开刷新数据
        stats_win.__init__()
        stats_win.show()
        stats_win.raise_()
        stats_win.activateWindow()

    def open_gallery() -> None:
        nonlocal gallery_win
        if gallery_win is None:
            gallery_win = GalleryGridWindow(hub=hub_holder["hub"])
        gallery_win.show()
        gallery_win.raise_()
        gallery_win.activateWindow()

    def do_backup_export() -> None:
        from PySide6.QtWidgets import QFileDialog
        path, _ = QFileDialog.getSaveFileName(
            None, "导出备份",
            f"CoupleSuite_backup_{__import__('datetime').datetime.now().strftime('%Y%m%d')}.zip",
            "ZIP 压缩包 (*.zip)"
        )
        if not path:
            return
        try:
            saved = backup.export_backup(Path(path))
            tray.show_toast("备份", f"已导出到 {saved}")
        except Exception as e:
            tray.show_toast("备份失败", str(e))

    def do_backup_restore() -> None:
        from PySide6.QtWidgets import QFileDialog, QMessageBox
        path, _ = QFileDialog.getOpenFileName(
            None, "选择备份文件", "", "ZIP 压缩包 (*.zip)"
        )
        if not path:
            return
        if QMessageBox.question(
            None, "恢复备份",
            "恢复将覆盖当前所有数据（照片、信件、配置），确定继续吗？"
        ) != QMessageBox.Yes:
            return
        try:
            backup.restore_backup(Path(path))
            # 恢复后重载一切
            pf_window.reload(pf_config.load())
            tray.refresh_albums()
            update_unread()
            tray.show_toast("恢复", "数据已恢复，请重启应用以完全生效")
        except Exception as e:
            tray.show_toast("恢复失败", str(e))

    def open_checkin() -> None:
        nonlocal checkin_win
        if checkin_win is None:
            checkin_win = CheckinWindow(hub=hub_holder["hub"])
        checkin_win.show()
        checkin_win.raise_()
        checkin_win.activateWindow()

    def open_movies() -> None:
        nonlocal movies_win
        if movies_win is None:
            movies_win = BoardWindow(hub=hub_holder["hub"])
        movies_win.refresh()
        movies_win.show()
        movies_win.raise_()
        movies_win.activateWindow()

    def open_travel() -> None:
        nonlocal travel_win
        if travel_win is None:
            travel_win = TravelMapWindow(hub=hub_holder["hub"])
        travel_win.show()
        travel_win.raise_()
        travel_win.activateWindow()

    def open_gomoku() -> None:
        open_gomoku_window(hub_holder["hub"])

    # ===== 连接相框信号 =====
    tray.pf_next.connect(pf_window.show_next)
    tray.pf_prev.connect(pf_window.show_prev)
    tray.pf_shuffle.connect(pf_window.shuffle)
    tray.pf_pause.connect(lambda: tray.update_pause_text(pf_window.toggle_pause()))
    tray.pf_zoom.connect(pf_window.toggle_zoom)
    tray.pf_polaroid.connect(lambda: tray.sync_polaroid(pf_window.toggle_polaroid()))
    tray.pf_watermark.connect(lambda: tray.sync_watermark(pf_window.toggle_watermark()))
    tray.pf_ken_burns.connect(lambda: tray.sync_ken_burns(pf_window.toggle_ken_burns()))
    tray.pf_blur_background.connect(
        lambda: tray.sync_blur_background(pf_window.toggle_blur_background())
    )
    tray.pf_image_dir.connect(pf_window.set_image_dir)

    # ===== 连接信箱信号 =====
    tray.mb_compose.connect(open_compose)
    tray.mb_inbox.connect(open_inbox)

    # ===== 连接新模块信号 =====
    tray.open_checkin.connect(open_checkin)
    tray.open_movies.connect(open_movies)
    tray.open_travel.connect(open_travel)
    tray.open_gallery.connect(open_gallery)

    # ===== 互动信号 =====
    # 想你了：向对方发送 miss_you ping
    tray.send_heart.connect(
        lambda: hub_holder["hub"].send_event("ping", {"kind": "miss_you"})
    )
    tray.open_gomoku.connect(open_gomoku)

    # ===== 在线状态心跳检测 =====
    # 每 5 秒检查一次对方最后心跳时间，超过 90 秒视为离线
    HEARTBEAT_TIMEOUT = 90.0

    def check_partner_online() -> None:
        last = hub_holder.get("last_heartbeat", 0.0)
        online = (last > 0.0) and (time.time() - last <= HEARTBEAT_TIMEOUT)
        tray.set_partner_online(online)

    online_timer = QTimer()
    online_timer.setInterval(5000)
    online_timer.timeout.connect(check_partner_online)
    online_timer.start()

    tray.settings_requested.connect(open_settings)
    tray.stats_requested.connect(open_stats)
    tray.backup_export_requested.connect(do_backup_export)
    tray.backup_restore_requested.connect(do_backup_restore)

    # ===== 通知与退出 =====
    tray.quit_requested.connect(app.quit)
    checker.letters_due.connect(on_letters_due)
    hub_holder["hub"].send_result.connect(lambda ok, msg: tray.show_toast("同步", msg))
    hub_holder["hub"].letter_received.connect(on_sync_received)
    hub_holder["hub"].event_received.connect(on_event_received)
    app.aboutToQuit.connect(hub_holder["hub"].stop)

    update_unread()

    if anniv_created:
        tray.show_toast(
            "纪念日快乐 🎉",
            f"已自动投递 {len(anniv_created)} 封纪念日信件",
        )

    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
