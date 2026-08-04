"""综合设置窗口：相框/信箱/同步/纪念日/通用 五个标签页。"""
from __future__ import annotations
from datetime import datetime
from pathlib import Path

from PySide6.QtCore import Signal
from PySide6.QtWidgets import (
    QCheckBox, QComboBox, QFileDialog, QFormLayout, QHBoxLayout, QLabel,
    QLineEdit, QListWidget, QMainWindow, QMessageBox, QPushButton, QSpinBox,
    QTabWidget, QVBoxLayout, QWidget, QColorDialog, QGroupBox, QDoubleSpinBox,
    QRadioButton, QButtonGroup,
)

import autostart
import app_paths
from DesktopPhotoFrame import config as pf_config
from DesktopMailbox import config as mb_config


class SettingsWindow(QMainWindow):
    """综合设置窗口。保存后发 settings_changed 信号通知外部刷新。"""
    settings_changed = Signal()  # 保存后触发

    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle("设置 ⚙")
        self.resize(620, 560)
        self._build_ui()
        self._load_values()

    def _build_ui(self) -> None:
        central = QWidget(self)
        self.setCentralWidget(central)
        root = QVBoxLayout(central)
        root.setContentsMargins(12, 12, 12, 12)

        tabs = QTabWidget(self)
        tabs.addTab(self._build_photo_frame_tab(), "🖼 相框")
        tabs.addTab(self._build_mailbox_tab(), "✉ 信箱")
        tabs.addTab(self._build_sync_tab(), "🔄 同步")
        tabs.addTab(self._build_anniversary_tab(), "🎉 纪念日")
        tabs.addTab(self._build_general_tab(), "⚙ 通用")
        root.addWidget(tabs, 1)

        # 底部保存按钮
        btn_row = QHBoxLayout()
        btn_row.addStretch(1)
        save_btn = QPushButton("💾 保存设置", self)
        save_btn.setStyleSheet(
            "QPushButton{background:#e65a7a;color:#fff;border:none;"
            "border-radius:8px;padding:10px 24px;font-size:14px;}"
            "QPushButton:hover{background:#d94a6a;}"
        )
        save_btn.clicked.connect(self._on_save)
        btn_row.addWidget(save_btn)
        root.addLayout(btn_row)

    # ===== 相框标签页 =====
    def _build_photo_frame_tab(self) -> QWidget:
        tab = QWidget()
        layout = QFormLayout(tab)
        
        self._pf_interval = QSpinBox()
        self._pf_interval.setRange(3, 3600)
        self._pf_interval.setSuffix(" 秒")
        layout.addRow("轮播间隔:", self._pf_interval)
        
        self._pf_width = QSpinBox()
        self._pf_width.setRange(160, 1600)
        self._pf_width.setSuffix(" px")
        self._pf_height = QSpinBox()
        self._pf_height.setRange(200, 2000)
        self._pf_height.setSuffix(" px")
        size_row = QHBoxLayout()
        size_row.addWidget(self._pf_width)
        size_row.addWidget(QLabel("×"))
        size_row.addWidget(self._pf_height)
        layout.addRow("窗口尺寸:", size_row)
        
        self._pf_zoom = QDoubleSpinBox()
        self._pf_zoom.setRange(1.0, 5.0)
        self._pf_zoom.setSingleStep(0.1)
        layout.addRow("双击放大倍数:", self._pf_zoom)
        
        self._pf_corner = QSpinBox()
        self._pf_corner.setRange(0, 80)
        self._pf_corner.setSuffix(" px")
        layout.addRow("圆角半径:", self._pf_corner)
        
        self._pf_polaroid = QCheckBox("拍立得边框")
        layout.addRow(self._pf_polaroid)
        self._pf_watermark = QCheckBox("日期水印")
        layout.addRow(self._pf_watermark)
        self._pf_kenburns = QCheckBox("Ken Burns 缓慢平移动画")
        layout.addRow(self._pf_kenburns)
        self._pf_wheel = QCheckBox("滚轮缩放")
        layout.addRow(self._pf_wheel)
        
        # 主题色
        color_row = QHBoxLayout()
        self._pf_color_edit = QLineEdit()
        self._pf_color_edit.setPlaceholderText("#RRGGBB")
        color_btn = QPushButton("选色…")
        color_btn.clicked.connect(self._pick_color)
        color_row.addWidget(self._pf_color_edit, 1)
        color_row.addWidget(color_btn)
        layout.addRow("纪念日主题色:", color_row)
        
        # 相册管理
        album_group = QGroupBox("相册管理")
        album_layout = QVBoxLayout(album_group)
        self._album_list = QListWidget()
        album_layout.addWidget(self._album_list)
        album_btn_row = QHBoxLayout()
        add_album_btn = QPushButton("添加相册…")
        add_album_btn.clicked.connect(self._add_album)
        del_album_btn = QPushButton("删除选中")
        del_album_btn.clicked.connect(self._del_album)
        album_btn_row.addWidget(add_album_btn)
        album_btn_row.addWidget(del_album_btn)
        album_layout.addLayout(album_btn_row)
        layout.addRow(album_group)
        
        return tab

    # ===== 信箱标签页 =====
    def _build_mailbox_tab(self) -> QWidget:
        tab = QWidget()
        layout = QFormLayout(tab)
        
        self._mb_my_name = QLineEdit()
        layout.addRow("我的昵称:", self._mb_my_name)
        self._mb_their_name = QLineEdit()
        layout.addRow("对方昵称:", self._mb_their_name)
        
        self._mb_check_interval = QSpinBox()
        self._mb_check_interval.setRange(10, 600)
        self._mb_check_interval.setSuffix(" 秒")
        layout.addRow("到期检查间隔:", self._mb_check_interval)
        
        return tab

    # ===== 同步标签页 =====
    def _build_sync_tab(self) -> QWidget:
        tab = QWidget()
        layout = QFormLayout(tab)

        self._sync_enabled = QCheckBox("启用局域网同步")
        layout.addRow(self._sync_enabled)

        # 同步模式单选
        self._sync_mode_group = QButtonGroup(self)
        self._mode_lan = QRadioButton("局域网")
        self._mode_cloud = QRadioButton("云中转")
        self._mode_both = QRadioButton("两者")
        self._sync_mode_group.addButton(self._mode_lan)
        self._sync_mode_group.addButton(self._mode_cloud)
        self._sync_mode_group.addButton(self._mode_both)
        mode_row = QHBoxLayout()
        mode_row.addWidget(self._mode_lan)
        mode_row.addWidget(self._mode_cloud)
        mode_row.addWidget(self._mode_both)
        mode_row.addStretch(1)
        layout.addRow("同步模式:", mode_row)

        self._sync_peer_host = QLineEdit()
        self._sync_peer_host.setPlaceholderText("如 192.168.1.20")
        layout.addRow("对方 IP:", self._sync_peer_host)

        self._sync_peer_port = QSpinBox()
        self._sync_peer_port.setRange(1, 65535)
        layout.addRow("对方端口:", self._sync_peer_port)

        self._sync_port = QSpinBox()
        self._sync_port.setRange(1, 65535)
        layout.addRow("本机监听端口:", self._sync_port)

        # 云中转配置
        self._cloud_group = QGroupBox("云中转配置")
        cloud_layout = QFormLayout(self._cloud_group)
        self._cloud_server = QLineEdit()
        self._cloud_server.setPlaceholderText("https://couple-relay.example.com")
        cloud_layout.addRow("服务器地址:", self._cloud_server)
        self._cloud_pair_code = QLineEdit()
        self._cloud_pair_code.setPlaceholderText("双方填相同码")
        cloud_layout.addRow("配对码:", self._cloud_pair_code)
        layout.addRow(self._cloud_group)

        # 根据模式显示/隐藏云配置
        self._mode_lan.toggled.connect(self._update_cloud_visibility)
        self._mode_cloud.toggled.connect(self._update_cloud_visibility)
        self._mode_both.toggled.connect(self._update_cloud_visibility)

        hint = QLabel("提示：两台电脑互填对方 IP 即可互相寄信。端口默认 52014。")
        hint.setStyleSheet("color:#888; font-size:12px;")
        hint.setWordWrap(True)
        layout.addRow(hint)

        return tab

    def _update_cloud_visibility(self) -> None:
        show_cloud = self._mode_cloud.isChecked() or self._mode_both.isChecked()
        self._cloud_group.setVisible(show_cloud)

    # ===== 纪念日标签页 =====
    def _build_anniversary_tab(self) -> QWidget:
        tab = QWidget()
        layout = QVBoxLayout(tab)
        
        # 相框纪念日（MM-DD 列表，影响主题色）
        pf_group = QGroupBox("相框纪念日（当天主题色变色，格式 MM-DD）")
        pf_layout = QVBoxLayout(pf_group)
        self._pf_anniv_list = QListWidget()
        pf_layout.addWidget(self._pf_anniv_list)
        pf_row = QHBoxLayout()
        self._pf_anniv_input = QLineEdit()
        self._pf_anniv_input.setPlaceholderText("如 08-14")
        pf_add = QPushButton("添加")
        pf_add.clicked.connect(self._add_pf_anniv)
        pf_del = QPushButton("删除选中")
        pf_del.clicked.connect(self._del_pf_anniv)
        pf_row.addWidget(self._pf_anniv_input, 1)
        pf_row.addWidget(pf_add)
        pf_row.addWidget(pf_del)
        pf_layout.addLayout(pf_row)
        layout.addWidget(pf_group)
        
        # 在一起起始日
        since_row = QHBoxLayout()
        self._together_since = QLineEdit()
        self._together_since.setPlaceholderText("YYYY-MM-DD")
        since_row.addWidget(self._together_since, 1)
        layout.addLayout(since_row)
        layout.insertWidget(layout.count() - 1, QLabel("在一起起始日（统计看板用）:"))
        
        return tab

    # ===== 通用标签页 =====
    def _build_general_tab(self) -> QWidget:
        tab = QWidget()
        layout = QVBoxLayout(tab)
        
        self._autostart = QCheckBox("开机自启动")
        layout.addWidget(self._autostart)
        
        layout.addStretch(1)
        return tab

    # ===== 加载当前值 =====
    def _load_values(self) -> None:
        pf = pf_config.load()
        self._pf_interval.setValue(pf["interval_sec"])
        self._pf_width.setValue(pf["window_width"])
        self._pf_height.setValue(pf["window_height"])
        self._pf_zoom.setValue(pf.get("zoom_factor", 2.0))
        self._pf_corner.setValue(pf.get("corner_radius", 18))
        self._pf_polaroid.setChecked(pf["polaroid_frame"])
        self._pf_watermark.setChecked(pf["show_watermark"])
        self._pf_kenburns.setChecked(pf.get("ken_burns", True))
        self._pf_wheel.setChecked(pf.get("wheel_zoom_enabled", True))
        self._pf_color_edit.setText(pf.get("theme_color", "#e65a7a"))
        # 相册列表
        self._album_list.clear()
        for a in pf.get("albums", []):
            self._album_list.addItem(f"{a['name']}  →  {a['path']}")
        # 相框纪念日
        self._pf_anniv_list.clear()
        for md in pf.get("anniversaries", []):
            self._pf_anniv_list.addItem(md)
        
        mb = mb_config.load()
        self._mb_my_name.setText(mb.get("my_name", "我"))
        self._mb_their_name.setText(mb.get("their_name", "你"))
        self._mb_check_interval.setValue(mb.get("check_interval_sec", 30))
        self._sync_enabled.setChecked(mb.get("sync_enabled", False))
        self._sync_peer_host.setText(mb.get("peer_host", ""))
        self._sync_peer_port.setValue(mb.get("peer_port", 52014))
        self._sync_port.setValue(mb.get("sync_port", 52014))
        mode = mb.get("sync_mode", "lan")
        if mode == "cloud":
            self._mode_cloud.setChecked(True)
        elif mode == "both":
            self._mode_both.setChecked(True)
        else:
            self._mode_lan.setChecked(True)
        self._cloud_server.setText(mb.get("cloud_server", ""))
        self._cloud_pair_code.setText(mb.get("cloud_pair_code", ""))
        self._update_cloud_visibility()
        
        suite = app_paths.load_suite()
        self._together_since.setText(suite.get("together_since", ""))
        self._autostart.setChecked(autostart.is_enabled())

    # ===== 交互处理 =====
    def _pick_color(self) -> None:
        from PySide6.QtWidgets import QColorDialog
        color = QColorDialog.getColor()
        if color.isValid():
            self._pf_color_edit.setText(color.name())
    
    def _add_album(self) -> None:
        path = QFileDialog.getExistingDirectory(self, "选择相册目录")
        if not path:
            return
        name = Path(path).name or path
        pf_config.add_album(name, path)
        self._album_list.addItem(f"{name}  →  {path}")
    
    def _del_album(self) -> None:
        row = self._album_list.currentRow()
        if row < 0:
            return
        item = self._album_list.takeItem(row)
        # 解析 path
        text = item.text()
        path = text.split("→")[-1].strip() if "→" in text else ""
        if path:
            pf_config.remove_album(path)
    
    def _add_pf_anniv(self) -> None:
        md = self._pf_anniv_input.text().strip()
        if not md:
            return
        # 简单校验 MM-DD
        try:
            month, day = md.split("-")
            int(month), int(day)
        except (ValueError, IndexError):
            QMessageBox.warning(self, "格式错误", "请输入 MM-DD 格式，如 08-14")
            return
        self._pf_anniv_list.addItem(md)
        self._pf_anniv_input.clear()
    
    def _del_pf_anniv(self) -> None:
        row = self._pf_anniv_list.currentRow()
        if row >= 0:
            self._pf_anniv_list.takeItem(row)

    # ===== 保存 =====
    def _on_save(self) -> None:
        # 相框配置
        pf_config.update(
            interval_sec=self._pf_interval.value(),
            window_width=self._pf_width.value(),
            window_height=self._pf_height.value(),
            zoom_factor=self._pf_zoom.value(),
            corner_radius=self._pf_corner.value(),
            polaroid_frame=self._pf_polaroid.isChecked(),
            show_watermark=self._pf_watermark.isChecked(),
            ken_burns=self._pf_kenburns.isChecked(),
            wheel_zoom_enabled=self._pf_wheel.isChecked(),
            theme_color=self._pf_color_edit.text().strip() or "#e65a7a",
            anniversaries=[self._pf_anniv_list.item(i).text()
                          for i in range(self._pf_anniv_list.count())],
        )
        # 信箱配置
        if self._mode_cloud.isChecked():
            sync_mode = "cloud"
        elif self._mode_both.isChecked():
            sync_mode = "both"
        else:
            sync_mode = "lan"
        mb_config.update(
            my_name=self._mb_my_name.text().strip() or "我",
            their_name=self._mb_their_name.text().strip() or "你",
            check_interval_sec=self._mb_check_interval.value(),
            sync_enabled=self._sync_enabled.isChecked(),
            peer_host=self._sync_peer_host.text().strip(),
            peer_port=self._sync_peer_port.value(),
            sync_port=self._sync_port.value(),
            sync_mode=sync_mode,
            cloud_server=self._cloud_server.text().strip(),
            cloud_pair_code=self._cloud_pair_code.text().strip(),
        )
        # 套件配置
        since = self._together_since.text().strip()
        if since:
            app_paths.update_suite(together_since=since)
        # 自启动
        autostart.toggle(self._autostart.isChecked())
        
        self.settings_changed.emit()
        QMessageBox.information(self, "已保存", "设置已保存并生效。")
