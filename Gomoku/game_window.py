"""联机五子棋主窗口：双人在线对弈 + 悔棋/重开/对局历史。

简化模型：本地玩家始终为黑，对方落子为白。每方屏幕上自己的棋子都是黑色。
事件类型：
  gomoku_move —— {row, col, color}  落子
  gomoku_ctrl —— {kind}             控制消息 (open/undo_request/undo_approve/
                                    undo_reject/restart)
"""
from __future__ import annotations

import weakref
from datetime import datetime

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QDialog, QHBoxLayout, QLabel, QListWidget, QListWidgetItem,
    QMainWindow, QMessageBox, QPushButton, QVBoxLayout, QWidget,
)

from . import store
from .board_widget import GomokuBoard

# 模块级引用：当前 GameWindow 实例 + hub 引用（供懒创建使用）
# _active_window 用弱引用：窗口关闭且无其他强引用时可被 GC，避免内存泄漏
_active_window: weakref.ref | None = None
_hub_ref: dict = {"hub": None}


def set_hub(hub) -> None:
    """由 launcher 在创建/重载 SyncHub 后调用，更新 hub 引用。"""
    _hub_ref["hub"] = hub
    win = _active_window() if _active_window is not None else None
    if win is not None:
        win._hub = hub


def handle_partner_event(meta: dict, content: str, attachment: bytes,
                         att_ext: str) -> None:
    """模块级事件分发：确保窗口存在，再转发到对应处理。

    供 launcher 的事件路由器在收到 type 为 gomoku_move/gomoku_ctrl 时调用。
    """
    global _active_window
    evt = meta.get("type", "")
    if evt not in ("gomoku_move", "gomoku_ctrl"):
        return
    win = _active_window() if _active_window is not None else None
    if win is None:
        win = GameWindow(hub=_hub_ref["hub"])
        # __init__ 已设置 _active_window 为弱引用
        # 懒创建的窗口需 show，否则无强引用会被 GC（on_partner_ctrl 也会自行 show）
        win.show()
    if evt == "gomoku_move":
        win.on_partner_move(meta, content, attachment, att_ext)
    else:
        win.on_partner_ctrl(meta, content, attachment, att_ext)


def open_window(hub) -> None:
    """复用或创建 GameWindow 并显示。由 launcher 调用。"""
    global _active_window
    win = _active_window() if _active_window is not None else None
    if win is None:
        win = GameWindow(hub=hub)
        # __init__ 已设置 _active_window 为弱引用
    else:
        win._hub = hub
    win.show()
    win.raise_()
    win.activateWindow()


class HistoryWindow(QDialog):
    """对局历史：左侧列表，右侧回放最终棋面。"""

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("对局历史 ♟")
        self.resize(820, 640)
        self._build_ui()

    def _build_ui(self) -> None:
        lay = QHBoxLayout(self)
        lay.setContentsMargins(12, 12, 12, 12)
        lay.setSpacing(12)

        # 左：对局列表
        left = QVBoxLayout()
        left.setSpacing(6)
        left.addWidget(QLabel("双击查看棋谱：", self))
        self._list = QListWidget(self)
        self._list.setMinimumWidth(280)
        self._list.itemDoubleClicked.connect(self._on_double)
        left.addWidget(self._list, 1)
        lay.addLayout(left, 0)

        # 右：回放棋盘（只读）
        self._board = GomokuBoard(self)
        self._board.set_locked(True)
        lay.addWidget(self._board, 1)

        self._refresh()

    def _refresh(self) -> None:
        self._list.clear()
        for g in store.list_games():
            winner = g.get("winner", "?")
            n = g.get("moves_count", 0)
            ts = g.get("played_at", "")[:16].replace("T", " ")
            text = f"{ts}  ·  {winner} 胜  ·  {n} 手"
            item = QListWidgetItem(text)
            item.setData(Qt.UserRole, g.get("id", ""))
            self._list.addItem(item)

    def _on_double(self, item: QListWidgetItem) -> None:
        gid = item.data(Qt.UserRole)
        rec = store.get_game(gid)
        if not rec:
            return
        self._board.clear_board()
        for mv in rec.get("moves", []):
            try:
                r = int(mv.get("row", 0))
                c = int(mv.get("col", 0))
            except (TypeError, ValueError):
                continue
            color = 1 if mv.get("color") == "black" else 2
            self._board.place_stone(r, c, color)


