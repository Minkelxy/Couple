"""综合设置窗口：相框/信箱/同步/联机身份/纪念日/通用 六个标签页。"""
from __future__ import annotations
from datetime import datetime
from pathlib import Path

from PySide6.QtCore import QObject, QThread, Signal, Qt, QTimer
from PySide6.QtGui import QColor, QBrush, QGuiApplication, QClipboard
from PySide6.QtWidgets import (
    QCheckBox, QComboBox, QFileDialog, QFormLayout, QHBoxLayout, QLabel,
    QLineEdit, QListWidget, QListWidgetItem, QMainWindow, QMessageBox, QPushButton,
    QSpinBox, QTabWidget, QVBoxLayout, QWidget, QColorDialog, QGroupBox,
    QDoubleSpinBox, QRadioButton, QButtonGroup, QProgressBar, QInputDialog,
)

import autostart
import app_paths
from DesktopPhotoFrame import config as pf_config
from DesktopMailbox import config as mb_config

import identity as idm
from pairing import PairingSession, PairingProgress, PairingPhase


# 「当前在用相册」列表项高亮颜色（浅粉，和主题色匹配）
_CURRENT_ALBUM_BG = QColor("#ffe3ec")


class _PairingWorker(QObject):
    """配对流程的线程包装：把 PairingSession 回调搬到 UI 线程发 Signal。"""
    progress = Signal(object)  # PairingProgress

    def __init__(self, mode: str, token: str | None, server: str, nickname: str) -> None:
        super().__init__()
        self._mode = mode
        self._token = token
        self._server = server
        self._nickname = nickname
        self._session: PairingSession | None = None

    def run(self) -> None:
        def _cb(p: PairingProgress) -> None:
            self.progress.emit(p)
        try:
            session = PairingSession(self._server, self._nickname, _cb)
            self._session = session
            if self._mode == "host":
                session.start_host()
            else:
                session.start_guest(self._token or "")
        except Exception as e:
            _cb(PairingProgress(PairingPhase.FAILED, error_message=str(e)))

    def confirm_safety(self, matched: bool) -> None:
        if self._session is not None:
            self._session.confirm_safety(matched)

    def cancel(self) -> None:
        if self._session is not None:
            self._session.cancel()
            self._session.wait(3)


