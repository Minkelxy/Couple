"""打卡日历主窗口。"""
from __future__ import annotations

import time
import weakref
from datetime import date
from pathlib import Path
from PIL import Image, ImageOps

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QButtonGroup, QDialog, QFileDialog, QHBoxLayout, QLabel,
    QLineEdit, QListWidget, QListWidgetItem, QMainWindow, QMessageBox,
    QPushButton, QVBoxLayout, QWidget,
)

import app_paths
from common_utils import (
    atomic_copy_file,
    check_attachment_size,
    log_warning,
    safe_filename,
    safe_image_ext,
)

from . import store
from .calendar_widget import CalendarWidget
from .mood_chart import MoodChart


def _resolve_checkin_image(image_path: str) -> str:
    """将 image_path 解析为完整路径：纯文件名拼接到 CHECKIN_DIR/images。

    旧数据可能是绝对路径，原样返回；新数据为纯文件名，拼接后返回。
    """
    if not image_path:
        return ""
    p = Path(image_path)
    if p.is_absolute() or len(p.parts) > 1:
        return image_path
    return str(app_paths.CHECKIN_DIR / "images" / image_path)

# 心情按钮顺序：😊(5) 😍(4) 😢(3) 😡(2) 😴(1)
_MOOD_CHOICES = [(5, "😊"), (4, "😍"), (3, "😢"), (2, "😡"), (1, "😴")]

# 当前 CheckinWindow 实例，供模块级事件处理刷新 UI
# 用弱引用：窗口关闭且无其他强引用时可被 GC，避免内存泄漏
_active_window: weakref.ref | None = None


def _save_partner_image(attachment: bytes, att_ext: str, date_str: str) -> str:
    """保存对方发来的打卡图片到 partner_images/，返回文件名（失败返回空串）。

    安全：attachment 大小校验，date_str 用 safe_filename 过滤防路径遍历。
    """
    if not attachment:
        return ""
    # 附件大小校验
    err = check_attachment_size(attachment)
    if err is not None:
        log_warning("拒绝接收对方打卡图片: %s", err)
        return ""
    ext = safe_image_ext(att_ext)
    # date_str 来自网络输入，过滤为安全文件名片段
    safe_date = safe_filename(date_str, fallback="partner")
    filename = f"{int(time.time())}_{safe_date}{ext}"
    dest_dir = store.PARTNER_IMAGES_DIR
    dest_dir.mkdir(parents=True, exist_ok=True)
    dest = dest_dir / filename
    try:
        dest.write_bytes(attachment)
        return filename
    except OSError:
        log_warning("写入对方打卡图片失败: %s", filename)
        return ""


def handle_partner_event(meta: dict, content: str, attachment: bytes,
                         att_ext: str) -> None:
    """模块级事件处理：写入对方打卡记录，并刷新已存在的窗口侧栏与日历。

    供 launcher 路由器调用，无需窗口实例即可落盘。
    """
    date_str = meta.get("date", "")
    try:
        mood = int(meta.get("mood", 0))
    except (TypeError, ValueError):
        mood = 0
    note = meta.get("note", "") or ""
    image_path = _save_partner_image(attachment, att_ext, date_str)
    store.add_partner_record(date_str, mood, note, image_path)
    win = _active_window() if _active_window is not None else None
    if win is not None:
        win.refresh_partner_sidebar()
        win._calendar.refresh()


