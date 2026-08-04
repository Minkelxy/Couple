"""写信窗口：标题 / 正文 / 图片附件 / 送达时间。"""
from __future__ import annotations

from datetime import datetime, timedelta
from pathlib import Path

from PySide6.QtCore import QDateTime, Qt, Signal
from PySide6.QtWidgets import (
    QComboBox,
    QDateTimeEdit,
    QFileDialog,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QSpinBox,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from . import config
from . import letter_store


class ComposeWindow(QMainWindow):
    sent = Signal()  # 寄出后通知外部刷新

    def __init__(self, sync_hub=None) -> None:
        super().__init__()
        self.setWindowTitle("写一封信 ✉")
        self.resize(560, 620)
        self._attachment_bytes: bytes | None = None
        self._attachment_ext: str = ""
        self._sync = sync_hub
        self._build_ui()

    def prefill(
        self,
        *,
        author: str = "",
        recipient: str = "",
        title: str = "",
        body_prefix: str = "",
    ) -> None:
        """回信场景预填：收件人=原信作者，标题 Re:，可选引用正文。"""
        if author:
            self._author.setText(author)
        if recipient:
            self._recipient.setText(recipient)
        if title:
            self._title.setText(title)
        if body_prefix:
            self._body.setPlainText(body_prefix)
            # 光标移到末尾
            cur = self._body.textCursor()
            cur.movePosition(cur.End)
            self._body.setTextCursor(cur)
        # 回信默认立即送达
        self._preset.setCurrentIndex(0)

    def _build_ui(self) -> None:
        cfg = config.load()
        central = QWidget(self)
        self.setCentralWidget(central)
        root = QVBoxLayout(central)
        root.setContentsMargins(18, 18, 18, 18)
        root.setSpacing(10)

        # 角色行：我 → 你
        role_row = QHBoxLayout()
        self._author = QLineEdit(cfg["my_name"], self)
        self._author.setPlaceholderText("寄信人")
        arrow = QLabel("→", self)
        arrow.setAlignment(Qt.AlignCenter)
        self._recipient = QLineEdit(cfg["their_name"], self)
        self._recipient.setPlaceholderText("收信人")
        role_row.addWidget(QLabel("寄:", self))
        role_row.addWidget(self._author, 1)
        role_row.addWidget(arrow)
        role_row.addWidget(QLabel("收:", self))
        role_row.addWidget(self._recipient, 1)
        root.addLayout(role_row)

        # 标题
        self._title = QLineEdit(self)
        self._title.setPlaceholderText("给这封信起个标题…")
        root.addWidget(self._title)

        # 正文
        self._body = QTextEdit(self)
        self._body.setPlaceholderText("写点什么吧，时间到了对方才会看到…")
        root.addWidget(self._body, 1)

        # 附件
        att_row = QHBoxLayout()
        self._att_btn = QPushButton("📎 添加图片", self)
        self._att_btn.clicked.connect(self._pick_attachment)
        self._att_label = QLabel("未选择附件", self)
        self._att_label.setStyleSheet("color:#888;")
        self._clear_att = QPushButton("移除", self)
        self._clear_att.clicked.connect(self._clear_attachment)
        self._clear_att.setVisible(False)
        att_row.addWidget(self._att_btn)
        att_row.addWidget(self._att_label, 1)
        att_row.addWidget(self._clear_att)
        root.addLayout(att_row)

        # 送达时间：预设 + 自定义
        time_form = QFormLayout()
        self._preset = QComboBox(self)
        self._preset.addItems([
            "立即送达",
            "1 小时后",
            "明天早上 8:00",
            "3 天后",
            "一周后",
            "自定义…",
        ])
        self._preset.currentIndexChanged.connect(self._on_preset_changed)
        self._dt = QDateTimeEdit(QDateTime.currentDateTime(), self)
        self._dt.setCalendarPopup(True)
        self._dt.setDisplayFormat("yyyy-MM-dd HH:mm")
        self._dt.setVisible(False)
        time_form.addRow("送达时间:", self._preset)
        time_form.addRow("", self._dt)
        root.addLayout(time_form)

        # 寄出按钮
        self._send_btn = QPushButton("💌 寄出", self)
        self._send_btn.setStyleSheet(
            "QPushButton{background:#e65a7a;color:#fff;border:none;"
            "border-radius:8px;padding:12px;font-size:15px;}"
            "QPushButton:hover{background:#d94a6a;}"
        )
        self._send_btn.clicked.connect(self._on_send)
        root.addWidget(self._send_btn)

    # ---------- 附件 ----------

    def _pick_attachment(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self, "选择图片", "",
            "图片 (*.jpg *.jpeg *.png *.bmp *.webp *.gif)"
        )
        if not path:
            return
        try:
            data = Path(path).read_bytes()
        except OSError as e:
            QMessageBox.warning(self, "读取失败", str(e))
            return
        self._attachment_bytes = data
        self._attachment_ext = Path(path).suffix
        self._att_label.setText(Path(path).name)
        self._clear_att.setVisible(True)

    def _clear_attachment(self) -> None:
        self._attachment_bytes = None
        self._attachment_ext = ""
        self._att_label.setText("未选择附件")
        self._clear_att.setVisible(False)

    # ---------- 送达时间 ----------

    def _on_preset_changed(self, idx: int) -> None:
        self._dt.setVisible(idx == 5)  # 自定义

    def _resolve_deliver_at(self) -> datetime | None:
        idx = self._preset.currentIndex()
        now = datetime.now()
        if idx == 0:
            return now
        if idx == 1:
            return now + timedelta(hours=1)
        if idx == 2:
            tmr = (now + timedelta(days=1)).replace(hour=8, minute=0, second=0, microsecond=0)
            return tmr
        if idx == 3:
            return now + timedelta(days=3)
        if idx == 4:
            return now + timedelta(weeks=1)
        # 自定义
        return self._dt.dateTime().toPython()

    # ---------- 寄出 ----------

    def _on_send(self) -> None:
        title = self._title.text().strip()
        content = self._body.toPlainText().strip()
        author = self._author.text().strip() or "我"
        recipient = self._recipient.text().strip() or "你"
        if not content:
            QMessageBox.information(self, "内容为空", "写点什么再寄出吧~")
            return
        deliver_at = self._resolve_deliver_at()
        if deliver_at is None:
            return

        letter_store.write_letter(
            author=author,
            recipient=recipient,
            title=title or "(无标题)",
            content=content,
            deliver_at=deliver_at,
            attachment_bytes=self._attachment_bytes,
            attachment_ext=self._attachment_ext,
        )
        # 同步给对方（异步，不阻塞 UI）
        if self._sync is not None:
            # write_letter 没返回 meta，补一个最小 meta 给同步用
            sync_meta = {
                "author": author,
                "recipient": recipient,
                "title": title or "(无标题)",
                "deliver_at": deliver_at.isoformat(timespec="minutes"),
            }
            self._sync.send_async(
                sync_meta, content, self._attachment_bytes, self._attachment_ext
            )
        # 记住角色名，下次默认值
        config.update(my_name=author, their_name=recipient)

        when = deliver_at.strftime("%Y-%m-%d %H:%M") if deliver_at > datetime.now() else "现在"
        QMessageBox.information(self, "已寄出 ✉", f"信件将在 {when} 送达。")
        self.sent.emit()
        self._clear_attachment()
        self._title.clear()
        self._body.clear()
        self.close()
