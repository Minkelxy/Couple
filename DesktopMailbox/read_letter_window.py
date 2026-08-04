"""读信弹窗：仪式感地展示一封完整信件（含附件图片）。"""
from __future__ import annotations

from datetime import datetime
from io import BytesIO

from PIL import Image
from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QPixmap
from PySide6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QPushButton,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from . import letter_store


class ReadLetterWindow(QMainWindow):
    """打开一封信：标记已读 + 展示正文 + 附件。"""

    reply_requested = Signal(str, str, str)  # author, recipient, title

    def __init__(self, letter_id: str) -> None:
        super().__init__()
        self._id = letter_id
        meta = next(
            (it for it in letter_store.list_letters() if it["id"] == letter_id),
            None,
        )
        if meta is None:
            self.close()
            return
        self._meta = meta

        self.setWindowTitle(f"一封信 ✉ · {meta['title']}")
        self.resize(640, 720)

        # 滚动容器，长信/大图也能看
        scroll = QScrollArea(self)
        scroll.setWidgetResizable(True)
        inner = QWidget()
        scroll.setWidget(inner)
        self.setCentralWidget(scroll)

        layout = QVBoxLayout(inner)
        layout.setContentsMargins(28, 24, 28, 24)
        layout.setSpacing(10)

        # 信头
        title_lbl = QLabel(meta["title"], self)
        title_lbl.setStyleSheet("font-size:22px; font-weight:600; color:#222;")
        title_lbl.setWordWrap(True)
        layout.addWidget(title_lbl)

        created = datetime.fromisoformat(meta["created_at"]).strftime("%Y-%m-%d %H:%M")
        meta_lbl = QLabel(
            f"{meta['author']}  →  {meta['recipient']}    写于 {created}",
            self,
        )
        meta_lbl.setStyleSheet("color:#888; font-size:13px;")
        layout.addWidget(meta_lbl)

        # 分隔
        sep = QLabel("—" * 30, self)
        sep.setStyleSheet("color:#ddd;")
        layout.addWidget(sep)

        # 正文
        content = letter_store.read_content(letter_id)
        body = QLabel(content, self)
        body.setWordWrap(True)
        body.setTextInteractionFlags(Qt.TextSelectableByMouse)
        body.setStyleSheet("font-size:15px; line-height:160%; color:#333;")
        layout.addWidget(body)

        # 附件
        if meta["has_attachment"]:
            att = letter_store.read_attachment(letter_id)
            if att:
                try:
                    pil = Image.open(BytesIO(att))
                    pil.load()
                    # 等比缩放到不超过窗口宽度
                    max_w = 580
                    if pil.width > max_w:
                        scale = max_w / pil.width
                        pil = pil.resize(
                            (max_w, int(pil.height * scale)), Image.LANCZOS
                        )
                    # PIL -> QPixmap
                    buf = BytesIO()
                    pil.save(buf, format="PNG")
                    pm = QPixmap()
                    pm.loadFromData(buf.getvalue())
                    img_lbl = QLabel(self)
                    img_lbl.setPixmap(pm)
                    img_lbl.setAlignment(Qt.AlignCenter)
                    layout.addWidget(img_lbl)
                except Exception as e:
                    layout.addWidget(QLabel(f"(附件无法显示: {e})", self))

        layout.addStretch(1)

        # 按钮行：写回信 + 收好这封信
        btn_row = QHBoxLayout()
        reply_btn = QPushButton("✍ 写回信", self)
        reply_btn.setStyleSheet(
            "QPushButton{background:#fff;color:#e65a7a;border:1px solid #e65a7a;"
            "border-radius:8px;padding:10px;font-size:14px;}"
            "QPushButton:hover{background:#fde8ee;}"
        )
        reply_btn.clicked.connect(self._on_reply)
        btn_row.addWidget(reply_btn)

        close_btn = QPushButton("收好这封信", self)
        close_btn.setStyleSheet(
            "QPushButton{background:#e65a7a;color:#fff;border:none;"
            "border-radius:8px;padding:10px;font-size:14px;}"
            "QPushButton:hover{background:#d94a6a;}"
        )
        close_btn.clicked.connect(self.close)
        btn_row.addWidget(close_btn)
        layout.addLayout(btn_row)

        # 打开即标记已读
        letter_store.mark_read(letter_id)

    def _on_reply(self) -> None:
        m = self._meta
        # 回信：寄信人=原收件人，收信人=原寄信人，标题 Re: 原标题
        self.reply_requested.emit(m["recipient"], m["author"], f"Re: {m['title']}")
