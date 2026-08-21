"""写信窗口：标题 / 正文 / 图片附件 / 送达时间。"""
from __future__ import annotations

import uuid

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

from common_utils import check_attachment_size, friendly_error

from . import config
from . import letter_store


class ComposeWindow(QMainWindow):
    sent = Signal()  # 寄出后通知外部刷新
    toast = Signal(str)  # 请求外部托盘提示（参数=消息文本）

    def __init__(self, sync_hub=None) -> None:
        super().__init__()
        self.setWindowTitle("写一封信")
        self.resize(600, 680)
        self.setMinimumSize(540, 600)
        self._attachment_bytes: bytes | None = None
        self._attachment_ext: str = ""
        self._sync = sync_hub
        self._build_ui()

    def set_sync_hub(self, sync_hub) -> None:
        """设置变更时热更新同步引用（避免使用已停止的旧 hub）。"""
        self._sync = sync_hub

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
        root.setContentsMargins(28, 22, 28, 22)
        root.setSpacing(12)

        header = QVBoxLayout()
        header.setSpacing(2)
        heading = QLabel("写一封信", self)
        heading.setStyleSheet("font-size:24px; font-weight:700; color:#263238;")
        hint = QLabel("写下此刻的心情，选择合适的时间送达", self)
        hint.setStyleSheet("color:#7b8794; font-size:13px;")
        header.addWidget(heading)
        header.addWidget(hint)
        root.addLayout(header)

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
        title_label = QLabel("主题", self)
        title_label.setStyleSheet("font-weight:600; color:#52616d;")
        root.addWidget(title_label)
        self._title = QLineEdit(self)
        self._title.setPlaceholderText("给这封信起个标题…")
        self._title.setMinimumHeight(40)
        root.addWidget(self._title)

        # 正文
        body_label = QLabel("正文", self)
        body_label.setStyleSheet("font-weight:600; color:#52616d;")
        root.addWidget(body_label)
        self._body = QTextEdit(self)
        self._body.setPlaceholderText("写点什么吧，时间到了对方才会看到…")
        self._body.setMinimumHeight(260)
        self._body.setStyleSheet(
            "QTextEdit{background:#ffffff;border:1px solid #dfe5ec;"
            "border-radius:8px;padding:10px;font-size:15px;}"
            "QTextEdit:focus{border:1px solid #e85d75;}"
        )
        self._body.textChanged.connect(self._update_send_state)
        root.addWidget(self._body, 1)
        self._body_count = QLabel("当前 0 字", self)
        self._body_count.setStyleSheet("color:#9aa5b1;font-size:12px;")
        self._body_count.setAlignment(Qt.AlignRight)
        root.addWidget(self._body_count)

        # 附件
        attachment_label = QLabel("图片附件", self)
        attachment_label.setStyleSheet("font-weight:600; color:#52616d;")
        root.addWidget(attachment_label)
        att_row = QHBoxLayout()
        self._att_btn = QPushButton("添加图片", self)
        self._att_btn.setToolTip("为信件添加一张图片附件")
        self._att_btn.clicked.connect(self._pick_attachment)
        self._att_label = QLabel("未选择附件", self)
        self._att_label.setStyleSheet("color:#7b8794; font-size:13px;")
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
        self._custom_time_label = QLabel("自定义时间:", self)
        self._custom_time_label.setVisible(False)
        time_form.addRow("送达时间:", self._preset)
        time_form.addRow(self._custom_time_label, self._dt)
        root.addLayout(time_form)

        # 寄出按钮
        self._send_btn = QPushButton("寄出", self)
        self._send_btn.setEnabled(False)
        self._send_btn.setStyleSheet(
            "QPushButton{background:#e85d75;color:#fff;border:none;"
            "border-radius:6px;padding:12px;font-size:15px;font-weight:600;}"
            "QPushButton:hover{background:#d94f68;}"
        )
        self._send_btn.setToolTip("寄出信件（Ctrl+Enter）")
        self._send_btn.clicked.connect(self._on_send)
        root.addWidget(self._send_btn)

        # 快捷键：Ctrl+Enter 寄出
        from PySide6.QtGui import QShortcut, QKeySequence
        QShortcut(QKeySequence("Ctrl+Return"), self, activated=self._on_send)

    def _update_send_state(self) -> None:
        text = self._body.toPlainText()
        self._send_btn.setEnabled(bool(text.strip()))
        self._body_count.setText(f"当前 {len(text)} 字")

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
            QMessageBox.warning(self, "读取失败", friendly_error(e, "无法读取图片"))
            return
        # 附件大小校验：超限拒绝，避免同步/存储压力
        err = check_attachment_size(data)
        if err is not None:
            QMessageBox.warning(self, "附件过大",
                "图片大小超过了限制（上限 50 MB），请压缩后再添加")
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
        custom = idx == 5
        self._dt.setVisible(custom)
        self._custom_time_label.setVisible(custom)

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
        # Qt6 的 QDateTime.currentDateTime() 携带系统时区，toPython() 返回
        # aware datetime，与 datetime.now()（naive）比较会抛 TypeError。
        # 统一剥离时区，保持与预设分支（均为 naive）一致。
        dt = self._dt.dateTime().toPython()
        if dt.tzinfo is not None:
            dt = dt.replace(tzinfo=None)
        return dt

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

        message_id = uuid.uuid4().hex
        letter_store.write_letter(
            author=author,
            recipient=recipient,
            title=title or "(无标题)",
            content=content,
            deliver_at=deliver_at,
            attachment_bytes=self._attachment_bytes,
            attachment_ext=self._attachment_ext,
            message_id=message_id,
        )
        # 同步给对方（异步，不阻塞 UI）
        if self._sync is not None:
            # write_letter 没返回 meta，补一个最小 meta 给同步用
            sync_meta = {
                "author": author,
                "recipient": recipient,
                "title": title or "(无标题)",
                "deliver_at": deliver_at.isoformat(timespec="minutes"),
                "message_id": message_id,
            }
            self._sync.send_async(
                sync_meta, content, self._attachment_bytes, self._attachment_ext
            )
        # 记住角色名，下次默认值
        config.update(my_name=author, their_name=recipient)

        when = deliver_at.strftime("%Y-%m-%d %H:%M") if deliver_at > datetime.now() else "现在"
        # 寄出成功后用 toast 反馈，不弹模态对话框打断用户
        tip = f"信件将在 {when} 送达" if when != "现在" else "信件已寄出"
        self.toast.emit(tip)
        self.statusBar().showMessage(tip, 5000)

        self.sent.emit()
        # 清空内容但保持窗口打开，方便连续写信
        self._clear_attachment()
        self._title.clear()
        self._body.clear()
        self._title.setFocus()
