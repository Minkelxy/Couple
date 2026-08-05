"""综合设置窗口：相框/信箱/同步/纪念日/通用 五个标签页。"""
from __future__ import annotations
from datetime import datetime
from pathlib import Path

from PySide6.QtCore import Signal, Qt
from PySide6.QtGui import QColor, QBrush
from PySide6.QtWidgets import (
    QCheckBox, QComboBox, QFileDialog, QFormLayout, QHBoxLayout, QLabel,
    QLineEdit, QListWidget, QListWidgetItem, QMainWindow, QMessageBox, QPushButton,
    QSpinBox, QTabWidget, QVBoxLayout, QWidget, QColorDialog, QGroupBox,
    QDoubleSpinBox, QRadioButton, QButtonGroup,
)

import autostart
import app_paths
from DesktopPhotoFrame import config as pf_config
from DesktopMailbox import config as mb_config


# 「当前在用相册」列表项高亮颜色（浅粉，和主题色匹配）
_CURRENT_ALBUM_BG = QColor("#ffe3ec")


class SettingsWindow(QMainWindow):
    """综合设置窗口。保存后发 settings_changed 信号通知外部刷新。"""
    settings_changed = Signal()  # 保存后触发

    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle("设置 ⚙")
        self.resize(660, 620)
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
        layout.setVerticalSpacing(8)

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
        self._pf_blur_bg = QCheckBox("模糊背景填充（与 Ken Burns 互斥）")
        layout.addRow(self._pf_blur_bg)
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

        # 当前在用相册（image_dir）显示 + 选择
        current_row = QHBoxLayout()
        self._pf_current_album = QLineEdit()
        self._pf_current_album.setReadOnly(True)
        self._pf_current_album.setPlaceholderText("(空，下方选一个相册或浏览目录)")
        pick_btn = QPushButton("浏览…")
        pick_btn.clicked.connect(self._pick_current_album)
        current_row.addWidget(self._pf_current_album, 1)
        current_row.addWidget(pick_btn)
        layout.addRow("当前默认相册:", current_row)

        # 相册管理
        album_group = QGroupBox("相册管理（添加后可在下方选中，点「设为默认」切换轮播目录）")
        album_layout = QVBoxLayout(album_group)
        self._album_list = QListWidget()
        self._album_list.setAlternatingRowColors(False)
        album_layout.addWidget(self._album_list, 1)
        album_btn_row = QHBoxLayout()
        add_album_btn = QPushButton("添加相册…")
        add_album_btn.clicked.connect(self._add_album)
        set_default_btn = QPushButton("设为默认")
        set_default_btn.clicked.connect(self._set_current_album_from_list)
        del_album_btn = QPushButton("删除选中")
        del_album_btn.clicked.connect(self._del_album)
        album_btn_row.addWidget(add_album_btn)
        album_btn_row.addWidget(set_default_btn)
        album_btn_row.addStretch(1)
        album_btn_row.addWidget(del_album_btn)
        album_layout.addLayout(album_btn_row)
        layout.addRow(album_group)

        # Ken Burns / 模糊背景 互斥提示
        self._pf_kenburns.toggled.connect(self._sync_blur_mutual_exclusion)
        self._pf_blur_bg.toggled.connect(self._sync_blur_mutual_exclusion)

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

    def _sync_blur_mutual_exclusion(self) -> None:
        """Ken Burns 与 模糊背景 互斥：一个勾选时自动取消另一个。"""
        sender = self.sender()
        if sender is self._pf_kenburns and self._pf_kenburns.isChecked():
            self._pf_blur_bg.setChecked(False)
        elif sender is self._pf_blur_bg and self._pf_blur_bg.isChecked():
            self._pf_kenburns.setChecked(False)

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
        layout.addWidget(QLabel("在一起起始日（统计看板用）:"))
        since_row = QHBoxLayout()
        self._together_since = QLineEdit()
        self._together_since.setPlaceholderText("YYYY-MM-DD")
        since_row.addWidget(self._together_since, 1)
        layout.addLayout(since_row)

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
        self._pf_zoom.setValue(float(pf.get("zoom_factor", 2.0)))
        self._pf_corner.setValue(int(pf.get("corner_radius", 18)))
        self._pf_polaroid.setChecked(bool(pf["polaroid_frame"]))
        self._pf_watermark.setChecked(bool(pf["show_watermark"]))
        self._pf_kenburns.setChecked(bool(pf.get("ken_burns", True)))
        self._pf_blur_bg.setChecked(bool(pf.get("blur_background", False)))
        self._pf_wheel.setChecked(bool(pf.get("wheel_zoom_enabled", True)))
        self._pf_color_edit.setText(str(pf.get("theme_color", "#e65a7a")))

        # 当前默认相册
        self._pf_current_album.setText(str(pf.get("image_dir", "")))

        # 相册列表（当前在用项高亮）
        self._album_list.clear()
        current_path = str(pf.get("image_dir", ""))
        for a in pf.get("albums", []) or []:
            text = f"{a['name']}  →  {a['path']}"
            item = QListWidgetItem(text)
            item.setData(Qt.UserRole, str(a.get("path", "")))
            if str(a.get("path", "")) == current_path:
                item.setBackground(QBrush(_CURRENT_ALBUM_BG))
                item.setToolTip("当前默认相册")
            self._album_list.addItem(item)

        # 相框纪念日
        self._pf_anniv_list.clear()
        for md in pf.get("anniversaries", []) or []:
            self._pf_anniv_list.addItem(str(md))

        mb = mb_config.load()
        self._mb_my_name.setText(str(mb.get("my_name", "我")))
        self._mb_their_name.setText(str(mb.get("their_name", "你")))
        self._mb_check_interval.setValue(int(mb.get("check_interval_sec", 30)))
        self._sync_enabled.setChecked(bool(mb.get("sync_enabled", False)))
        self._sync_peer_host.setText(str(mb.get("peer_host", "")))
        self._sync_peer_port.setValue(int(mb.get("peer_port", 52014)))
        self._sync_port.setValue(int(mb.get("sync_port", 52014)))
        mode = str(mb.get("sync_mode", "lan"))
        if mode == "cloud":
            self._mode_cloud.setChecked(True)
        elif mode == "both":
            self._mode_both.setChecked(True)
        else:
            self._mode_lan.setChecked(True)
        self._cloud_server.setText(str(mb.get("cloud_server", "")))
        self._cloud_pair_code.setText(str(mb.get("cloud_pair_code", "")))
        self._update_cloud_visibility()

        suite = app_paths.load_suite()
        self._together_since.setText(str(suite.get("together_since", "")))
        self._autostart.setChecked(autostart.is_enabled())

    # ===== 交互处理 =====
    def _pick_color(self) -> None:
        color = QColorDialog.getColor()
        if color.isValid():
            self._pf_color_edit.setText(color.name())

    def _pick_current_album(self) -> None:
        path = QFileDialog.getExistingDirectory(self, "选择默认相册目录")
        if not path:
            return
        self._pf_current_album.setText(path)
        # 如果该目录不在相册列表里，自动加进去
        for i in range(self._album_list.count()):
            item = self._album_list.item(i)
            if item.data(Qt.UserRole) == path:
                return
        name = Path(path).name or path
        pf_config.add_album(name, path)
        item = QListWidgetItem(f"{name}  →  {path}")
        item.setData(Qt.UserRole, path)
        self._album_list.addItem(item)

    def _set_current_album_from_list(self) -> None:
        row = self._album_list.currentRow()
        if row < 0:
            QMessageBox.information(self, "提示", "请先在上面列表里选一个相册。")
            return
        item = self._album_list.item(row)
        path = item.data(Qt.UserRole)
        if not path:
            return
        self._pf_current_album.setText(path)
        # 刷新高亮
        for i in range(self._album_list.count()):
            it = self._album_list.item(i)
            if it.data(Qt.UserRole) == path:
                it.setBackground(QBrush(_CURRENT_ALBUM_BG))
                it.setToolTip("当前默认相册")
            else:
                it.setBackground(QBrush(Qt.transparent))
                it.setToolTip("")

    def _add_album(self) -> None:
        path = QFileDialog.getExistingDirectory(self, "选择相册目录")
        if not path:
            return
        # 去重
        for i in range(self._album_list.count()):
            if self._album_list.item(i).data(Qt.UserRole) == path:
                return
        name = Path(path).name or path
        pf_config.add_album(name, path)
        item = QListWidgetItem(f"{name}  →  {path}")
        item.setData(Qt.UserRole, path)
        self._album_list.addItem(item)

    def _del_album(self) -> None:
        row = self._album_list.currentRow()
        if row < 0:
            return
        item = self._album_list.takeItem(row)
        path = item.data(Qt.UserRole) or (
            item.text().split("→")[-1].strip() if "→" in item.text() else ""
        )
        if path:
            pf_config.remove_album(path)
            # 如果删掉的正是当前默认相册，切回系统默认 images 目录
            current = self._pf_current_album.text().strip()
            if current == path:
                self._pf_current_album.setText(str(app_paths.IMAGES_DIR))

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
        # 去重
        for i in range(self._pf_anniv_list.count()):
            if self._pf_anniv_list.item(i).text() == md:
                return
        self._pf_anniv_list.addItem(md)
        self._pf_anniv_input.clear()

    def _del_pf_anniv(self) -> None:
        row = self._pf_anniv_list.currentRow()
        if row >= 0:
            self._pf_anniv_list.takeItem(row)

    # ===== 保存 =====
    def _collect_albums_from_list(self) -> list[dict]:
        albums: list[dict] = []
        for i in range(self._album_list.count()):
            item = self._album_list.item(i)
            text = item.text()
            path = item.data(Qt.UserRole) or ""
            if not path:
                # 兜底：老项没带 UserRole，按文本解析
                path = text.split("→")[-1].strip() if "→" in text else ""
            if not path:
                continue
            name = text.split("→", 1)[0].strip() if "→" in text else (Path(path).name or path)
            albums.append({"name": name, "path": path})
        return albums

    def _on_save(self) -> None:
        # 当前默认相册
        current_album = self._pf_current_album.text().strip() or str(app_paths.IMAGES_DIR)
        albums = self._collect_albums_from_list()

        # 确保当前默认相册也在 albums 列表里
        if not any(a["path"] == current_album for a in albums):
            name = Path(current_album).name or "默认相册"
            albums.append({"name": name, "path": current_album})

        # 相框配置（含 albums + image_dir + blur_background）
        pf_config.update(
            interval_sec=self._pf_interval.value(),
            window_width=self._pf_width.value(),
            window_height=self._pf_height.value(),
            zoom_factor=float(self._pf_zoom.value()),
            corner_radius=self._pf_corner.value(),
            polaroid_frame=self._pf_polaroid.isChecked(),
            show_watermark=self._pf_watermark.isChecked(),
            ken_burns=self._pf_kenburns.isChecked(),
            blur_background=self._pf_blur_bg.isChecked(),
            wheel_zoom_enabled=self._pf_wheel.isChecked(),
            theme_color=self._pf_color_edit.text().strip() or "#e65a7a",
            anniversaries=[
                self._pf_anniv_list.item(i).text()
                for i in range(self._pf_anniv_list.count())
            ],
            albums=albums,
            image_dir=current_album,
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
