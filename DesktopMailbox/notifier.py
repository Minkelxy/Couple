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
        self._already_notified: set[str] = set()
        # 初始化时把当前已存在的到期信件记入"已知"，避免启动瞬间弹一堆
        for it in letter_store.list_due_unread():
            self._already_notified.add(it["id"])

    def start(self) -> None:
        interval = max(10, config.load().get("check_interval_sec", 30)) * 1000
        self._timer.start(interval)
        # 启动后立刻检查一次（不弹已知的，但能更新托盘未读数）

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
