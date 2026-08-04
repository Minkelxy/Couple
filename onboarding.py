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
        self.setWindowTitle("欢迎使用桌面相册 💕")
        self.resize(480, 420)
        self._build_ui()

    def _build_ui(self) -> None:
        central = QWidget(self)
        self.setCentralWidget(central)
        root = QVBoxLayout(central)
        root.setContentsMargins(28, 24, 28, 24)
        root.setSpacing(12)

        # 标题
        title = QLabel("初次见面，简单设置一下", self)
        title.setStyleSheet("font-size:18px; font-weight:600; color:#e65a7a;")
        root.addWidget(title)

        hint = QLabel("以下设置随时可在「设置」中修改。", self)
        hint.setStyleSheet("color:#888; font-size:13px;")
        root.addWidget(hint)

        # 步骤1：昵称
        root.addWidget(QLabel("1. 昵称", self))
        name_row = QHBoxLayout()
        self._my_name = QLineEdit(self)
        self._my_name.setPlaceholderText("我的昵称")
        self._their_name = QLineEdit(self)
        self._their_name.setPlaceholderText("对方昵称")
        name_row.addWidget(self._my_name)
        name_row.addWidget(self._their_name)
        root.addLayout(name_row)

        # 步骤2：图片目录
        root.addWidget(QLabel("2. 照片目录（轮播的图片）", self))
        dir_row = QHBoxLayout()
        self._image_dir = QLineEdit(str(app_paths.IMAGES_DIR), self)
        browse_btn = QPushButton("浏览…", self)
        browse_btn.clicked.connect(self._browse_dir)
        dir_row.addWidget(self._image_dir, 1)
        dir_row.addWidget(browse_btn)
        root.addLayout(dir_row)

        # 步骤3：局域网同步（可选）
        root.addWidget(QLabel("3. 局域网同步（可选，跳过则仅本地使用）", self))
        self._sync_check = QCheckBox("启用局域网同步（两台电脑互相寄信）", self)
        self._sync_check.toggled.connect(self._on_sync_toggled)
        root.addWidget(self._sync_check)
        
        peer_row = QHBoxLayout()
        self._peer_host = QLineEdit(self)
        self._peer_host.setPlaceholderText("对方电脑 IP（如 192.168.1.20）")
        self._peer_host.setEnabled(False)
        peer_row.addWidget(QLabel("对方IP:", self))
        peer_row.addWidget(self._peer_host, 1)
        root.addLayout(peer_row)

        root.addStretch(1)

        # 按钮
        btn_row = QHBoxLayout()
        skip_btn = QPushButton("跳过，用默认值", self)
        skip_btn.setStyleSheet("padding:10px; color:#888;")
        skip_btn.clicked.connect(self._on_skip)
        finish_btn = QPushButton("完成 ✅", self)
        finish_btn.setStyleSheet(
            "QPushButton{background:#e65a7a;color:#fff;border:none;"
            "border-radius:8px;padding:12px;font-size:15px;}"
            "QPushButton:hover{background:#d94a6a;}"
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

    def _on_sync_toggled(self, on: bool) -> None:
        self._peer_host.setEnabled(on)

    def _on_skip(self) -> None:
        # 写入 suite.json 标记已完成引导
        app_paths.update_suite(onboarded=True)
        self.finished.emit()
        self.close()

    def _on_finish(self) -> None:
        my_name = self._my_name.text().strip() or "我"
        their_name = self._their_name.text().strip() or "你"
        image_dir = self._image_dir.text().strip() or str(app_paths.IMAGES_DIR)
        
        # 保存配置
        mb_config.update(my_name=my_name, their_name=their_name)
        pf_config.update(image_dir=image_dir)
        
        if self._sync_check.isChecked():
            peer_host = self._peer_host.text().strip()
            mb_config.update(sync_enabled=True, peer_host=peer_host)
        
        # 标记引导完成
        app_paths.update_suite(onboarded=True)
        self.finished.emit()
        self.close()
