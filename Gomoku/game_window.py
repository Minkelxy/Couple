"""联机五子棋主窗口：双人在线对弈 + 悔棋/重开/对局历史。

联机协议（gomoku_move / gomoku_ctrl 两类事件）
==============================================
gomoku_move —— 落子
  meta: {row:int, col:int, color:"black", session_id:str}
  注：发送方永远为自己本地颜色（black=本地），接收方收到后永远按 white=2 落子。
      这样双方屏幕上自己的棋都是黑。

gomoku_ctrl —— 控制消息
  meta.kind 取值：
  · invite          邀请对局  {invite_id:str}
  · invite_accept   接受邀请  {invite_id:str, session_id:str}
  · invite_reject   拒绝邀请  {invite_id:str, reason?:str}
  · ready           会话已就绪（对方刚打开窗口等）{session_id:str}
  · move            废弃：请用 gomoku_move
  · undo_request    请求悔棋  {session_id:str}
  · undo_approve    同意悔棋  {session_id:str}
  · undo_reject     拒绝悔棋  {session_id:str}
  · restart         重新开局  {session_id:str, next_session_id:str}

会话模型：
  - 所有对局相关事件带 session_id，忽略"不是当前会话"的迟到消息。
  - 本地先手约定：谁接受邀请（invite_accept 的发送方）对方执黑先手；
    即「邀请发起方执白等对方先下，被邀请方执黑立即落子」。
    这样"先动手的是谁"天然一致，无需另协商。本地模型始终显示"自己=黑"，
    所以我们用一个 _i_started 标志在本地控制是否开局锁定，避免两端同时解锁。
"""
from __future__ import annotations

import threading
import uuid
import weakref
from datetime import datetime

from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import (
    QDialog, QHBoxLayout, QLabel, QListWidget, QListWidgetItem,
    QMainWindow, QMessageBox, QPushButton, QVBoxLayout, QWidget,
)

from . import store
from .board_widget import GomokuBoard

# 模块级引用：当前 GameWindow 实例 + hub 引用（供懒创建使用）
_active_window: weakref.ref | None = None
_hub_ref: dict = {"hub": None}


def _new_id(prefix: str = "") -> str:
    return prefix + uuid.uuid4().hex[:12]


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
    kind = meta.get("kind", "")
    # invite 可以在无窗口时到达 → 需要主动建窗口再弹邀请
    win = _active_window() if _active_window is not None else None
    if win is None:
        win = GameWindow(hub=_hub_ref["hub"])
        win.show()
    if evt == "gomoku_move":
        win.on_partner_move(meta, content, attachment, att_ext)
    else:
        win.on_partner_ctrl(meta, content, attachment, att_ext)


