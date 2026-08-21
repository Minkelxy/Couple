"""收件箱 + 读信窗口。"""
from __future__ import annotations

from datetime import datetime
from io import BytesIO

from PIL import Image
from PySide6.QtCore import QByteArray, Qt, Signal
from PySide6.QtGui import QPixmap
from PySide6.QtWidgets import (
    QComboBox,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QSplitter,
    QTextBrowser,
    QVBoxLayout,
    QWidget,
)

from . import letter_store


class InboxWindow(QMainWindow):
    open_requested = Signal(str)  # 选中某封信时触发

    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle("信件箱")
        self.resize(900, 620)
        self.setMinimumSize(760, 520)
        self._mode = "inbox"  # inbox | drafts
        self._build_ui()

    def _build_ui(self) -> None:
        central = QWidget(self)
        self.setCentralWidget(central)
        root = QVBoxLayout(central)
        root.setContentsMargins(24, 20, 24, 20)
        root.setSpacing(10)

        header = QVBoxLayout()
        header.setSpacing(2)
        title = QLabel("信件箱", self)
        title.setStyleSheet("font-size:24px; font-weight:700; color:#263238;")
        subtitle = QLabel("把想说的话留在这里，按自己的节奏打开", self)
        subtitle.setStyleSheet("color:#7b8794; font-size:13px;")
        header.addWidget(title)
        header.addWidget(subtitle)
        root.addLayout(header)

        # 顶部：视图切换 + 状态 + 刷新
        top = QHBoxLayout()
        top.setSpacing(8)
        self._view_switch = QComboBox(self)
        self._view_switch.addItem("收件箱（已送达）", "inbox")
        self._view_switch.addItem("我的草稿（未送达）", "drafts")
        self._view_switch.currentIndexChanged.connect(self._on_view_changed)
        top.addWidget(self._view_switch)
        self._status = QLabel("加载中…", self)
        self._status.setStyleSheet("color:#7b8794; font-size:13px;")
        top.addWidget(self._status, 1)
        refresh = QPushButton("刷新", self)
        refresh.setToolTip("重新读取信件列表")
        refresh.clicked.connect(self.refresh)
        top.addWidget(refresh)
        root.addLayout(top)

        # 左侧列表 + 右侧预览
        splitter = QSplitter(Qt.Horizontal, self)
        self._list = QListWidget(self)
        self._list.setMinimumWidth(260)
        self._list.setAlternatingRowColors(True)
        self._list.setSpacing(2)
        self._list.setStyleSheet(
            "QListWidget{background:#ffffff;border:1px solid #dfe5ec;"
            "border-radius:8px;padding:4px;}"
            "QListWidget::item{padding:8px 7px;border-radius:5px;}"
            "QListWidget::item:hover{background:#fff7f8;}"
            "QListWidget::item:selected{background:#ffe8ed;color:#263238;}"
        )
        self._list.itemClicked.connect(self._on_item_clicked)
        self._preview = QTextBrowser(self)
        self._preview.setOpenExternalLinks(True)
        self._preview.setMinimumWidth(420)
        self._preview.setStyleSheet(
            "QTextBrowser{background:#ffffff;border:1px solid #dfe5ec;"
            "border-radius:8px;padding:10px;}"
        )
        splitter.addWidget(self._list)
        splitter.addWidget(self._preview)
        splitter.setStretchFactor(0, 1)
        splitter.setStretchFactor(1, 3)
        splitter.setHandleWidth(7)
        splitter.setChildrenCollapsible(False)
        root.addWidget(splitter, 1)

        # 底部按钮
        bottom = QHBoxLayout()
        self._open_btn = QPushButton("打开完整信件", self)
        self._open_btn.setEnabled(False)
        self._open_btn.clicked.connect(self._open_current)
        self._del_btn = QPushButton("删除", self)
        self._del_btn.setEnabled(False)
        self._del_btn.clicked.connect(self._delete_current)
        self._open_btn.setStyleSheet(
            "QPushButton{background:#e85d75;color:#fff;border:none;"
            "border-radius:6px;padding:9px 16px;font-weight:600;}"
            "QPushButton:hover{background:#d94f68;}"
        )
        self._del_btn.setStyleSheet(
            "QPushButton{padding:9px 16px;color:#b04a5a;"
            "border-color:#efcaca;background:#fff8f8;}"
            "QPushButton:hover{background:#fdeaea;}"
        )
        bottom.addStretch(1)
        bottom.addWidget(self._open_btn)
        bottom.addWidget(self._del_btn)
        root.addLayout(bottom)

    # ---------- 数据 ----------

    def _on_view_changed(self, _idx: int) -> None:
        self._mode = self._view_switch.currentData()
        # 切换时调整打开按钮可用性（草稿不可打开，只能撤回）
        self._open_btn.setText("打开完整信件" if self._mode == "inbox" else "草稿不可打开")
        self.refresh()

    def refresh(self) -> None:
        self._list.clear()
        if self._mode == "inbox":
            items = letter_store.list_letters(include_unsent=False)
            unread = sum(1 for it in items if not it["read"])
            self._status.setText(f"共 {len(items)} 封已送达，未读 {unread} 封")
            self._open_btn.setEnabled(False)
            self._del_btn.setText("删除")
        else:
            # 草稿：未送达信件
            now = datetime.now()
            all_items = letter_store.list_letters(include_unsent=True)
            items = [
                it for it in all_items
                if datetime.fromisoformat(it["deliver_at"]) > now
            ]
            self._status.setText(f"共 {len(items)} 封待送达草稿")
            self._open_btn.setEnabled(False)
            self._del_btn.setText("↩ 撤回删除")
        for it in items:
            ts = datetime.fromisoformat(it["deliver_at"]).strftime("%m-%d %H:%M")
            if self._mode == "inbox":
                prefix = "[未读] " if not it["read"] else "[已读] "
            else:
                prefix = "[草稿] "
            title = it["title"]
            att = " [附件]" if it["has_attachment"] else ""
            label = f"{prefix}{ts}  {it['author']}→{it['recipient']}  {title}{att}"
            item = QListWidgetItem(label)
            item.setData(Qt.UserRole, it["id"])
            self._list.addItem(item)
        self._preview.setText(
            "<div style='text-align:center;color:#aaa;padding:40px'>"
            "选择左侧信件查看预览"
            "</div>"
        )
        self._del_btn.setEnabled(False)

    # ---------- 交互 ----------

    def _on_item_clicked(self, item: QListWidgetItem) -> None:
        letter_id = item.data(Qt.UserRole)
        self._show_preview(letter_id)
        # 草稿模式不可打开，只能撤回
        self._open_btn.setEnabled(self._mode == "inbox")
        self._del_btn.setEnabled(True)

    def _show_preview(self, letter_id: str) -> None:
        # 找元数据（草稿模式需 include_unsent）
        meta = next(
            (it for it in letter_store.list_letters(include_unsent=True)
             if it["id"] == letter_id),
            None,
        )
        if meta is None:
            return
        content = letter_store.read_content(letter_id)
        created = datetime.fromisoformat(meta["created_at"]).strftime("%Y-%m-%d %H:%M")
        deliver = datetime.fromisoformat(meta["deliver_at"]).strftime("%Y-%m-%d %H:%M")
        html = (
            f"<h3 style='margin:0'>{_escape(meta['title'])}</h3>"
            f"<p style='color:#7b8794;margin:2px 0 8px'>"
            f"{_escape(meta['author'])} → {_escape(meta['recipient'])} · 写于 {_escape(created)}</p>"
            f"<p style='color:#d84f68;margin:2px 0 8px'>送达时间：{_escape(deliver)}</p>"
            f"<pre style='font-family:inherit;white-space:pre-wrap;margin:0'>"
            f"{_escape(content)}</pre>"
        )
        if meta["has_attachment"]:
            html += "<p style='color:#7b8794;margin-top:8px'>含附件</p>"
        self._preview.setHtml(html)

    def _open_current(self) -> None:
        if self._mode != "inbox":
            return
        item = self._list.currentItem()
        if item:
            self.open_requested.emit(item.data(Qt.UserRole))

    def _delete_current(self) -> None:
        item = self._list.currentItem()
        if not item:
            return
        letter_id = item.data(Qt.UserRole)
        tip = "撤回这封未送达的信吗？" if self._mode == "drafts" else "确定删除这封信吗？"
        if QMessageBox.question(self, "确认", tip) == QMessageBox.Yes:
            letter_store.delete_letter(letter_id)
            self.refresh()


def _escape(s: str) -> str:
    return (
        s.replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
    )