class CheckinEditor(QDialog):
    """打卡编辑对话框。"""

    def __init__(self, date_str: str, parent=None) -> None:
        super().__init__(parent)
        self._date = date_str
        self._mood: int = 0
        self._image_path: str = ""
        self._build_ui()
        self._load_existing()

    def _build_ui(self) -> None:
        self.setWindowTitle(f"打卡 · {self._date}")
        self.setMinimumWidth(380)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 20, 24, 20)
        layout.setSpacing(14)

        title = QLabel(f"📅 {self._date}", self)
        title.setStyleSheet("font-size:16px; font-weight:600; color:#e65a7a;")
        layout.addWidget(title)

        # 心情选择
        mood_label = QLabel("今天心情如何？", self)
        mood_label.setStyleSheet("font-size:14px; color:#555;")
        layout.addWidget(mood_label)

        mood_row = QHBoxLayout()
        mood_row.setSpacing(8)
        self._mood_group = QButtonGroup(self)
        self._mood_buttons: dict[int, QPushButton] = {}
        for mood_val, emoji in _MOOD_CHOICES:
            btn = QPushButton(emoji, self)
            btn.setFixedSize(48, 48)
            btn.setCheckable(True)
            btn.setStyleSheet(
                "QPushButton{font-size:24px; border:2px solid #eee;"
                "border-radius:24px; background:#fff;}"
                "QPushButton:checked{border:2px solid #e65a7a; background:#fdf2f5;}"
                "QPushButton:hover{border:2px solid #f0a0b0;}"
            )
            self._mood_group.addButton(btn)
            self._mood_buttons[mood_val] = btn
            btn.clicked.connect(lambda _, v=mood_val: self._select_mood(v))
            mood_row.addWidget(btn)
        mood_row.addStretch(1)
        layout.addLayout(mood_row)

        # 一句话
        text_label = QLabel("一句话记录：", self)
        text_label.setStyleSheet("font-size:14px; color:#555;")
        layout.addWidget(text_label)
        self._text_edit = QLineEdit(self)
        self._text_edit.setMaxLength(100)
        self._text_edit.setPlaceholderText("今天最想说的一句话…（最多 100 字）")
        self._text_edit.setStyleSheet(
            "QLineEdit{border:1px solid #ddd; border-radius:6px;"
            "padding:8px; font-size:14px;}"
            "QLineEdit:focus{border:1px solid #e65a7a;}"
        )
        layout.addWidget(self._text_edit)

        # 图片选择
        img_row = QHBoxLayout()
        self._img_btn = QPushButton("📷 选择图片", self)
        self._img_btn.setStyleSheet(
            "QPushButton{background:#fdf2f5; color:#e65a7a;"
            "border:1px solid #e65a7a; border-radius:6px; padding:8px 16px;"
            "font-size:13px;}"
            "QPushButton:hover{background:#fce4ea;}"
        )
        self._img_btn.clicked.connect(self._pick_image)
        self._img_label = QLabel("未选择", self)
        self._img_label.setStyleSheet("color:#999; font-size:12px;")
        img_row.addWidget(self._img_btn)
        img_row.addWidget(self._img_label, 1)
        layout.addLayout(img_row)

        layout.addStretch(1)

        # 保存按钮
        self._save_btn = QPushButton("保存 💾", self)
        self._save_btn.setStyleSheet(
            "QPushButton{background:#e65a7a; color:#fff; border:none;"
            "border-radius:8px; padding:10px; font-size:15px;}"
            "QPushButton:hover{background:#d94a6a;}"
        )
        self._save_btn.clicked.connect(self._save)
        layout.addWidget(self._save_btn)

    def _select_mood(self, mood: int) -> None:
        self._mood = mood

    def _pick_image(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self, "选择图片", "", "图片 (*.png *.jpg *.jpeg *.bmp *.gif)"
        )
        if not path:
            return
        filename = f"{int(time.time())}_{Path(path).name}"
        dest = app_paths.CHECKIN_DIR / "images" / filename
        try:
            # 用 PIL 打开并统一 EXIF 方向，避免手机竖拍照片横躺
            with Image.open(path) as src_img:
                src_img.load()
                img = ImageOps.exif_transpose(src_img).copy()
            img.save(dest)
        except Exception:
            # PIL 处理失败（非图片格式或损坏等），回退到直接复制原图
            try:
                atomic_copy_file(path, dest)
            except OSError:
                QMessageBox.warning(self, "错误", "无法读取该图片，请换一张。")
                return
        self._image_path = filename
        self._img_label.setText(str(dest))

    def _load_existing(self) -> None:
        rec = store.get_by_date(self._date)
        if not rec:
            return
        self._mood = rec["mood"]
        if rec["mood"] in self._mood_buttons:
            self._mood_buttons[rec["mood"]].setChecked(True)
        self._text_edit.setText(rec["text"] or "")
        if rec["image_path"]:
            self._image_path = rec["image_path"]
            self._img_label.setText(_resolve_checkin_image(rec["image_path"]))

    def _save(self) -> None:
        if self._mood == 0:
            QMessageBox.warning(self, "提示", "请先选择心情哦～")
            return
        store.add_or_update(
            self._date, self._mood,
            self._text_edit.text().strip(), self._image_path,
        )
        self.accept()