class GameWindow(QMainWindow):
    """联机五子棋主窗口。"""

    def __init__(self, hub=None) -> None:
        super().__init__()
        self._hub = hub
        global _active_window
        _active_window = weakref.ref(self)
        self._my_color = "black"   # 本地始终为黑
        self._game_over = False
        self._i_requested_undo = False
        # 并发竞态：双方同时点悔棋时，自己先同意了对方的 undo_request
        # （已在本地 undo_last(2)），随后对方对自己早先发出的 undo_request
        # 回复 undo_approve 到达，导致再次 undo_last(2) 共撤 4 手。
        # 用 _local_undo_applied 标志标记本地已执行过撤销。
        self._local_undo_applied = False
        self._i_requested_restart = False
        self._suppress_open = False

        self.setWindowTitle("联机五子棋 ♟")
        self._build_ui()
        self._sync_lock()

    # ---------- UI ----------

    def _build_ui(self) -> None:
        central = QWidget(self)
        root = QVBoxLayout(central)
        root.setContentsMargins(12, 10, 12, 10)
        root.setSpacing(8)

        # 顶部工具栏
        bar = QHBoxLayout()
        bar.setSpacing(8)
        title = QLabel("♟ 联机五子棋", self)
        title.setStyleSheet("font-size:18px; font-weight:600; color:#e65a7a;")
        bar.addWidget(title)
        bar.addStretch(1)
        self._undo_btn = QPushButton("↩ 悔棋", self)
        self._restart_btn = QPushButton("🔄 重新开局", self)
        self._history_btn = QPushButton("📜 对局历史", self)
        for b in (self._undo_btn, self._restart_btn, self._history_btn):
            b.setStyleSheet(
                "QPushButton{background:#fdf2f5;color:#e65a7a;"
                "border:1px solid #e65a7a;border-radius:8px;padding:6px 14px;"
                "font-size:13px;}"
                "QPushButton:hover{background:#fce4ea;}"
            )
            bar.addWidget(b)
        self._undo_btn.clicked.connect(self._on_undo)
        self._restart_btn.clicked.connect(self._on_restart)
        self._history_btn.clicked.connect(self._on_history)
        root.addLayout(bar)

        # 棋盘居中
        self._board = GomokuBoard(self)
        self._board.stone_placed.connect(self._on_stone_placed)
        self._board.game_over.connect(self._on_game_over)
        wrap = QHBoxLayout()
        wrap.addStretch(1)
        wrap.addWidget(self._board)
        wrap.addStretch(1)
        root.addLayout(wrap, 1)

        self.setCentralWidget(central)
        self.statusBar().showMessage("轮到你落子（黑棋）")

    # ---------- 状态栏与锁定 ----------

    def _status(self, msg: str) -> None:
        self.statusBar().showMessage(msg)

    def _sync_lock(self) -> None:
        """根据当前回合同步棋盘锁定状态。"""
        if self._game_over:
            self._board.set_locked(True)
            return
        if self._hub is None:
            self._board.set_locked(False)
            return
        # 在线：本地为黑，对方（白）回合时锁定
        self._board.set_locked(self._board.current_color() == 2)

    # ---------- 本地落子 ----------

    def _on_stone_placed(self, row: int, col: int, color: int) -> None:
        if self._hub:
            self._hub.send_event("gomoku_move", {
                "row": row, "col": col, "color": "black",
            }, silent=True)
            self._status("等待对方落子…")
        else:
            # 本地双人模式：黑白轮流
            cur = "黑" if self._board.current_color() == 1 else "白"
            self._status(f"轮到 {cur} 方落子")
        self._sync_lock()

    # ---------- 对方落子 ----------

    def on_partner_move(self, meta: dict, content: str, attachment: bytes,
                        att_ext: str) -> None:
        if meta.get("type") != "gomoku_move":
            return
        # 防御：游戏结束后收到迟到的落子（网络抖动、重传、对方未同步致胜结果）
        # 继续落子会重复触发 game_over 并写入第二条对局记录，直接丢弃
        if self._game_over:
            return
        try:
            row = int(meta.get("row", -1))
            col = int(meta.get("col", -1))
        except (TypeError, ValueError):
            return
        if row < 0 or col < 0:
            return
        # 对方落子始终为白（本地为黑）
        self._board.place_stone(row, col, 2)
        if not self._game_over:
            self._status("轮到你落子（黑棋）")
        self._sync_lock()

    # ---------- 对方控制消息 ----------

    def on_partner_ctrl(self, meta: dict, content: str, attachment: bytes,
                        att_ext: str) -> None:
        kind = meta.get("kind", "")
        if kind == "open":
            if not self.isVisible():
                self._suppress_open = True
                self.show()
                self._suppress_open = False
            self.raise_()
            self.activateWindow()
        elif kind == "undo_request":
            self._handle_undo_request()
        elif kind == "undo_approve":
            # 并发竞态：双方同时发 undo_request 时，对方可能先同意了我的请求
            # （我这边随后才回复），此时我已经在 _handle_undo_request 里
            # undo_last(2) 并标记 _local_undo_applied=True。
            # 若对方也给我回复 undo_approve，再次 undo 会多撤 2 手。
            # 故只有本方确实发过 undo_request 且尚未在本地执行撤销时才撤销。
            if self._i_requested_undo and not self._local_undo_applied:
                self._board.undo_last(2)
            self._local_undo_applied = False
            self._game_over = False
            self._i_requested_undo = False
            self._board.set_locked(False)
            self._status("对方同意悔棋，轮到你落子")
        elif kind == "undo_reject":
            self._local_undo_applied = False
            self._i_requested_undo = False
            self._sync_lock()
            self._status("对方拒绝悔棋，轮到你落子")
            QMessageBox.information(self, "悔棋", "对方拒绝悔棋")
        elif kind == "restart":
            # 并发竞态：双方同时点重开时，双方都会在 _on_restart 解锁，
            # 之后各自收到对方的 restart 事件又锁定 → 两方都锁死。
            # 用 _i_requested_restart 守卫：若自己刚发起过重开，收到对方
            # restart 时不重复锁定（按「本地先手=解锁」保持一致）。
            if self._i_requested_restart:
                self._i_requested_restart = False
                self._board.set_locked(False)
                self._status("双方同时重新开局，你先手（黑棋）")
            else:
                self._board.clear_board()
                self._game_over = False
                self._i_requested_undo = False
                # 对方发起重开，等待对方先手
                self._board.set_locked(True)
                self._status("对方发起重新开局，等待对方先手")

    def _handle_undo_request(self) -> None:
        """响应对方的悔棋请求。"""
        btn = QMessageBox.question(self, "悔棋请求", "对方想悔棋，同意吗？")
        if btn == QMessageBox.Yes:
            if self._hub:
                self._hub.send_event("gomoku_ctrl", {"kind": "undo_approve"}, silent=True)
            self._board.undo_last(2)
            # 标记：我已在本地执行过撤销。如果对方随后也同意了我方早先发出的
            # undo_request，收到 undo_approve 时不再重复撤销（防撤 4 手）。
            self._local_undo_applied = True
            self._game_over = False
            # 同意后等待对方落子（对方先手）
            self._board.set_locked(True)
            self._status("你同意了悔棋，等待对方落子")
        else:
            if self._hub:
                self._hub.send_event("gomoku_ctrl", {"kind": "undo_reject"}, silent=True)
            self._status("你拒绝了悔棋")

    # ---------- 工具栏按钮 ----------

    def _on_undo(self) -> None:
        if self._game_over:
            QMessageBox.information(self, "悔棋", "对局已结束")
            return
        if self._hub is None:
            # 本地双人：直接悔两手
            self._board.undo_last(2)
            self._status("已悔棋")
            return
        if self._i_requested_undo:
            return
        self._i_requested_undo = True
        self._hub.send_event("gomoku_ctrl", {"kind": "undo_request"}, silent=True)
        self._board.set_locked(True)
        self._status("已发送悔棋请求…")

    def _on_restart(self) -> None:
        self._board.clear_board()
        self._game_over = False
        self._i_requested_undo = False
        self._local_undo_applied = False
        if self._hub:
            # 标记：自己发起了重开。收到对方 restart 时若也带该标记不重复锁定（防同时重开死锁）
            self._i_requested_restart = True
            self._hub.send_event("gomoku_ctrl", {"kind": "restart"}, silent=True)
            self._status("已重新开局，你先手（黑棋）")
        else:
            self._status("已重新开局")
        self._sync_lock()

    def _on_history(self) -> None:
        dlg = HistoryWindow(self)
        dlg.exec()

    # ---------- 结束 ----------

    def _on_game_over(self, winner: str) -> None:
        self._game_over = True
        self._board.set_locked(True)
        self._status(f"{winner} 胜！点击重新开局")
        records = [
            {"row": r, "col": c, "color": "black" if cl == 1 else "white"}
            for r, c, cl in self._board.get_moves()
        ]
        try:
            store.save_game(
                winner, records,
                datetime.now().isoformat(timespec="seconds"),
            )
        except Exception:
            pass

    # ---------- 显示通知 ----------

    def showEvent(self, event) -> None:
        super().showEvent(event)
        if self._hub and not self._suppress_open:
            self._hub.send_event("gomoku_ctrl", {"kind": "open"}, silent=True)
