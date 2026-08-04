"""心情曲线：matplotlib 嵌入 QWidget 显示最近 30 天心情。"""
from __future__ import annotations

from datetime import datetime

from PySide6.QtWidgets import QVBoxLayout, QWidget

from matplotlib.figure import Figure
from matplotlib.backends.backend_qtagg import FigureCanvasQTAgg as FigureCanvas

PINK = "#e65a7a"
# Y 轴从下到上：1😴 2😡 3😢 4😍 5😊
# matplotlib 在 Windows 默认 YaHei 缺 emoji 字形会刷警告，
# 故 y 轴只用纯中文标签 + 颜色区分心情；emoji 保留在 Qt 控件里展示
MOOD_LABELS = {1: "困倦", 2: "愤怒", 3: "伤心", 4: "喜爱", 5: "开心"}
MOOD_COLORS = {1: "#7a8fa6", 2: "#e6745a", 3: "#5a9ad6", 4: "#e65a7a", 5: "#f0b850"}


class MoodChart(QWidget):
    """心情曲线组件。"""

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._fig = Figure(figsize=(5, 3), facecolor="none")
        self._canvas = FigureCanvas(self._fig)
        self._canvas.setStyleSheet("background: transparent;")
        layout = QVBoxLayout(self)
        layout.setContentsMargins(4, 4, 4, 4)
        layout.addWidget(self._canvas)
        self._ax = self._fig.add_subplot(111)
        self._setup_ax()
        self._canvas.draw()

    def _setup_ax(self) -> None:
        ax = self._ax
        ax.set_facecolor("none")
        ax.set_ylim(0.5, 5.5)
        ax.set_yticks([1, 2, 3, 4, 5])
        # 每个心情标签单独上色，emoji 缺字形警告已通过改纯中文标签消除
        ax.set_yticklabels(
            [MOOD_LABELS[i] for i in range(1, 6)], fontsize=10
        )
        for mood_val, label in zip(range(1, 6), ax.get_yticklabels()):
            label.set_color(MOOD_COLORS[mood_val])
        ax.tick_params(axis="x", labelsize=8, colors="#888")
        ax.tick_params(axis="y", colors="#888")
        for spine in ax.spines.values():
            spine.set_color("#ddd")
        ax.grid(True, linestyle="--", alpha=0.3, color="#ccc")

    def update_data(self, records: list[dict]) -> None:
        """用 records 列表刷新图表。

        records: [{'date':'YYYY-MM-DD','mood':1-5}, ...]
        """
        self._ax.clear()
        self._setup_ax()
        if not records:
            self._ax.set_title("暂无打卡记录", color="#999", fontsize=12)
            self._fig.tight_layout()
            self._canvas.draw()
            return
        items = sorted(records, key=lambda r: r["date"])
        dates = [datetime.strptime(r["date"], "%Y-%m-%d") for r in items]
        moods = [r["mood"] for r in items]
        self._ax.plot(
            dates, moods, color=PINK, marker="o", markersize=6,
            linewidth=2, markerfacecolor=PINK, markeredgecolor="white",
        )
        self._ax.set_title("最近心情趋势", color=PINK, fontsize=13)
        self._fig.autofmt_xdate(rotation=30)
        self._fig.tight_layout()
        self._canvas.draw()
