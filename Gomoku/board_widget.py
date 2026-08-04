"""五子棋棋盘组件：15×15 网格，自绘棋盘与棋子。

棋子编码：0 空 / 1 黑 / 2 白。黑先。
本地玩家始终为黑，对方落子为白（由 game_window 控制）。
"""
from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QColor, QPainter, QPen
from PySide6.QtWidgets import QWidget

SIZE = 15                                    # 15 条线
CELL = 40                                    # 每格像素
MARGIN = 20                                  # 棋盘边距
WIDGET = MARGIN * 2 + (SIZE - 1) * CELL      # 600

# 棋盘星位（天元 + 四角星）
_STARS = [(3, 3), (3, 11), (7, 7), (11, 3), (11, 11)]


class GomokuBoard(QWidget):
    """五子棋棋盘。"""

    stone_placed = Signal(int, int, int)   # row, col, color(1黑/2白)
    game_over = Signal(str)                # "black"/"white"

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setFixedSize(WIDGET, WIDGET)
        self._grid: list[list[int]] = [[0] * SIZE for _ in range(SIZE)]
        self._moves: list[tuple[int, int, int]] = []
        self._current = 1   # 黑先
        self._locked = False
        self._winner = 0

    # ---------- 绘制 ----------

    def paintEvent(self, event) -> None:
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing, True)
        # 木质背景
        p.fillRect(self.rect(), QColor(222, 184, 135))
        # 网格线
        p.setPen(QPen(QColor(60, 40, 20), 1))
        for i in range(SIZE):
            pos = MARGIN + i * CELL
            p.drawLine(pos, MARGIN, pos, MARGIN + (SIZE - 1) * CELL)
            p.drawLine(MARGIN, pos, MARGIN + (SIZE - 1) * CELL, pos)
        # 星位
        p.setBrush(QColor(60, 40, 20))
        p.setPen(Qt.NoPen)
        for r, c in _STARS:
            cx = MARGIN + c * CELL
            cy = MARGIN + r * CELL
            p.drawEllipse(cx - 3, cy - 3, 6, 6)
        # 棋子
        for r in range(SIZE):
            for c in range(SIZE):
                color = self._grid[r][c]
                if color:
                    self._draw_stone(p, r, c, color)

    def _draw_stone(self, p: QPainter, row: int, col: int, color: int) -> None:
        cx = MARGIN + col * CELL
        cy = MARGIN + row * CELL
        radius = int(CELL * 0.42)
        if color == 1:   # 黑
            p.setBrush(QColor(30, 30, 30))
            p.setPen(QPen(QColor(0, 0, 0), 1))
        else:            # 白
            p.setBrush(QColor(245, 245, 245))
            p.setPen(QPen(QColor(120, 120, 120), 1))
        p.drawEllipse(cx - radius, cy - radius, radius * 2, radius * 2)

    # ---------- 鼠标 ----------

    def mousePressEvent(self, event) -> None:
        if self._locked:
            return
        pos = event.position()
        col = round((pos.x() - MARGIN) / CELL)
        row = round((pos.y() - MARGIN) / CELL)
        if not (0 <= row < SIZE and 0 <= col < SIZE):
            return
        if self._grid[row][col] != 0:
            return
        self._on_click(row, col)

    def _on_click(self, row: int, col: int) -> None:
        """本地点击落子：放置后发出 stone_placed 信号。"""
        color = self._current
        self.place_stone(row, col, color)
        self.stone_placed.emit(row, col, color)

    # ---------- 公共接口 ----------

    def place_stone(self, row: int, col: int, color: int) -> None:
        """落子（本地或远端）：写入网格、切换回合、判定胜负。"""
        if not (0 <= row < SIZE and 0 <= col < SIZE):
            return
        if self._grid[row][col] != 0:
            return
        self._grid[row][col] = color
        self._moves.append((row, col, color))
        self._current = 2 if color == 1 else 1
        self.update()
        winner = self._check_win(row, col)
        if winner:
            self._winner = winner
            self._locked = True
            self.game_over.emit("black" if winner == 1 else "white")

    def _check_win(self, row: int, col: int) -> int:
        """从 (row, col) 出发检查 4 个方向是否五连，返回胜方颜色或 0。"""
        color = self._grid[row][col]
        if color == 0:
            return 0
        for dr, dc in ((0, 1), (1, 0), (1, 1), (1, -1)):
            count = 1
            r, c = row + dr, col + dc
            while 0 <= r < SIZE and 0 <= c < SIZE and self._grid[r][c] == color:
                count += 1
                r += dr
                c += dc
            r, c = row - dr, col - dc
            while 0 <= r < SIZE and 0 <= c < SIZE and self._grid[r][c] == color:
                count += 1
                r -= dr
                c -= dc
            if count >= 5:
                return color
        return 0

    def clear_board(self) -> None:
        """清空棋盘，黑方回合。"""
        self._grid = [[0] * SIZE for _ in range(SIZE)]
        self._moves = []
        self._current = 1
        self._locked = False
        self._winner = 0
        self.update()

    def undo_last(self, n: int = 1) -> None:
        """撤销最近 n 手。"""
        for _ in range(n):
            if not self._moves:
                break
            r, c, _color = self._moves.pop()
            self._grid[r][c] = 0
        self._current = 1 if len(self._moves) % 2 == 0 else 2
        self._winner = 0
        self.update()

    def set_locked(self, locked: bool) -> None:
        self._locked = locked

    def current_color(self) -> int:
        return self._current

    def get_moves(self) -> list[tuple[int, int, int]]:
        return list(self._moves)
