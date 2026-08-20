"""心情曲线：matplotlib 嵌入 QWidget 显示最近 30 天心情。"""
from __future__ import annotations

from datetime import datetime

from PySide6.QtWidgets import QVBoxLayout, QWidget

from matplotlib.figure import Figure
from matplotlib.backends.backend_qtagg import FigureCanvasQTAgg as FigureCanvas

from . import store

PINK = "#e85d75"
PARTNER_BLUE = "#4d7ea8"
# Y 轴从下到上：1😴 2😡 3😢 4😍 5😊
# matplotlib 在 Windows 默认 YaHei 缺 emoji 字形会刷警告，
# 故 y 轴只用纯中文标签 + 颜色区分心情；emoji 保留在 Qt 控件里展示
MOOD_LABELS = {1: "困倦", 2: "愤怒", 3: "伤心", 4: "喜爱", 5: "开心"}
MOOD_COLORS = {1: "#7b8794", 2: "#d9785d", 3: "#5f97b8", 4: "#e85d75", 5: "#c58b36"}


class MoodChart(QWidget):
    """心情曲线组件。"""

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._fig = Figure(figsize=(5, 3), facecolor="#ffffff")
        self._canvas = FigureCanvas(self._fig)
        self._canvas.setStyleSheet("background: transparent;")
        layout = QVBoxLayout(self)
        self.setObjectName("moodChart")
        self.setStyleSheet(
            "QWidget#moodChart{background:#ffffff;border:1px solid #dfe5ec;"
            "border-radius:8px;}"
        )
        layout.setContentsMargins(12, 10, 12, 10)
        layout.addWidget(self._canvas)
        self._ax = self._fig.add_subplot(111)
        self._setup_ax()
        self._canvas.draw()

    def _setup_ax(self) -> None:
        ax = self._ax
        ax.set_facecolor("#ffffff")
        ax.set_ylim(0.5, 5.5)
        ax.set_yticks([1, 2, 3, 4, 5])
        # 每个心情标签单独上色，emoji 缺字形警告已通过改纯中文标签消除
        ax.set_yticklabels(
            [MOOD_LABELS[i] for i in range(1, 6)], fontsize=10
        )
        for mood_val, label in zip(range(1, 6), ax.get_yticklabels()):
            label.set_color(MOOD_COLORS[mood_val])
        ax.tick_params(axis="x", labelsize=8, colors="#7b8794")
        ax.tick_params(axis="y", colors="#7b8794")
        for spine in ax.spines.values():
            spine.set_color("#dfe5ec")
        ax.grid(True, linestyle="--", alpha=0.35, color="#dfe5ec")

    def update_data(self, records: list[dict]) -> None:
        """用 records 列表刷新图表，同时绘制自己与对方两条折线。

        records: [{'date':'YYYY-MM-DD','mood':1-5}, ...]（自己的记录）
        对方记录由 store.get_partner_recent 读取。仅一方有数据时只画一方；
        双方均无数据时清空图表不报错。
        """
        self._ax.clear()
        self._setup_ax()
        # 自己与对方数据，按日期升序
        mine = sorted(records, key=lambda r: r["date"]) if records else []
        partner = sorted(store.get_partner_recent(30), key=lambda r: r["date"])
        if not mine and not partner:
            self._ax.set_title("暂无打卡记录", color="#7b8794", fontsize=12)
            self._fig.tight_layout()
            self._canvas.draw()
            return
        # 自己：粉色圆点
        if mine:
            dates = [datetime.strptime(r["date"], "%Y-%m-%d") for r in mine]
            moods = [r["mood"] for r in mine]
            self._ax.plot(
                dates, moods, color=PINK, marker="o", markersize=6,
                linewidth=2, markerfacecolor=PINK, markeredgecolor="white",
                label="我",
            )
        # 对方：蓝色方块
        if partner:
            p_dates = [datetime.strptime(r["date"], "%Y-%m-%d") for r in partner]
            p_moods = [r["mood"] for r in partner]
            self._ax.plot(
                p_dates, p_moods, color=PARTNER_BLUE, marker="s", markersize=6,
                linewidth=2, markerfacecolor=PARTNER_BLUE, markeredgecolor="white",
                label="对方",
            )
        self._ax.set_title("最近心情趋势", color="#263238", fontsize=13, fontweight="bold")
        self._ax.legend(loc="upper left", fontsize=10, frameon=False)
        self._fig.autofmt_xdate(rotation=30)
        self._fig.tight_layout()
        self._canvas.draw()
