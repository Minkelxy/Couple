"""统计看板：在一起天数、信件总数、未读数、照片数、下个纪念日倒计时。"""
from __future__ import annotations
from datetime import datetime, date
from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QGridLayout, QHBoxLayout, QLabel, QMainWindow, QPushButton,
    QVBoxLayout, QWidget,
)

import app_paths
from DesktopPhotoFrame import config as pf_config
from DesktopPhotoFrame import image_processor as ip
from DesktopMailbox import config as mb_config
from DesktopMailbox import letter_store


def _calc_days_together() -> int:
    """计算在一起天数。优先用 suite.json 的 together_since，否则用最早信件日期，否则 0。"""
    suite = app_paths.load_suite()
    since = suite.get("together_since")
    if since:
        try:
            d = datetime.fromisoformat(since).date()
            return max(0, (date.today() - d).days)
        except ValueError:
            pass
    # 回退：取最早信件的 created_at
    items = letter_store.list_letters(include_unsent=True)
    if items:
        earliest = min(it["created_at"] for it in items)
        try:
            d = datetime.fromisoformat(earliest).date()
            return max(0, (date.today() - d).days)
        except ValueError:
            pass
    return 0


def _next_anniversary() -> tuple[str, int] | None:
    """返回 (描述, 距今天数)，无则 None。合并相框和信箱的纪念日。"""
    today = date.today()
    candidates: list[tuple[str, date]] = []
    
    # 相框纪念日（MM-DD 字符串列表）
    pf_cfg = pf_config.load()
    for md in pf_cfg.get("anniversaries", []):
        try:
            month, day = md.split("-")
            d = date(today.year, int(month), int(day))
            if d < today:
                d = date(today.year + 1, int(month), int(day))
            candidates.append((md, d))
        except (ValueError, IndexError):
            continue
    
    # 信箱纪念日（dict 列表，含 date/title）
    mb_cfg = mb_config.load()
    for anniv in mb_cfg.get("anniversaries", []):
        if not isinstance(anniv, dict):
            continue
        md = anniv.get("date", "")
        title = anniv.get("title", md)
        try:
            month, day = md.split("-")
            d = date(today.year, int(month), int(day))
            if d < today:
                d = date(today.year + 1, int(month), int(day))
            candidates.append((title, d))
        except (ValueError, IndexError):
            continue
    
    if not candidates:
        return None
    candidates.sort(key=lambda x: x[1])
    nearest_name, nearest_date = candidates[0]
    days = (nearest_date - today).days
    return (nearest_name, days)


class StatsWindow(QMainWindow):
    """统计看板窗口。"""

    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle("统计看板")
        self.resize(520, 420)
        self.setMinimumSize(460, 380)
        # 保存子控件引用，refresh() 时重设数据
        self._cards: list[tuple[QLabel, QLabel]] = []
        self._build_ui()
        self.refresh()

    def _build_ui(self) -> None:
        central = QWidget(self)
        self.setCentralWidget(central)
        layout = QVBoxLayout(central)
        layout.setContentsMargins(28, 24, 28, 24)
        layout.setSpacing(8)

        title = QLabel("我们的日常", self)
        title.setStyleSheet("font-size:24px; font-weight:700; color:#263238;")
        layout.addWidget(title)
        subtitle = QLabel("把一起生活的片段，留在看得见的地方", self)
        subtitle.setStyleSheet("color:#7b8794; font-size:13px;")
        layout.addWidget(subtitle)

        grid = QGridLayout()
        grid.setContentsMargins(0, 16, 0, 8)
        grid.setHorizontalSpacing(12)
        grid.setVerticalSpacing(12)
        cards = (
            ("在一起", "#e85d75"),
            ("信件", "#2a9d8f"),
            ("照片", "#4d7ea8"),
            ("下个纪念日", "#c58b36"),
        )
        for index, (label, accent) in enumerate(cards):
            card, value_lbl = self._make_card(label, "", accent)
            card.setToolTip({
                "在一起": "从共同开始日期计算的相处天数",
                "信件": "已保存的信件总数和未读数量",
                "照片": "当前相框相册中的照片数量",
                "下个纪念日": "距离最近纪念日的剩余天数",
            }.get(label, ""))
            self._cards.append(value_lbl)
            grid.addWidget(card, index // 2, index % 2)
        layout.addLayout(grid, 1)

        refresh_btn = QPushButton("刷新数据", self)
        refresh_btn.setStyleSheet(
            "QPushButton{background:#ffffff;color:#d84f68;"
            "border:1px solid #e8a0ad;border-radius:6px;"
            "padding:9px 16px;font-size:14px;}"
            "QPushButton:hover{background:#fff0f3;}"
        )
        refresh_btn.setToolTip("重新计算信件、照片和纪念日统计")
        refresh_btn.clicked.connect(self.refresh)

        close_btn = QPushButton("关闭", self)
        close_btn.setStyleSheet(
            "QPushButton{background:#263238;color:#fff;border:none;"
            "border-radius:6px;padding:9px 22px;font-size:14px;}"
            "QPushButton:hover{background:#37474f;}"
        )
        close_btn.clicked.connect(self.close)
        button_row = QHBoxLayout()
        button_row.addStretch(1)
        button_row.addWidget(refresh_btn)
        button_row.addWidget(close_btn)
        layout.addLayout(button_row)

    def refresh(self) -> None:
        """重新计算各项统计并更新卡片文本。避免手动调用 __init__ 造成的
        QMainWindow 二次构造（未定义行为 + 尺寸复位 + central 内存泄漏）。"""
        days = _calc_days_together()
        letters = letter_store.list_letters(include_unsent=True)
        unread = letter_store.count_unread()
        images = ip.list_images(pf_config.load().get("image_dir", ""))
        next_anniv = _next_anniversary()

        if self._cards:
            self._cards[0].setText(f"{days} 天")
            self._cards[1].setText(f"{len(letters)} 封（未读 {unread}）")
            self._cards[2].setText(f"{len(images)} 张")
            if next_anniv:
                name, days_left = next_anniv
                self._cards[3].setText(f"{name}（还有 {days_left} 天）")
            else:
                self._cards[3].setText("未设置纪念日")

    def _make_card(self, label: str, value: str, accent: str):
        card = QWidget(self)
        card.setObjectName("statCard")
        card.setStyleSheet(
            f"QWidget#statCard{{background:#ffffff;border:1px solid #dfe5ec;"
            f"border-top:3px solid {accent};border-radius:8px;}}"
        )
        cl = QVBoxLayout(card)
        cl.setContentsMargins(16, 14, 16, 12)
        cl.setSpacing(6)
        lbl = QLabel(label, card)
        lbl.setStyleSheet("color:#7b8794; font-size:13px; border:none;")
        val = QLabel(value, card)
        val.setWordWrap(True)
        val.setStyleSheet("font-size:19px; font-weight:700; color:#263238; border:none;")
        cl.addWidget(lbl)
        cl.addWidget(val)
        cl.addStretch(1)
        card.setMinimumHeight(112)
        return card, val