class CheckinWindow(QMainWindow):
    """打卡日历主窗口。"""

    def __init__(self, hub=None) -> None:
        super().__init__()
        self._hub = hub
        global _active_window
        _active_window = weakref.ref(self)
        self.setWindowTitle("打卡日历 📅")
        self.resize(1180, 650)
        self._build_ui()
        self._refresh_chart()
        self.refresh_partner_sidebar()

    def set_hub(self, hub) -> None:
        """设置变更时热更新同步引用（避免使用已停止的旧 hub）。"""
        self._hub = hub

    def _build_ui(self) -> None:
        central = QWidget(self)
        self.setCentralWidget(central)
        layout = QHBoxLayout(central)
        layout.setContentsMargins(20, 16, 20, 16)
        layout.setSpacing(16)

        # ---- 左侧：日历 + 连续打卡 + 今日打卡按钮 ----
        left = QVBoxLayout()
        left.setSpacing(12)
        self._calendar = CalendarWidget(self)
        self._calendar.day_clicked.connect(self._on_day_clicked)
        left.addWidget(self._calendar)

        self._streak_label = QLabel("", self)
        self._streak_label.setAlignment(Qt.AlignCenter)
        self._streak_label.setStyleSheet(
            "background:#fdf2f5; border-radius:10px; padding:10px;"
            "font-size:15px; color:#333;"
        )
        left.addWidget(self._streak_label)

        self._today_btn = QPushButton("📝 今日打卡", self)
        self._today_btn.setStyleSheet(
            "QPushButton{background:#e65a7a; color:#fff; border:none;"
            "border-radius:8px; padding:12px; font-size:15px;}"
            "QPushButton:hover{background:#d94a6a;}"
        )
        self._today_btn.clicked.connect(self._checkin_today)
        left.addWidget(self._today_btn)

        left.addStretch(1)
        layout.addLayout(left, 1)

        # ---- 右侧：心情趋势图 + 切换按钮 ----
        right = QVBoxLayout()
        right.setSpacing(10)
        self._chart = MoodChart(self)
        right.addWidget(self._chart, 1)

        self._refresh_btn = QPushButton("🔄 查看心情趋势", self)
        self._refresh_btn.setStyleSheet(
            "QPushButton{background:#fdf2f5; color:#e65a7a;"
            "border:1px solid #e65a7a; border-radius:8px; padding:8px;"
            "font-size:13px;}"
            "QPushButton:hover{background:#fce4ea;}"
        )
        self._refresh_btn.clicked.connect(self._refresh_chart)
        right.addWidget(self._refresh_btn)
        layout.addLayout(right, 1)

        # ---- 最右：对方的心情 ----
        partner_col = QVBoxLayout()
        partner_col.setSpacing(8)
        partner_title = QLabel("对方的心情 💙", self)
        partner_title.setStyleSheet(
            "font-size:14px; font-weight:600; color:#3a7bd5;"
        )
        partner_col.addWidget(partner_title)
        self._partner_list = QListWidget(self)
        self._partner_list.setFixedWidth(210)
        self._partner_list.setStyleSheet(
            "QListWidget{border:1px solid #d8e4ff; border-radius:8px;"
            "background:#f5f9ff; font-size:13px;}"
            "QListWidget::item{padding:8px 6px; border-bottom:1px solid #eaf1ff;}"
        )
        partner_col.addWidget(self._partner_list)
        layout.addLayout(partner_col, 0)

        self._update_streak()

    def _update_streak(self) -> None:
        streak = store.get_streak()
        self._streak_label.setText(f"🔥 连续打卡 {streak} 天")

    def _refresh_chart(self) -> None:
        records = store.get_recent(30)
        self._chart.update_data(records)
        self._calendar.refresh()
        self._update_streak()

    def refresh_partner_sidebar(self) -> None:
        """刷新右侧"对方的心情"侧栏，显示对方最近 7 天打卡。"""
        self._partner_list.clear()
        records = store.list_partner_records(7)
        if not records:
            item = QListWidgetItem("暂无对方的打卡")
            item.setFlags(item.flags() & ~Qt.ItemIsSelectable & ~Qt.ItemIsEnabled)
            self._partner_list.addItem(item)
            return
        for rec in records:
            mood = rec.get("mood", 0)
            emoji = store.MOOD_MAP.get(mood, "🙂")
            note = rec.get("note", "") or ""
            date_str = rec.get("date", "")
            text = f"{emoji}  {date_str}"
            if note:
                text += f"\n    {note}"
            self._partner_list.addItem(QListWidgetItem(text))

    def _send_checkin(self, date_str: str) -> None:
        """保存打卡后同步给对方（hub 为 None 时跳过）。"""
        if self._hub is None:
            return
        rec = store.get_by_date(date_str)
        if not rec:
            return
        payload = {
            "date": date_str,
            "mood": rec["mood"],
            "note": rec["text"] or "",
        }
        attachment: bytes | None = None
        att_ext = ""
        if rec.get("image_path"):
            full = _resolve_checkin_image(rec["image_path"])
            if full and Path(full).exists():
                try:
                    attachment = Path(full).read_bytes()
                    att_ext = Path(full).suffix
                except OSError:
                    attachment = None
        self._hub.send_event("checkin", payload, attachment=attachment, att_ext=att_ext, silent=True)

    def on_partner_event(self, meta: dict, content: str, attachment: bytes,
                         att_ext: str) -> None:
        """收到对方打卡事件：落盘并刷新 UI。"""
        handle_partner_event(meta, content, attachment, att_ext)

    def _checkin_today(self) -> None:
        today = date.today().isoformat()
        editor = CheckinEditor(today, self)
        if editor.exec() == QDialog.Accepted:
            self._refresh_chart()
            self._send_checkin(today)

    def _on_day_clicked(self, date_str: str) -> None:
        if store.get_by_date(date_str):
            # 已有打卡：编辑
            editor = CheckinEditor(date_str, self)
            if editor.exec() == QDialog.Accepted:
                self._refresh_chart()
                self._send_checkin(date_str)
            return
        # 补卡：仅过去 7 天内
        clicked = date.fromisoformat(date_str)
        today = date.today()
        if clicked > today:
            QMessageBox.information(self, "提示", "未来的日子还没到哦～")
            return
        if (today - clicked).days > 7:
            QMessageBox.information(self, "提示", "仅可补过去 7 天")
            return
        editor = CheckinEditor(date_str, self)
        if editor.exec() == QDialog.Accepted:
            self._refresh_chart()
            self._send_checkin(date_str)
