"""读信弹窗：仪式感地展示一封完整信件（含附件图片）。"""
from __future__ import annotations

from datetime import datetime
from io import BytesIO

from PIL import Image
from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QPixmap
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QPushButton,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from common_utils import check_attachment_size, log_exception, log_warning

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
        self._meta = meta  # 始终初始化，meta 不存在则为 None，保证后续方法不 AttributeError

        self.setWindowTitle("一封信" if meta is None else f"一封信 · {meta['title']}")
        self.resize(640, 720)
        self.setMinimumSize(560, 620)

        # 滚动容器，长信/大图也能看
        scroll = QScrollArea(self)
        scroll.setWidgetResizable(True)
        inner = QWidget()
        scroll.setWidget(inner)
        self.setCentralWidget(scroll)

        layout = QVBoxLayout(inner)
        layout.setContentsMargins(28, 24, 28, 24)
        layout.setSpacing(10)

        # meta 不存在：最小 UI 提示，避免残破窗口后访问 self._meta 抛 AttributeError
        if meta is None:
            tip = QLabel("这封信不存在（可能已删除）。", self)
            tip.setStyleSheet("font-size:16px; color:#7b8794; padding:40px 0;")
            tip.setAlignment(Qt.AlignCenter)
            layout.addWidget(tip)
            layout.addStretch(1)
            close_btn = QPushButton("关闭", self)
            close_btn.setStyleSheet(
                "QPushButton{background:#263238;color:#fff;border:none;"
                "border-radius:6px;padding:10px;font-size:14px;}"
                "QPushButton:hover{background:#37474f;}"
            )
            close_btn.clicked.connect(self.close)
            layout.addWidget(close_btn)
            return

        # 信头
        title_lbl = QLabel(meta["title"], self)
        title_lbl.setStyleSheet("font-size:24px; font-weight:700; color:#263238;")
        title_lbl.setWordWrap(True)
        layout.addWidget(title_lbl)

        created = datetime.fromisoformat(meta["created_at"]).strftime("%Y-%m-%d %H:%M")
        meta_lbl = QLabel(
            f"{meta['author']}  →  {meta['recipient']}    写于 {created}",
            self,
        )
        meta_lbl.setStyleSheet("color:#7b8794; font-size:13px;")
        layout.addWidget(meta_lbl)

        # 分隔
        sep = QFrame(self)
        sep.setFrameShape(QFrame.HLine)
        sep.setFrameShadow(QFrame.Sunken)
        sep.setStyleSheet("color:#dfe5ec;")
        layout.addWidget(sep)

        # 正文
        body_title = QLabel("正文", self)
        body_title.setStyleSheet("color:#52616d;font-size:13px;font-weight:600;")
        layout.addWidget(body_title)
        content = letter_store.read_content(letter_id)
        body = QLabel(content, self)
        body.setWordWrap(True)
        body.setTextInteractionFlags(Qt.TextSelectableByMouse)
        body.setStyleSheet(
            "background:#ffffff;border:1px solid #edf1f5;border-radius:8px;"
            "padding:16px;font-size:15px;line-height:160%;color:#263238;"
        )
        layout.addWidget(body)

        # 附件
        if meta["has_attachment"]:
            attachment_title = QLabel("附件", self)
            attachment_title.setStyleSheet(
                "color:#52616d;font-size:13px;font-weight:600;margin-top:4px;"
            )
            layout.addWidget(attachment_title)
            att = letter_store.read_attachment(letter_id)
            if att:
                # 附件大小校验：超限直接拒绝渲染，避免大图卡顿/OOM
                size_err = check_attachment_size(att)
                if size_err is not None:
                    log_warning("附件过大，拒绝显示: %s", size_err)
                    layout.addWidget(QLabel("(附件过大，无法显示)", self))
                else:
                    try:
                        with Image.open(BytesIO(att)) as pil:
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
                        img_lbl.setStyleSheet(
                            "QLabel{background:#ffffff;border:1px solid #dfe5ec;"
                            "border-radius:8px;padding:6px;}"
                        )
                        layout.addWidget(img_lbl)
                    except Exception:
                        log_exception("附件渲染失败")
                        layout.addWidget(QLabel("(附件无法显示)", self))

        layout.addStretch(1)

        # 按钮行：写回信 + 收好这封信
        btn_row = QHBoxLayout()
        reply_btn = QPushButton("写回信", self)
        reply_btn.setStyleSheet(
            "QPushButton{background:#ffffff;color:#d84f68;border:1px solid #e8a0ad;"
            "border-radius:6px;padding:10px 16px;font-size:14px;}"
            "QPushButton:hover{background:#fff0f3;}"
        )
        reply_btn.clicked.connect(self._on_reply)
        btn_row.addWidget(reply_btn)

        close_btn = QPushButton("收好这封信", self)
        close_btn.setStyleSheet(
            "QPushButton{background:#e85d75;color:#fff;border:none;"
            "border-radius:6px;padding:10px 16px;font-size:14px;font-weight:600;}"
            "QPushButton:hover{background:#d94f68;}"
        )
        close_btn.clicked.connect(self.close)
        btn_row.addWidget(close_btn)
        layout.addLayout(btn_row)

        # 打开即标记已读
        letter_store.mark_read(letter_id)

    def _on_reply(self) -> None:
        m = self._meta
        if m is None:
            return
        # 回信：寄信人=原收件人，收信人=原寄信人，标题 Re: 原标题
        self.reply_requested.emit(m["recipient"], m["author"], f"Re: {m['title']}")