def open_window(hub, *, invite: bool = False) -> None:
    """复用或创建 GameWindow 并显示。

    - invite=False：仅打开本地对弈窗口（离线单人或已连接但不主动邀）
    - invite=True：打开窗口 + 立即向对方发 invite 邀请，等对方接受后开始
    """
    global _active_window
    win = _active_window() if _active_window is not None else None
    if win is None:
        win = GameWindow(hub=hub)
    else:
        win._hub = hub
    win.show()
    win.raise_()
    win.activateWindow()
    if invite:
        win.start_invite()


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

        left = QVBoxLayout()
        left.setSpacing(6)
        left.addWidget(QLabel("双击查看棋谱：", self))
        self._list = QListWidget(self)
        self._list.setMinimumWidth(280)
        self._list.itemDoubleClicked.connect(self._on_double)
        left.addWidget(self._list, 1)
        lay.addLayout(left, 0)

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

        self._my_color = "black"       # 本地始终显示为黑
        self._game_over = False
        self._session_id: str | None = None

        # 邀请相关（去重 + 超时）
        self._pending_invite_id: str | None = None
        self._pending_invite_from_partner: str | None = None
        self._invite_guard = threading.Lock()

        # 悔棋并发守卫
        self._i_requested_undo = False
        self._local_undo_applied = False

        # 重开并发守卫
        self._i_requested_restart = False
        self._restart_proposed_next_session: str | None = None

        # 先手标记：True = 开局后本地立即解锁（我先下）；False = 锁住等对方
        # 初始状态：离线双人模式 / 还没邀请 / 仅本地打开 → 默认解锁
        self._i_start_first = True

        self._suppress_open_show_event = False

        self.setWindowTitle("联机五子棋 ♟")
        self._build_ui()
        self._sync_lock()

    # ---------- UI ----------

    def _build_ui(self) -> None:
        central = QWidget(self)
        root = QVBoxLayout(central)
        root.setContentsMargins(12, 10, 12, 10)
        root.setSpacing(8)

        bar = QHBoxLayout()
        bar.setSpacing(8)
        title = QLabel("♟ 联机五子棋", self)
        title.setStyleSheet("font-size:18px; font-weight:600; color:#e65a7a;")
        bar.addWidget(title)
        bar.addStretch(1)

        self._invite_btn = QPushButton("📨 邀请对方", self)
        self._undo_btn = QPushButton("↩ 悔棋", self)
        self._restart_btn = QPushButton("🔄 重新开局", self)
        self._history_btn = QPushButton("📜 对局历史", self)
        for b in (self._invite_btn, self._undo_btn, self._restart_btn, self._history_btn):
            b.setStyleSheet(
                "QPushButton{background:#fdf2f5;color:#e65a7a;"
                "border:1px solid #e65a7a;border-radius:8px;padding:6px 14px;"
                "font-size:13px;}"
                "QPushButton:hover{background:#fce4ea;}"
                "QPushButton:disabled{background:#f5f5f5;color:#aaa;border-color:#ddd;}"
            )
            bar.addWidget(b)
        self._invite_btn.clicked.connect(self.start_invite)
        self._undo_btn.clicked.connect(self._on_undo)
        self._restart_btn.clicked.connect(self._on_restart)
        self._history_btn.clicked.connect(self._on_history)
        root.addLayout(bar)

        self._board = GomokuBoard(self)
        self._board.stone_placed.connect(self._on_stone_placed)
        self._board.game_over.connect(self._on_game_over)
        wrap = QHBoxLayout()
        wrap.addStretch(1)
        wrap.addWidget(self._board)
        wrap.addStretch(1)
        root.addLayout(wrap, 1)

        self.setCentralWidget(central)
        self.statusBar().showMessage("点击「邀请对方」开始联机；未邀请前可本地体验")

    # ---------- 状态栏与锁定 ----------

    def _status(self, msg: str) -> None:
        self.statusBar().showMessage(msg)

    def _sync_lock(self) -> None:
        """根据当前回合同步棋盘锁定状态。"""
        if self._game_over:
            self._board.set_locked(True)
            return
        # 离线模式 / 未连接 hub：默认解锁轮流
        if self._hub is None:
            self._board.set_locked(False)
            return
        # 在线模式：没有 session 还没开局 → 解锁让用户熟悉/本地摆
        if self._session_id is None:
            self._board.set_locked(False)
            return
        # 约定：本地黑。轮到白=对方回合时才锁
        self._board.set_locked(self._board.current_color() == 2)

    # ---------- 邀请协议 ----------

    def start_invite(self) -> None:
        """本地用户点「邀请对方」：发 invite 给对方，锁定棋盘等对方接受。"""
        if self._hub is None:
            QMessageBox.information(self, "未连接", "当前未启用联机同步，无法邀请对方。\n请在设置里启用局域网或云同步。")
            return
        with self._invite_guard:
            # 上一次邀请尚未过期：先不重复发
            if self._pending_invite_id:
                return
            invite_id = _new_id("inv-")
            self._pending_invite_id = invite_id
        # 我是邀请发起方：对方先下 → 我开局白 → 本地锁
        self._i_start_first = False
        self._session_id = None
        self._game_over = False
        self._board.clear_board()
        self._board.set_locked(True)
        self._status("已发送邀请，等待对方接受…")
        self._hub.send_event("gomoku_ctrl", {
            "kind": "invite",
            "invite_id": invite_id,
        }, silent=True)
        # 30s 未回应自动取消邀请（对方可能不在线）
        QTimer.singleShot(30_000, lambda: self._timeout_invite(invite_id))

    def _timeout_invite(self, invite_id: str) -> None:
        with self._invite_guard:
            if self._pending_invite_id != invite_id:
                return
            self._pending_invite_id = None
        self._status("邀请超时（对方未回应）")
        self._board.set_locked(False)
        self._i_start_first = True

    def _handle_invite(self, invite_id: str) -> None:
        """对方发来了 invite。需要在 GUI 线程弹框。"""
        # 同一条邀请去重
        with self._invite_guard:
            if self._pending_invite_from_partner == invite_id:
                return
            self._pending_invite_from_partner = invite_id
        # 已在对战中 → 直接拒绝（忙）
        if self._session_id is not None and not self._game_over:
            if self._hub:
                self._hub.send_event("gomoku_ctrl", {
                    "kind": "invite_reject",
                    "invite_id": invite_id,
                    "reason": "busy",
                }, silent=True)
            return

        btn = QMessageBox.question(
            self, "五子棋邀请",
            "对方邀请你下五子棋，接受吗？\n（接受后你执黑先手）",
        )
        if btn == QMessageBox.Yes:
            session_id = _new_id("ses-")
            self._session_id = session_id
            self._i_start_first = True       # 被邀请方执黑先手
            self._game_over = False
            self._board.clear_board()
            self._sync_lock()
            self._status("你接受了邀请，你执黑先手！")
            if self._hub:
                self._hub.send_event("gomoku_ctrl", {
                    "kind": "invite_accept",
                    "invite_id": invite_id,
                    "session_id": session_id,
                }, silent=True)
            with self._invite_guard:
                self._pending_invite_from_partner = None
        else:
            if self._hub:
                self._hub.send_event("gomoku_ctrl", {
                    "kind": "invite_reject",
                    "invite_id": invite_id,
                }, silent=True)
            with self._invite_guard:
                if self._pending_invite_from_partner == invite_id:
                    self._pending_invite_from_partner = None
            self._status("你拒绝了邀请")

    # ---------- 本地落子 ----------

    def _on_stone_placed(self, row: int, col: int, color: int) -> None:
        if self._hub and self._session_id:
            # 发送方永远填自己颜色 black（接收端会统一放 white）
            self._hub.send_event("gomoku_move", {
                "row": row, "col": col, "color": "black",
                "session_id": self._session_id,
            }, silent=True)
            self._status("等待对方落子…")
        else:
            cur = "黑" if self._board.current_color() == 1 else "白"
            self._status(f"轮到 {cur} 方落子")
        self._sync_lock()

    # ---------- 对方落子 ----------

    def on_partner_move(self, meta: dict, content: str, attachment: bytes,
                        att_ext: str) -> None:
        if meta.get("type") != "gomoku_move":
            return
        if self._game_over:
            return
        # session 校验：忽略不在当前会话的迟到/重放 move
        sid = meta.get("session_id")
        if self._session_id is None or (sid and sid != self._session_id):
            return
        # 回合校验：对方（white）只有在 current_color==2 时才允许落，
        #           防止重传 / 对方伪造多步连下
        if self._board.current_color() != 2:
            return
        try:
            row = int(meta.get("row", -1))
            col = int(meta.get("col", -1))
        except (TypeError, ValueError):
            return
        if row < 0 or col < 0:
            return
        # 对方颜色按 white 放置
        self._board.place_stone(row, col, 2)
        if not self._game_over:
            self._status("轮到你落子（黑棋）")
        self._sync_lock()

    # ---------- 对方控制消息 ----------

    def on_partner_ctrl(self, meta: dict, content: str, attachment: bytes,
                        att_ext: str) -> None:
        kind = meta.get("kind", "")

        # ---- 邀请相关 ----
        if kind == "invite":
            self.raise_()
            self.activateWindow()
            self._handle_invite(str(meta.get("invite_id", "")))
            return

        if kind == "invite_accept":
            with self._invite_guard:
                if not self._pending_invite_id or \
                        meta.get("invite_id") != self._pending_invite_id:
                    return
                self._pending_invite_id = None
            self._session_id = str(meta.get("session_id") or _new_id("ses-"))
            # 我是邀请发起方：对方接受 → 对方先下，本地锁
            self._i_start_first = False
            self._game_over = False
            self._board.clear_board()
            self._board.set_locked(True)
            self._status("对方接受了邀请，对方先手，请等待…")
            return

        if kind == "invite_reject":
            with self._invite_guard:
                if not self._pending_invite_id or \
                        meta.get("invite_id") != self._pending_invite_id:
                    return
                self._pending_invite_id = None
            reason = str(meta.get("reason", "") or "")
            msg = "对方在对局中，稍后再试" if reason == "busy" else "对方拒绝了邀请"
            self._status(msg)
            QMessageBox.information(self, "邀请", msg)
            # 回退为解锁，用户可继续本地玩
            self._board.set_locked(False)
            self._i_start_first = True
            return

        if kind == "ready":
            # 对方打开了窗口发来 ready：同步一下会话状态，一般不需特殊处理
            sid = meta.get("session_id")
            if sid and self._session_id is None:
                self._session_id = str(sid)
            return

        # ---- 以下控制消息都要求会话匹配 ----
        sid = meta.get("session_id")
        if self._session_id is None or (sid and sid != self._session_id):
            return

        if kind == "undo_request":
            self._handle_undo_request()
        elif kind == "undo_approve":
            # 并发竞态：双方同时发 undo_request 时，对方先同意了我的请求
            # 我这边随后才在 _handle_undo_request 里 undo_last(2) 并标记
            # _local_undo_applied=True。对方又回我的 undo_approve 会导致再
            # 撤 2 手。加守卫避免。
            if self._i_requested_undo and not self._local_undo_applied:
                self._board.undo_last(2)
            self._local_undo_applied = False
            self._game_over = False
            self._i_requested_undo = False
            # 我是悔棋发起方 → 我的上一步被撤 → 当前轮回到对方先下
            self._board.set_locked(True)
            self._status("对方同意悔棋，等待对方落子")
            self._sync_lock()
        elif kind == "undo_reject":
            self._local_undo_applied = False
            self._i_requested_undo = False
            self._sync_lock()
            if self._board.current_color() == 1:
                self._status("对方拒绝悔棋，轮到你落子")
            else:
                self._status("对方拒绝悔棋，等待对方落子")
            QMessageBox.information(self, "悔棋", "对方拒绝悔棋")
        elif kind == "restart":
            next_sid = str(meta.get("next_session_id") or _new_id("ses-"))
            # 并发竞态：双方同时点重开时，各自都会在 _on_restart 解锁，
            # 之后各自收到对方的 restart 又锁定 → 两边都锁死。
            # 用 _i_requested_restart 守卫，避免二次锁。
            if self._i_requested_restart:
                # 我也刚发起过重开：保持"本地先手"的约定不锁
                self._i_requested_restart = False
                self._restart_proposed_next_session = None
                self._session_id = next_sid
                self._i_start_first = True
                self._board.clear_board()
                self._game_over = False
                self._i_requested_undo = False
                self._local_undo_applied = False
                self._board.set_locked(False)
                self._status("双方同时重新开局，你先手（黑棋）")
            else:
                # 对方单方发起重开：对方先手 → 本地锁
                self._session_id = next_sid
                self._i_start_first = False
                self._board.clear_board()
                self._game_over = False
                self._i_requested_undo = False
                self._local_undo_applied = False
                self._board.set_locked(True)
                self._status("对方发起重新开局，等待对方先手")
            self._sync_lock()

    def _handle_undo_request(self) -> None:
        """响应对方的悔棋请求。"""
        btn = QMessageBox.question(self, "悔棋请求", "对方想悔棋，同意吗？")
        if btn == QMessageBox.Yes:
            if self._hub and self._session_id:
                self._hub.send_event("gomoku_ctrl", {
                    "kind": "undo_approve",
                    "session_id": self._session_id,
                }, silent=True)
            self._board.undo_last(2)
            self._local_undo_applied = True
            self._game_over = False
            # 对方悔棋 → 对方被撤一步 → 还是对方先下（锁定等待）
            self._board.set_locked(True)
            self._status("你同意了悔棋，等待对方落子")
        else:
            if self._hub and self._session_id:
                self._hub.send_event("gomoku_ctrl", {
                    "kind": "undo_reject",
                    "session_id": self._session_id,
                }, silent=True)
            self._sync_lock()
            if self._board.current_color() == 1:
                self._status("你拒绝了悔棋，轮到你落子")
            else:
                self._status("你拒绝了悔棋，等待对方落子")

    # ---------- 工具栏按钮 ----------

    def _on_undo(self) -> None:
        if self._game_over:
            QMessageBox.information(self, "悔棋", "对局已结束")
            return
        if self._hub is None or self._session_id is None:
            # 本地双人：直接悔两手
            self._board.undo_last(2)
            self._sync_lock()
            cur = "黑" if self._board.current_color() == 1 else "白"
            self._status(f"已悔棋，轮到 {cur} 落子")
            return
        if self._i_requested_undo:
            return
        self._i_requested_undo = True
        self._hub.send_event("gomoku_ctrl", {
            "kind": "undo_request",
            "session_id": self._session_id,
        }, silent=True)
        self._board.set_locked(True)
        self._status("已发送悔棋请求…")

    def _on_restart(self) -> None:
        self._board.clear_board()
        self._game_over = False
        self._i_requested_undo = False
        self._local_undo_applied = False
        if self._hub:
            next_sid = _new_id("ses-")
            self._i_requested_restart = True
            self._restart_proposed_next_session = next_sid
            self._hub.send_event("gomoku_ctrl", {
                "kind": "restart",
                "session_id": self._session_id,
                "next_session_id": next_sid,
            }, silent=True)
            # 切换到新会话
            self._session_id = next_sid
            # 重开后本地默认按「我先手」处理；若对方非并发重开，
            # 我们收到对方 restart 时会根据守卫正确切回锁状态
            self._i_start_first = True
            self._board.set_locked(False)
            self._status("已重新开局，你先手（黑棋）")
            # 30s 后清掉 _i_requested_restart，防止下一局迟到的 restart
            # 被误判为"双方同时重开"
            QTimer.singleShot(30_000, self._clear_restart_flag)
        else:
            self._i_start_first = True
            self._sync_lock()
            self._status("已重新开局")

    def _clear_restart_flag(self) -> None:
        self._i_requested_restart = False
        self._restart_proposed_next_session = None

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

    # ---------- 显示事件（不再用作邀请！） ----------

    def showEvent(self, event) -> None:
        super().showEvent(event)
        # 旧版本在 showEvent 发 kind=open 当"邀请"用，会让对方未确认就弹出，
        # 并且和 show() 互相 ping-pong。现在邀请只走「邀请对方」按钮+协议。
        if self._suppress_open_show_event:
            return
        if self._hub and self._session_id:
            # 我刚打开 / 从最小化还原，发一个 ready 让对方知道我在线，
            # 不含状态副作用
            self._hub.send_event("gomoku_ctrl", {
                "kind": "ready",
                "session_id": self._session_id,
            }, silent=True)
