"""统计看板：在一起天数、信件总数、未读数、照片数、下个纪念日倒计时。"""
from __future__ import annotations
from datetime import datetime, date
from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QLabel, QMainWindow, QVBoxLayout, QWidget, QPushButton

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
        self.setWindowTitle("统计看板 📊")
        self.resize(400, 380)
        self._build_ui()

    def _build_ui(self) -> None:
        central = QWidget(self)
        self.setCentralWidget(central)
        layout = QVBoxLayout(central)
        layout.setContentsMargins(28, 24, 28, 24)
        layout.setSpacing(16)

        title = QLabel("我们的数据 📊", self)
        title.setStyleSheet("font-size:20px; font-weight:600; color:#e65a7a;")
        layout.addWidget(title)

        # 计算各项数据
        days = _calc_days_together()
        letters = letter_store.list_letters(include_unsent=True)
        unread = letter_store.count_unread()
        images = ip.list_images(pf_config.load().get("image_dir", ""))
        next_anniv = _next_anniversary()

        # 卡片式展示
        layout.addWidget(self._make_card("💕 在一起", f"{days} 天"))
        layout.addWidget(self._make_card("✉ 信件总数", f"{len(letters)} 封（未读 {unread}）"))
        layout.addWidget(self._make_card("🖼 照片数量", f"{len(images)} 张"))
        
        if next_anniv:
            name, days_left = next_anniv
            layout.addWidget(self._make_card("🎉 下个纪念日", f"{name}（还有 {days_left} 天）"))
        else:
            layout.addWidget(self._make_card("🎉 下个纪念日", "未设置"))

        layout.addStretch(1)

        close_btn = QPushButton("关闭", self)
        close_btn.setStyleSheet(
            "QPushButton{background:#e65a7a;color:#fff;border:none;"
            "border-radius:8px;padding:10px;font-size:14px;}"
            "QPushButton:hover{background:#d94a6a;}"
        )
        close_btn.clicked.connect(self.close)
        layout.addWidget(close_btn)

    def _make_card(self, label: str, value: str) -> QWidget:
        card = QWidget(self)
        card.setStyleSheet(
            "QWidget{background:#fdf2f5; border-radius:10px;}"
        )
        cl = QVBoxLayout(card)
        cl.setContentsMargins(16, 12, 16, 12)
        lbl = QLabel(label, card)
        lbl.setStyleSheet("color:#888; font-size:13px; border:none;")
        val = QLabel(value, card)
        val.setStyleSheet("font-size:18px; font-weight:600; color:#333; border:none;")
        cl.addWidget(lbl)
        cl.addWidget(val)
        return card
