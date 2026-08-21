"""首次运行引导：设置双方昵称、图片目录、可选对方 IP。"""
from __future__ import annotations
from pathlib import Path

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QFileDialog, QHBoxLayout, QLabel, QLineEdit, QMainWindow,
    QPushButton, QVBoxLayout, QWidget, QCheckBox, QSpinBox,
)

import app_paths
from DesktopPhotoFrame import config as pf_config
from DesktopMailbox import config as mb_config


class OnboardingWindow(QMainWindow):
    """首次运行引导窗口。"""
    finished = Signal()  # 完成或跳过时发信号

    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle("欢迎使用桌面相册")
        self.resize(520, 500)
        self.setMinimumSize(480, 460)
        self._build_ui()

    def _build_ui(self) -> None:
        central = QWidget(self)
        self.setCentralWidget(central)
        root = QVBoxLayout(central)
        root.setContentsMargins(28, 24, 28, 24)
        root.setSpacing(10)

        # 标题
        title = QLabel("初次见面，简单设置一下", self)
        title.setStyleSheet("font-size:24px; font-weight:700; color:#263238;")
        root.addWidget(title)

        hint = QLabel("以下设置随时可在「设置」中修改。", self)
        hint.setStyleSheet("color:#7b8794; font-size:13px;")
        root.addWidget(hint)

        # 步骤1：昵称
        step_one = QLabel("01  昵称", self)
        step_one.setStyleSheet("font-size:15px; font-weight:700; color:#263238;")
        root.addWidget(step_one)
        name_row = QHBoxLayout()
        self._my_name = QLineEdit(self)
        self._my_name.setPlaceholderText("我的昵称")
        self._their_name = QLineEdit(self)
        self._their_name.setPlaceholderText("对方昵称")
        name_row.addWidget(self._my_name)
        name_row.addWidget(self._their_name)
        root.addLayout(name_row)

        # 步骤2：图片目录
        step_two = QLabel("02  照片目录", self)
        step_two.setStyleSheet("font-size:15px; font-weight:700; color:#263238;")
        root.addWidget(step_two)
        dir_row = QHBoxLayout()
        self._image_dir = QLineEdit(str(app_paths.IMAGES_DIR), self)
        browse_btn = QPushButton("浏览…", self)
        browse_btn.setToolTip("选择桌面相框使用的照片目录")
        browse_btn.clicked.connect(self._browse_dir)
        dir_row.addWidget(self._image_dir, 1)
        dir_row.addWidget(browse_btn)
        root.addLayout(dir_row)

        # 步骤3：局域网同步（可选）
        step_three = QLabel("03  局域网同步", self)
        step_three.setStyleSheet("font-size:15px; font-weight:700; color:#263238;")
        root.addWidget(step_three)
        self._sync_check = QCheckBox("启用局域网同步（两台电脑互相寄信）", self)
        self._sync_check.toggled.connect(self._on_sync_toggled)
        root.addWidget(self._sync_check)
        
        peer_row = QHBoxLayout()
        self._peer_host = QLineEdit(self)
        self._peer_host.setPlaceholderText("对方电脑 IP（如 192.168.1.20）")
        self._peer_host.setEnabled(False)
        self._peer_host.textChanged.connect(
            lambda _text: self._on_sync_toggled(self._sync_check.isChecked())
        )
        peer_row.addWidget(QLabel("对方IP:", self))
        peer_row.addWidget(self._peer_host, 1)
        root.addLayout(peer_row)
        self._sync_hint = QLabel(self)
        self._sync_hint.setWordWrap(True)
        self._sync_hint.setStyleSheet("color:#7b8794;font-size:12px;")
        root.addWidget(self._sync_hint)
        self._on_sync_toggled(False)

        root.addStretch(1)

        # 按钮
        btn_row = QHBoxLayout()
        skip_btn = QPushButton("跳过，用默认值", self)
        skip_btn.setStyleSheet("padding:9px 14px; color:#7b8794;")
        skip_btn.clicked.connect(self._on_skip)
        finish_btn = QPushButton("完成", self)
        finish_btn.setStyleSheet(
            "QPushButton{background:#e85d75;color:#fff;border:none;"
            "border-radius:6px;padding:10px 20px;font-size:15px;font-weight:600;}"
            "QPushButton:hover{background:#d94f68;}"
        )
        finish_btn.clicked.connect(self._on_finish)
        btn_row.addStretch(1)
        btn_row.addWidget(skip_btn)
        btn_row.addWidget(finish_btn)
        root.addLayout(btn_row)

    def _browse_dir(self) -> None:
        path = QFileDialog.getExistingDirectory(self, "选择照片目录", self._image_dir.text())
        if path:
            self._image_dir.setText(path)

    def closeEvent(self, event) -> None:
        # 用户点窗口 X 或 Alt+F4 时也必须释放 finished，否则 launcher 的
        # QEventLoop 永久阻塞，首次启动卡死。
        self.finished.emit()
        super().closeEvent(event)

    def _on_sync_toggled(self, on: bool) -> None:
        self._peer_host.setEnabled(on)
        if not on:
            self._sync_hint.setText("可以稍后在设置中配置局域网同步。")
            self._sync_hint.setStyleSheet("color:#7b8794;font-size:12px;")
        elif self._peer_host.text().strip():
            self._sync_hint.setText("已启用：保存后会尝试连接对方电脑。")
            self._sync_hint.setStyleSheet("color:#2f7d68;font-size:12px;")
        else:
            self._sync_hint.setText("请填写对方电脑的局域网 IP，保存后才会开始连接。")
            self._sync_hint.setStyleSheet("color:#a56d2f;font-size:12px;")

    def _on_skip(self) -> None:
        # 写入 suite.json 标记已完成引导
        app_paths.update_suite(onboarded=True)
        self.finished.emit()
        self.close()

    def _on_finish(self) -> None:
        my_name = self._my_name.text().strip() or "我"
        their_name = self._their_name.text().strip() or "你"
        image_dir = self._image_dir.text().strip() or str(app_paths.IMAGES_DIR)
        peer_host = self._peer_host.text().strip()
        if self._sync_check.isChecked() and not peer_host:
            self._sync_hint.setText("请填写对方电脑的局域网 IP 后再完成设置。")
            self._sync_hint.setStyleSheet("color:#b04a5a;font-size:12px;")
            self._peer_host.setFocus()
            return
        
        # 保存配置
        mb_config.update(my_name=my_name, their_name=their_name)
        pf_config.update(image_dir=image_dir)
        
        if self._sync_check.isChecked():
            mb_config.update(sync_enabled=True, peer_host=peer_host)
        
        # 标记引导完成
        app_paths.update_suite(onboarded=True)
        self.finished.emit()
        self.close()
