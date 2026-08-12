"""到期检测器：定时轮询未读信件，发现新到期信件时发信号。"""
from __future__ import annotations

from PySide6.QtCore import QObject, QTimer, Qt, Signal

from . import config
from . import letter_store


class DueChecker(QObject):
    """每 N 秒检查一次；发起新到期的信件 id 列表。"""

    letters_due = Signal(list)  # list[str] of letter ids

    def __init__(self) -> None:
        super().__init__()
        self._timer = QTimer(self)
        self._timer.setTimerType(Qt.VeryCoarseTimer)
        self._timer.timeout.connect(self._check)
        # 启动时 _already_notified 初始为空集：
        # 关机期间到期的未读信件，由首次 _check() 正常发 letters_due 通知，
        # 而非被静默吞掉只更新托盘未读数。
        # list_due_unread 已过滤 read==true，历史已读信件不会进入，无需特殊处理。
        # _already_notified 仅用于运行期去重：信件通知一次后加入集合，
        # 后续 QTimer 轮询不再重复通知同一封信。
        self._already_notified: set[str] = set()

    def start(self) -> None:
        interval = max(10, config.load().get("check_interval_sec", 30)) * 1000
        self._timer.start(interval)
        # 首次 _check() 由 QTimer 触发（此时 letters_due 已连好处理函数）：
        # 关机期间到期的未读信件会正常弹通知。

    def _check(self) -> None:
        due = letter_store.list_due_unread()
        new_ids = [
            it["id"] for it in due
            if it["id"] not in self._already_notified
        ]
        for it in due:
            self._already_notified.add(it["id"])
        if new_ids:
            self.letters_due.emit(new_ids)

    def reset_known(self) -> None:
        """重新计算已知集合（删除信件后调用，避免再弹）。"""
        self._already_notified = {it["id"] for it in letter_store.list_due_unread()}
