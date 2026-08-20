"""信箱入口。

启动后：
- 托盘出现一个信封图标，显示未读数；
- 双击托盘打开信件箱；
- 右键菜单可"写信"/"信件箱"/"退出"；
- 写信时可选送达时间，到点自动弹 toast + 打开读信窗口。
"""
from __future__ import annotations

import sys

from PySide6.QtCore import Qt
from PySide6.QtGui import QGuiApplication
from PySide6.QtWidgets import QApplication

import anniversary
import config
import letter_store
from compose_window import ComposeWindow
from inbox_window import InboxWindow
from notifier import DueChecker
from read_letter_window import ReadLetterWindow
from sync import SyncHub, SyncSignalBridge
from tray import TrayController


def main() -> int:
    QGuiApplication.setHighDpiScaleFactorRoundingPolicy(
        Qt.HighDpiScaleFactorRoundingPolicy.PassThrough
    )

    app = QApplication(sys.argv)
    app.setApplicationName("DesktopMailbox")
    app.setQuitOnLastWindowClosed(False)  # 关窗口不退出，靠托盘

    config.ensure_dirs()

    # 纪念日自动投递（启动时检查今天是否匹配）
    anniv_created = anniversary.check_and_deliver()

    # 窗口按需创建/复用
    compose_win: ComposeWindow | None = None
    inbox_win: InboxWindow | None = None
    read_windows: dict[str, ReadLetterWindow] = {}

    tray = TrayController()
    checker = DueChecker()
    checker.start()

    # 局域网同步
    hub = SyncHub(config.load())
    hub.start()

    def update_unread() -> None:
        tray.set_unread_count(letter_store.count_unread())

    def open_compose(
        *, author: str = "", recipient: str = "", title: str = ""
    ) -> None:
        nonlocal compose_win
        if compose_win is None:
            compose_win = ComposeWindow(sync_hub=hub)
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
        # 已开则前置，避免重复
        if letter_id in read_windows:
            w = read_windows[letter_id]
            if w.isVisible():
                w.raise_()
                w.activateWindow()
                return
        win = ReadLetterWindow(letter_id)
        read_windows[letter_id] = win
        # 回信：预填收件人=原信作者
        win.reply_requested.connect(
            lambda a, r, t: open_compose(author=a, recipient=r, title=t)
        )
        win.show()
        win.raise_()
        win.activateWindow()
        # 关闭时清理引用 + 刷新未读
        win.destroyed.connect(lambda *_: read_windows.pop(letter_id, None))
        win.destroyed.connect(lambda *_: update_unread())
        # 打开即已读
        if inbox_win is not None:
            inbox_win.refresh()
        update_unread()

    def on_letters_due(ids: list[str]) -> None:
        if not ids:
            return
        # 用第一封做 toast，全部统一提示
        first_meta = next(
            (it for it in letter_store.list_letters() if it["id"] == ids[0]),
            None,
        )
        title = first_meta["title"] if first_meta else "新信件"
        author = first_meta["author"] if first_meta else "?"
        tray.show_toast("💌 收到一封信", f"来自 {author}：{title}")
        update_unread()
        # 自动打开第一封（仪式感）
        open_read_letter(ids[0])

    def on_sync_received(letter_id: str) -> None:
        update_unread()
        # 仅到期信件才立即弹窗；未来信静默等 DueChecker 到点
        if any(it["id"] == letter_id for it in letter_store.list_due_unread()):
            on_letters_due([letter_id])

    sync_bridge = SyncSignalBridge(
        lambda _ok, message: tray.show_toast("同步", message),
        on_sync_received,
        lambda *_: None,
        lambda meta, ok: hub.record_event_dispatch(meta, ok),
    )
    connection_type = Qt.ConnectionType.QueuedConnection

    # 连信号
    tray.compose_requested.connect(open_compose)
    tray.inbox_requested.connect(open_inbox)
    tray.quit_requested.connect(app.quit)
    checker.letters_due.connect(on_letters_due)
    hub.send_result.connect(sync_bridge.send_result, connection_type)
    hub.letter_received.connect(sync_bridge.letter_received, connection_type)
    hub.event_received.connect(
        sync_bridge.event_received, Qt.ConnectionType.BlockingQueuedConnection
    )

    # 退出时关闭同步服务
    app.aboutToQuit.connect(hub.stop)

    update_unread()

    # 纪念日投递提示
    if anniv_created:
        tray.show_toast(
            "纪念日快乐 🎉",
            f"已自动投递 {len(anniv_created)} 封纪念日信件",
        )

    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
