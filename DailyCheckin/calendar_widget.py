"""月历组件：7x6 网格显示当月打卡情况。"""
from __future__ import annotations

import calendar as _cal
from datetime import date

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QGridLayout, QHBoxLayout, QLabel, QPushButton, QWidget,
)

from . import store

_WEEK_HEADERS = ["一", "二", "三", "四", "五", "六", "日"]


class CalendarWidget(QWidget):
    """月历组件，发出 day_clicked(YYYY-MM-DD) 信号。"""

    day_clicked = Signal(str)

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._year = date.today().year
        self._month = date.today().month
        self._day_labels: list[QPushButton] = []
        self._build_ui()
        self.refresh()

    def _build_ui(self) -> None:
        layout = QGridLayout(self)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(5)

        # 顶部月份切换
        self._prev_btn = QPushButton("◀", self)
        self._prev_btn.setFixedWidth(36)
        self._prev_btn.setStyleSheet(
            "QPushButton{border:none; font-size:16px; color:#d84f68;}"
            "QPushButton:hover{color:#b83d54;}"
        )
        self._prev_btn.clicked.connect(self._prev_month)

        self._month_label = QLabel("", self)
        self._month_label.setAlignment(Qt.AlignCenter)
        self._month_label.setStyleSheet(
            "font-size:17px; font-weight:700; color:#263238;"
        )

        self._next_btn = QPushButton("▶", self)
        self._next_btn.setFixedWidth(36)
        self._next_btn.setStyleSheet(
            "QPushButton{border:none; font-size:16px; color:#d84f68;}"
            "QPushButton:hover{color:#b83d54;}"
        )
        self._next_btn.clicked.connect(self._next_month)

        nav = QHBoxLayout()
        nav.setSpacing(8)
        nav.addWidget(self._prev_btn)
        nav.addWidget(self._month_label, 1)
        nav.addWidget(self._next_btn)
        layout.addLayout(nav, 0, 0, 1, 7)

        # 星期表头
        for col, header in enumerate(_WEEK_HEADERS):
            lbl = QLabel(header, self)
            lbl.setAlignment(Qt.AlignCenter)
            lbl.setStyleSheet("color:#7b8794; font-size:12px; padding:4px;")
            layout.addWidget(lbl, 1, col)

        # 6 行 x 7 列 日期格
        for row in range(6):
            for col in range(7):
                cell = QPushButton("", self)
                cell.setFixedSize(64, 56)
                cell.setStyleSheet(self._cell_style(False, False))
                cell.clicked.connect(
                    lambda _, r=row, c=col: self._on_cell_clicked(r, c)
                )
                layout.addWidget(cell, row + 2, col)
                self._day_labels.append(cell)

    @staticmethod
    def _cell_style(is_today: bool, has_record: bool, has_partner: bool = False) -> str:
        border = "2px solid #e85d75" if is_today else "1px solid #dfe5ec"
        if is_today:
            bg = "#fff0f3"
        elif has_partner and has_record:
            bg = "#f2eff8"  # 双方都有：粉紫
        elif has_partner:
            bg = "#eef5f7"  # 仅 TA：淡蓝
        elif has_record:
            bg = "#fff8f9"  # 仅自己：淡粉
        else:
            bg = "#fff"
        return (
            f"QPushButton{{border:{border}; border-radius:8px;"
            f"background:{bg}; font-size:16px; color:#333;}}"
            f"QPushButton:hover{{background:#fff0f3;}}"
        )

    def _prev_month(self) -> None:
        m = self._month - 1
        if m < 1:
            m = 12
            self._year -= 1
        self.set_month(self._year, m)

    def _next_month(self) -> None:
        m = self._month + 1
        if m > 12:
            m = 1
            self._year += 1
        self.set_month(self._year, m)

    def set_month(self, year: int, month: int) -> None:
        self._year = year
        self._month = month
        self.refresh()

    def refresh(self) -> None:
        """重绘当前月。"""
        self._month_label.setText(f"{self._year}年{self._month}月")
        first_weekday = _cal.monthrange(self._year, self._month)[0]  # 0=Monday
        days_in_month = _cal.monthrange(self._year, self._month)[1]
        today = date.today()

        first_of_month = date(self._year, self._month, 1).isoformat()
        last_of_month = date(self._year, self._month, days_in_month).isoformat()
        records = store.get_range(first_of_month, last_of_month)
        mood_by_date = {r["date"]: r["mood"] for r in records}
        partner_by_date = {
            r["date"]: r["mood"]
            for r in store.get_partner_range(first_of_month, last_of_month)
        }

        idx = 0
        for row in range(6):
            for col in range(7):
                cell = self._day_labels[idx]
                day_num = row * 7 + col - first_weekday + 1
                if 1 <= day_num <= days_in_month:
                    cell_date = date(self._year, self._month, day_num)
                    date_str = cell_date.isoformat()
                    mood = mood_by_date.get(date_str)
                    has_partner = date_str in partner_by_date
                    emoji = store.MOOD_MAP.get(mood, "") if mood else ""
                    line2 = emoji
                    if has_partner:
                        line2 = (line2 + " " if line2 else "") + "🔵"
                    if line2:
                        cell.setText(f"{day_num}\n{line2}")
                        cell.setStyleSheet(self._cell_style(
                            cell_date == today, bool(mood), has_partner))
                    else:
                        cell.setText(str(day_num))
                        cell.setStyleSheet(self._cell_style(
                            cell_date == today, False, has_partner))
                    cell.setProperty("date", date_str)
                else:
                    cell.setText("")
                    cell.setStyleSheet(
                        "QPushButton{border:none; background:transparent;}"
                    )
                    cell.setProperty("date", "")
                idx += 1

    def _on_cell_clicked(self, row: int, col: int) -> None:
        idx = row * 7 + col
        date_str = self._day_labels[idx].property("date")
        if date_str:
            self.day_clicked.emit(date_str)