class SettingsWindow(QMainWindow):
    """综合设置窗口。保存后发 settings_changed 信号通知外部刷新。"""
    settings_changed = Signal()  # 保存后触发

    def closeEvent(self, event) -> None:
        if self._pairing_worker is not None:
            self._on_pair_cancel()
        event.accept()

    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle("设置")
        self.resize(720, 780)
        self.setMinimumSize(660, 720)
        self._build_ui()
        self._load_values()

    def _build_ui(self) -> None:
        central = QWidget(self)
        self.setCentralWidget(central)
        root = QVBoxLayout(central)
        root.setContentsMargins(24, 20, 24, 20)
        root.setSpacing(10)

        header = QVBoxLayout()
        header.setSpacing(2)
        title = QLabel("设置", self)
        title.setStyleSheet("font-size:24px; font-weight:700; color:#263238;")
        subtitle = QLabel("调整相框、信箱、同步和身份，让两台设备保持一致", self)
        subtitle.setStyleSheet("color:#7b8794; font-size:13px;")
        header.addWidget(title)
        header.addWidget(subtitle)
        root.addLayout(header)

        tabs = QTabWidget(self)
        tabs.setDocumentMode(True)
        tabs.setUsesScrollButtons(True)
        tabs.addTab(self._build_photo_frame_tab(), "相框")
        tabs.addTab(self._build_mailbox_tab(), "信箱")
        tabs.addTab(self._build_sync_tab(), "同步")
        tabs.addTab(self._build_identity_tab(), "联机身份")
        tabs.addTab(self._build_anniversary_tab(), "纪念日")
        tabs.addTab(self._build_general_tab(), "通用")
        self._tabs = tabs
        root.addWidget(tabs, 1)

        # 底部保存按钮
        btn_row = QHBoxLayout()
        btn_row.addStretch(1)
        save_btn = QPushButton("保存设置", self)
        save_btn.setToolTip("保存所有设置并立即生效")
        save_btn.setStyleSheet(
            "QPushButton{background:#e85d75;color:#fff;border:none;"
            "border-radius:6px;padding:10px 24px;font-size:14px;font-weight:600;}"
            "QPushButton:hover{background:#d94f68;}"
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
        add_album_btn.setToolTip("选择一个文件夹作为新相册")
        add_album_btn.clicked.connect(self._add_album)
        set_default_btn = QPushButton("设为默认")
        set_default_btn.setToolTip("将选中的相册设为桌面相框默认显示的相册")
        set_default_btn.clicked.connect(self._set_current_album_from_list)
        del_album_btn = QPushButton("删除选中")
        del_album_btn.setToolTip("从相册列表中移除（不会删除硬盘上的图片）")
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

        self._sync_enabled = QCheckBox("启用局域网监听")
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
        self._cloud_pairing_status = QLabel()
        self._cloud_pairing_status.setWordWrap(True)
        self._cloud_pairing_status.setStyleSheet("color:#7b8794; font-size:12px;")
        cloud_layout.addRow("公钥配对:", self._cloud_pairing_status)
        self._cloud_pair_code = QLineEdit()
        self._cloud_pair_code.setPlaceholderText("仅旧版客户端迁移时使用")
        cloud_layout.addRow("旧版配对码:", self._cloud_pair_code)
        layout.addRow(self._cloud_group)

        # 根据模式显示/隐藏云配置
        self._mode_lan.toggled.connect(self._update_cloud_visibility)
        self._mode_cloud.toggled.connect(self._update_cloud_visibility)
        self._mode_both.toggled.connect(self._update_cloud_visibility)

        self._sync_mode_hint = QLabel(self)
        self._sync_mode_hint.setWordWrap(True)
        self._sync_mode_hint.setStyleSheet(
            "color:#52616d;font-size:12px;padding:8px 10px;"
            "background:#f7f9fb;border:1px solid #dfe5ec;border-radius:6px;"
        )
        layout.addRow(self._sync_mode_hint)

        hint = QLabel("提示：两台电脑互填对方 IP 即可互相寄信。端口默认 52014。")
        hint.setStyleSheet("color:#7b8794; font-size:12px;")
        hint.setWordWrap(True)
        layout.addRow(hint)

        return tab

    def _update_cloud_visibility(self) -> None:
        show_cloud = self._mode_cloud.isChecked() or self._mode_both.isChecked()
        self._cloud_group.setVisible(show_cloud)
        if self._mode_cloud.isChecked():
            text = "云中转：两台客户端都连接 Ubuntu 服务器，适合不在同一局域网的设备。"
        elif self._mode_both.isChecked():
            text = "两者：优先使用局域网直连，无法直连时再通过 Ubuntu 服务器中转。"
        else:
            text = "局域网：两台客户端处于同一网络时互填对方 IP，延迟最低。"
        self._sync_mode_hint.setText(text)

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

    # ===== 联机身份标签页 =====
    def _build_identity_tab(self) -> QWidget:
        tab = QWidget()
        outer = QVBoxLayout(tab)
        outer.setSpacing(10)

        # 1. 我
        grp_me = QGroupBox("我的身份")
        form_me = QFormLayout(grp_me)
        self._id_my_fp = QLineEdit()
        self._id_my_fp.setReadOnly(True)
        self._id_copy_my_fp = QPushButton("复制指纹")
        self._id_copy_my_fp.clicked.connect(lambda: self._copy_text(self._id_my_fp.text()))
        row1 = QHBoxLayout()
        row1.addWidget(self._id_my_fp, 1)
        row1.addWidget(self._id_copy_my_fp)
        wrap1 = QWidget(); wrap1.setLayout(row1)
        form_me.addRow("公钥指纹:", wrap1)
        self._id_my_pk = QLineEdit()
        self._id_my_pk.setReadOnly(True)
        self._id_my_pk.setPlaceholderText("（点击右侧复制完整公钥）")
        self._id_copy_my_pk = QPushButton("复制公钥")
        self._id_copy_my_pk.clicked.connect(lambda: self._copy_text(self._id_my_pk.text()))
        row2 = QHBoxLayout()
        row2.addWidget(self._id_my_pk, 1)
        row2.addWidget(self._id_copy_my_pk)
        wrap2 = QWidget(); wrap2.setLayout(row2)
        form_me.addRow("完整公钥:", wrap2)
        self._id_nick_me = QLineEdit()
        self._id_nick_me.setPlaceholderText("配对时展示给对方的昵称，如「阿鹿」")
        self._id_nick_me.setMaxLength(20)
        form_me.addRow("我的昵称:", self._id_nick_me)
        outer.addWidget(grp_me)

        # 2. 对方
        grp_them = QGroupBox("对方身份（未配对则为空）")
        form_them = QFormLayout(grp_them)
        self._id_them_nick = QLineEdit()
        self._id_them_nick.setReadOnly(True)
        self._id_them_nick.setPlaceholderText("尚未与任何设备配对")
        form_them.addRow("对方昵称:", self._id_them_nick)
        self._id_them_fp = QLineEdit()
        self._id_them_fp.setReadOnly(True)
        self._id_them_fp.setPlaceholderText("尚未配对")
        self._id_copy_them_fp = QPushButton("复制指纹")
        self._id_copy_them_fp.clicked.connect(lambda: self._copy_text(self._id_them_fp.text()))
        row3 = QHBoxLayout()
        row3.addWidget(self._id_them_fp, 1)
        row3.addWidget(self._id_copy_them_fp)
        wrap3 = QWidget(); wrap3.setLayout(row3)
        form_them.addRow("对方指纹:", wrap3)
        self._id_safety = QLineEdit()
        self._id_safety.setReadOnly(True)
        self._id_safety.setPlaceholderText("尚未配对")
        btn_safety = QPushButton("核对安全码")
        btn_safety.clicked.connect(self._show_safety_dialog)
        row4 = QHBoxLayout()
        row4.addWidget(self._id_safety, 1)
        row4.addWidget(btn_safety)
        wrap4 = QWidget(); wrap4.setLayout(row4)
        form_them.addRow("安全码:", wrap4)
        self._id_channel = QLineEdit()
        self._id_channel.setReadOnly(True)
        self._id_channel.setPlaceholderText("尚未配对")
        form_them.addRow("专属通道 ID:", self._id_channel)
        row5 = QHBoxLayout()
        self._btn_reset_partner = QPushButton("解除配对")
        self._btn_reset_partner.clicked.connect(self._on_reset_partner)
        row5.addStretch(1); row5.addWidget(self._btn_reset_partner)
        form_them.addRow(row5)
        outer.addWidget(grp_them)

        # 3. 配对向导
        grp_pair = QGroupBox("开始配对（仅第一次需要，之后不用再填任何码）")
        pv = QVBoxLayout(grp_pair)
        tip = QLabel("配对是一次性的，完成后你们两台电脑会互相认出彼此，不需要再填任何识别码。"
                     "<br>两台电脑分别选择一个角色：一台发起（获得 6 位配对码），另一台输入（输入那 6 位码）。")
        tip.setWordWrap(True); tip.setStyleSheet("color:#52616d;")
        pv.addWidget(tip)
        row_btns = QHBoxLayout()
        self._btn_host = QPushButton("① 发起配对（我这边显示 6 位码）")
        self._btn_host.setStyleSheet(self._primary_btn_css())
        self._btn_host.clicked.connect(self._on_start_host)
        self._btn_guest = QPushButton("② 输入对方的 6 位配对码")
        self._btn_guest.setStyleSheet(self._primary_btn_css())
        self._btn_guest.clicked.connect(self._on_start_guest)
        row_btns.addWidget(self._btn_host)
        row_btns.addWidget(self._btn_guest)
        pv.addLayout(row_btns)
        # 状态行
        self._pair_stage = QLabel("—— 请点击上面的按钮开始 ——")
        self._pair_stage.setStyleSheet(
            "padding:10px;border:1px solid #dfe5ec;border-radius:6px;"
            "background:#f7f9fb;color:#263238;"
        )
        self._pair_stage.setWordWrap(True)
        pv.addWidget(self._pair_stage)
        self._pair_progress = QProgressBar()
        self._pair_progress.setRange(0, 0)  # busy 进度条
        self._pair_progress.hide()
        pv.addWidget(self._pair_progress)
        self._pair_cancel = QPushButton("取消配对")
        self._pair_cancel.hide()
        self._pair_cancel.clicked.connect(self._on_pair_cancel)
        pv.addWidget(self._pair_cancel)
        outer.addWidget(grp_pair)
        outer.addStretch(1)

        # 保存线程
        self._pairing_thread: QThread | None = None
        self._pairing_worker: _PairingWorker | None = None
        return tab

    @staticmethod
    def _primary_btn_css() -> str:
        return (
            "QPushButton{background:#e85d75;color:#fff;border:none;"
            "border-radius:6px;padding:9px 16px;font-weight:600;}"
            "QPushButton:hover{background:#d94f68;}"
            "QPushButton:disabled{background:#d9dee4;color:#ffffff;}"
        )

    def _copy_text(self, text: str) -> None:
        if not text:
            return
        cb = QGuiApplication.clipboard()
        cb.setText(text, QClipboard.Clipboard)
        QMessageBox.information(self, "已复制", "已复制到剪贴板。")

    def _refresh_identity_ui(self) -> None:
        status = idm.get_status()
        self._id_my_fp.setText(status.my_fingerprint)
        self._id_my_pk.setText(status.my_pk_b64)
        # 昵称优先从「信箱的 my_name」取（配对时会同步用这个字段作为展示）
        mb = mb_config.load()
        nick = (mb.get("my_name") or "我").strip()
        if nick and not self._id_nick_me.isModified():
            self._id_nick_me.setText(nick[:20])
        # 对方信息
        if status.paired:
            self._cloud_pairing_status.setText(
                f"已完成公钥配对，通道 ID：{status.channel_id or '未知'}。"
                "正常使用不需要填写旧版配对码。"
            )
            self._cloud_pairing_status.setStyleSheet("color:#2f7d68; font-size:12px;")
            self._id_them_nick.setText(status.partner_nickname or "对方")
            self._id_them_fp.setText(status.partner_fingerprint or "")
            self._id_safety.setText(status.safety_code or "")
            self._id_channel.setText(status.channel_id or "")
            self._btn_reset_partner.setEnabled(True)
        else:
            self._cloud_pairing_status.setText(
                "尚未完成公钥配对。请先填写服务器地址并保存，"
                "再到「联机身份」页完成一次配对。"
            )
            self._cloud_pairing_status.setStyleSheet("color:#a56d2f; font-size:12px;")
            self._id_them_nick.setText("")
            self._id_them_fp.setText("")
            self._id_safety.setText("")
            self._id_channel.setText("")
            self._btn_reset_partner.setEnabled(False)

    def _show_safety_dialog(self) -> None:
        status = idm.get_status()
        if not status.paired or not status.safety_code:
            QMessageBox.information(self, "安全码", "尚未与对方配对，没有安全码。")
            return
        code = status.safety_code
        nick = status.partner_nickname or "对方"
        QMessageBox.information(
            self,
            "核对安全码",
            f"请通过电话/微信等<u>安全渠道</u>让对方打开「设置 → 联机身份 → 安全码」，<br>"
            f"并念一下屏幕上的 6 位数字。<br><br>"
            f"你这边显示的安全码为：<br>"
            f"<div style='font-size:36px;font-weight:900;color:#e85d75;"
            f"letter-spacing:12px;text-align:center;margin:12px 0;'>{code}</div>"
            f"如果两边数字<b>完全一样</b>，说明你们之间没有中间人，可以放心使用。<br>"
            f"如果<b>不一样</b>，说明你们之间有人被转发了消息，请到设置里「解除配对」后重新开始。"
        )

    def _on_reset_partner(self) -> None:
        ans = QMessageBox.question(
            self, "确认解除配对",
            "解除后本机将不再信任对方发来的签名消息，对方那边也需要解除。真的继续吗？",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No,
        )
        if ans != QMessageBox.Yes:
            return
        idm.reset_partner()
        self._refresh_identity_ui()
        QMessageBox.information(self, "已解除", "已解除配对。")

    # ---------- 配对向导 ----------

    def _on_start_host(self) -> None:
        mb = mb_config.load()
        server = (mb.get("cloud_server") or "").strip()
        if not server:
            QMessageBox.warning(
                self, "缺少云中转服务器",
                "发起配对必须先在「同步」页填好「云中转服务器地址」并保存。\n"
                "（你们双方的消息都靠这台服务器的配对接口做公钥交换，局域网直连不需要交换公钥，但为了安全码可校验，仍要求走一次配对向导。）"
            )
            return
        nick = (self._id_nick_me.text() or "我").strip() or "我"
        self._start_pairing_thread("host", None, server, nick)

    def _on_start_guest(self) -> None:
        mb = mb_config.load()
        server = (mb.get("cloud_server") or "").strip()
        if not server:
            QMessageBox.warning(
                self, "缺少云中转服务器",
                "先到「同步」页填好「云中转服务器地址」并保存。"
            )
            return
        token, ok = QInputDialog.getText(
            self, "输入 6 位配对码",
            "请输入对方屏幕上显示的 6 位配对码（不区分大小写，不含字母 I/L/O/0）："
        )
        if not ok:
            return
        nick = (self._id_nick_me.text() or "我").strip() or "我"
        self._start_pairing_thread("guest", token.strip(), server, nick)

    def _start_pairing_thread(self, mode: str, token: str | None, server: str, nickname: str) -> None:
        self._pair_progress.show()
        self._pair_cancel.show()
        self._btn_host.setEnabled(False)
        self._btn_guest.setEnabled(False)
        self._pairing_thread = QThread(self)
        self._pairing_worker = _PairingWorker(mode, token, server, nickname)
        self._pairing_worker.moveToThread(self._pairing_thread)
        self._pairing_thread.started.connect(self._pairing_worker.run)
        self._pairing_worker.progress.connect(self._on_pair_progress)
        self._pairing_thread.start()

    def _on_pair_cancel(self) -> None:
        if self._pairing_worker is not None:
            try:
                self._pairing_worker.cancel()
            except Exception:
                pass
        self._pair_finished()
        self._pair_stage.setText("已取消。")

    def _pair_finished(self) -> None:
        if self._pairing_thread is not None:
            self._pairing_thread.quit()
            self._pairing_thread.wait(3000)
            self._pairing_thread = None
        self._pairing_worker = None
        self._pair_progress.hide()
        self._pair_cancel.hide()
        self._btn_host.setEnabled(True)
        self._btn_guest.setEnabled(True)

    def _on_pair_progress(self, p: PairingProgress) -> None:
        phase = p.phase
        if phase == PairingPhase.WAITING_PARTNER:
            if p.token:
                self._pair_stage.setText(
                    "正在等待对方输入配对码……<br>"
                    f"<div style='font-size:48px;font-weight:900;color:#e85d75;"
                    f"letter-spacing:24px;text-align:center;margin:16px 0;'>{p.token}</div>"
                    "<b>请把这 6 位数字告诉对方</b>（微信/电话都可以，它是一次性短期胶水，泄漏也没用），"
                    "对方在设置里选「② 输入对方的 6 位配对码」即可。"
                )
            else:
                self._pair_stage.setText("已提交配对码，正在与发起方握手……（最长 10 分钟内有效）")
        elif phase == PairingPhase.SHOW_SAFETY:
            # UI 线程弹对话框：安全码核对
            safety = p.safety_code or "??????"
            nick = p.partner_nickname or "对方"
            ans = QMessageBox.question(
                self, "核对安全码",
                f"已收到「{nick}」的配对请求。<br><br>"
                f"请让对方打开「设置 → 联机身份 → 安全码」念一下他屏幕上的 6 位数字，<br>"
                f"你这边显示的安全码为：<br>"
                f"<div style='font-size:36px;font-weight:900;color:#e85d75;"
                f"letter-spacing:12px;text-align:center;margin:12px 0;'>{safety}</div>"
                f"两边数字<b>完全一样吗？</b>"
            )
            matched = (ans == QMessageBox.Yes)
            if self._pairing_worker is not None:
                self._pairing_worker.confirm_safety(matched)
            if not matched:
                self._pair_finished()
                self._pair_stage.setText("你取消了安全码核对，配对已停止。")
        elif phase == PairingPhase.DONE:
            self._pair_finished()
            self._refresh_identity_ui()
            self._pair_stage.setText(
                f"<font color='#2f7d68'><b>配对成功！</b></font><br>"
                f"专属通道 ID：{p.channel_id or ''}<br>"
                f"你们之间的所有信件/照片/五子棋都由 Ed25519 签名校验，外人再也冒充不了。<br>"
                f"如果以后想换配对对象，随时可以点「解除配对」重来。"
            )
            self.settings_changed.emit()  # 通知外部重建 hub 走 channel 模式
        elif phase == PairingPhase.FAILED:
            self._pair_finished()
            msg = p.error_message or "配对失败"
            self._pair_stage.setText(
                f"<font color='#b04a5a'><b>配对失败：</b></font>{msg}"
            )

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
        self._pf_color_edit.setText(str(pf.get("theme_color", "#e85d75")))

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

        # 身份页初始化
        self._refresh_identity_ui()

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
        item = self._album_list.item(row)
        if item is None:
            return
        album_name = item.text().split("→")[0].strip() if "→" in item.text() else item.text()
        # 删除前确认
        if QMessageBox.question(
            self, "确认删除",
            f"确定要删除相册「{album_name}」吗？\n（不会删除硬盘上的图片文件，只是从相册列表里移除）"
        ) != QMessageBox.Yes:
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
            theme_color=self._pf_color_edit.text().strip() or "#e85d75",
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
        # 保存成功后仅 statusBar 提示，不弹模态对话框
        self.statusBar().showMessage("设置已保存并生效", 3000)
