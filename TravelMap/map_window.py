"""旅行地图主窗口。

继承 QMainWindow，标题"旅行地图 🗺"，初始尺寸 1000x750。
中央 QLabel 显示地图渲染结果，底部统计 + 操作按钮 + 城市列表。
"""
from __future__ import annotations

import time
from datetime import date
from pathlib import Path

from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QPixmap
from PySide6.QtWidgets import (
    QButtonGroup, QDateEdit, QDialog, QFileDialog, QHBoxLayout, QLabel,
    QListWidget, QListWidgetItem, QMainWindow, QMessageBox, QPushButton,
    QRadioButton, QSizePolicy, QTextEdit, QVBoxLayout, QWidget,
)

import app_paths
from common_utils import (
    atomic_copy_file,
    check_attachment_size,
    log_warning,
    safe_filename,
    safe_image_ext,
)

from . import city_picker
from . import store
from .china_map_widget import ChinaMapWidget

PINK = "#e65a7a"
CARD_BG = "#fdf2f5"


def _resolve_travel_photo(image_path: str) -> str:
    """将 image_path 解析为完整路径：纯文件名拼接到 TRAVEL_DIR/photos，
    含子目录的相对路径（如 partner_photos/xxx.jpg）拼接到 TRAVEL_DIR。

    旧数据可能是绝对路径，原样返回。
    """
    if not image_path:
        return ""
    p = Path(image_path)
    if p.is_absolute():
        return image_path
    if len(p.parts) > 1:
        # 含子目录的相对路径（如 partner_photos/xxx.jpg），拼接到 TRAVEL_DIR
        return str(app_paths.TRAVEL_DIR / image_path)
    # 纯文件名，拼接到 photos 子目录
    return str(app_paths.TRAVEL_DIR / "photos" / image_path)


def handle_partner_event(meta: dict, content: str, attachment: bytes,
                         att_ext: str) -> None:
    """收到对方 map 事件：追加为 partner 城市记录。

    若附带照片字节，存入 TRAVEL_DIR/partner_photos/，再调 store.add_partner_city。
    安全：city 来自网络输入，用 safe_filename 过滤防路径遍历；attachment 大小校验。
    """
    city = meta.get("city", "")
    if not city:
        return
    # 防御：lat/lng 是网络输入，非数字会在 store 里 float() 抛 ValueError
    try:
        lat = float(meta.get("lat", 0.0) or 0)
        lng = float(meta.get("lng", 0.0) or 0)
    except (TypeError, ValueError):
        log_warning("收到对方 map 事件的非法 lat/lng: %r, %r",
                    meta.get("lat"), meta.get("lng"))
        return
    note = meta.get("note", "")
    photo_filename = ""
    if attachment:
        # 附件大小校验
        err = check_attachment_size(attachment)
        if err is not None:
            log_warning("拒绝接收对方旅行照片: %s", err)
        else:
            ext = safe_image_ext(att_ext)
            # city 来自网络输入，过滤为安全文件名片段
            safe_city = safe_filename(city, fallback="city")
            filename = f"{int(time.time())}_{safe_city}{ext}"
            dest_dir = app_paths.TRAVEL_DIR / "partner_photos"
            dest_dir.mkdir(parents=True, exist_ok=True)
            dest = dest_dir / filename
            try:
                dest.write_bytes(attachment)
                photo_filename = f"partner_photos/{filename}"
            except OSError:
                log_warning("写入对方旅行照片失败: %s", filename)
    store.add_partner_city(city, lat, lng, note, photo_filename)


class _EditCityDialog(QDialog):
    """编辑/添加城市详情对话框：日期、故事、照片、类型。"""

    def __init__(self, parent=None, city: dict | None = None,
                 default_type: str = "visited") -> None:
        super().__init__(parent)
        self.setWindowTitle("城市详情 ✏")
        self.resize(380, 440)
        self._city = city or {}
        self._image_path = self._city.get("image_path", "")
        self._build_ui(default_type)

    def _build_ui(self, default_type: str) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 18, 20, 18)
        layout.setSpacing(10)

        name = self._city.get("name") or self._city.get("city_name", "")
        title = QLabel(f"✏ {name}" if name else "➕ 添加城市", self)
        title.setStyleSheet(f"font-size:18px; font-weight:600; color:{PINK};")
        layout.addWidget(title)

        # 日期
        layout.addWidget(QLabel("📅 日期：", self))
        self.date_edit = QDateEdit(self)
        self.date_edit.setDisplayFormat("yyyy-MM-dd")
        self.date_edit.setCalendarPopup(True)
        self.date_edit.setStyleSheet(
            "QDateEdit{padding:6px;border:1px solid #ddd;border-radius:6px;font-size:14px;}"
        )
        d = self._city.get("date", "")
        if d:
            try:
                parts = d.split("-")
                self.date_edit.setDate(date(int(parts[0]), int(parts[1]), int(parts[2])))
            except (ValueError, IndexError):
                self.date_edit.setDate(date.today())
        else:
            self.date_edit.setDate(date.today())
        layout.addWidget(self.date_edit)

        # 故事
        layout.addWidget(QLabel("💭 故事：", self))
        self.story_edit = QTextEdit(self)
        self.story_edit.setPlainText(self._city.get("story", ""))
        self.story_edit.setStyleSheet(
            "QTextEdit{border:1px solid #ddd;border-radius:6px;padding:6px;font-size:14px;}"
        )
        layout.addWidget(self.story_edit)

        # 类型
        type_row = QHBoxLayout()
        type_row.addWidget(QLabel("类型：", self))
        self.rb_visited = QRadioButton("🌸 已去过", self)
        self.rb_wish = QRadioButton("✨ 愿望", self)
        self.type_group = QButtonGroup(self)
        self.type_group.addButton(self.rb_visited)
        self.type_group.addButton(self.rb_wish)
        cur_type = self._city.get("type", default_type)
        if cur_type == "wish":
            self.rb_wish.setChecked(True)
        else:
            self.rb_visited.setChecked(True)
        type_row.addWidget(self.rb_visited)
        type_row.addWidget(self.rb_wish)
        type_row.addStretch(1)
        layout.addLayout(type_row)

        # 照片
        photo_row = QHBoxLayout()
        self.photo_btn = QPushButton("📷 选择照片", self)
        self.photo_btn.setStyleSheet(
            "QPushButton{background:#eee;color:#666;border:none;border-radius:6px;padding:8px 12px;}"
            "QPushButton:hover{background:#ddd;}"
        )
        self.photo_path_label = QLabel(
            _resolve_travel_photo(self._image_path) or "未选择", self
        )
        self.photo_path_label.setStyleSheet("color:#999;font-size:12px;")
        self.photo_path_label.setMinimumWidth(120)
        self.photo_btn.clicked.connect(self._pick_photo)
        photo_row.addWidget(self.photo_btn)
        photo_row.addWidget(self.photo_path_label, 1)
        layout.addLayout(photo_row)

        # 按钮行
        layout.addStretch(1)
        btn_row = QHBoxLayout()
        cancel_btn = QPushButton("取消", self)
        cancel_btn.setStyleSheet(
            "QPushButton{background:#eee;color:#666;border:none;border-radius:6px;padding:8px 16px;}"
            "QPushButton:hover{background:#ddd;}"
        )
        ok_btn = QPushButton("保存", self)
        ok_btn.setStyleSheet(
            f"QPushButton{{background:{PINK};color:#fff;border:none;border-radius:6px;padding:8px 16px;}}"
            f"QPushButton:hover{{background:#d94a6a;}}"
        )
        cancel_btn.clicked.connect(self.reject)
        ok_btn.clicked.connect(self.accept)
        btn_row.addStretch(1)
        btn_row.addWidget(cancel_btn)
        btn_row.addWidget(ok_btn)
        layout.addLayout(btn_row)

    def _pick_photo(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self, "选择照片", "", "图片 (*.png *.jpg *.jpeg *.bmp)"
        )
        if not path:
            return
        filename = f"{int(time.time())}_{Path(path).name}"
        dest = app_paths.TRAVEL_DIR / "photos" / filename
        try:
            atomic_copy_file(path, dest)
        except OSError:
            QMessageBox.warning(self, "错误", "无法读取该照片，请换一张。")
            return
        self._image_path = filename
        self.photo_path_label.setText(str(dest))

    def values(self) -> dict:
        return {
            "date": self.date_edit.date().toString("yyyy-MM-dd"),
            "story": self.story_edit.toPlainText().strip(),
            "image_path": self._image_path,
            "type": "wish" if self.rb_wish.isChecked() else "visited",
        }


class _DetailDialog(QDialog):
    """城市详情卡片：显示城市名、日期、故事、照片，提供编辑/删除按钮。"""

    def __init__(self, parent, city: dict, on_edit=None, on_delete=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("城市详情 📍")
        self.resize(360, 480)
        self._on_edit = on_edit
        self._on_delete = on_delete
        self._build_ui(city)

    def _build_ui(self, city: dict) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 18, 20, 18)
        layout.setSpacing(10)

        title = QLabel(f"📍 {city.get('city_name', '')}", self)
        title.setStyleSheet(f"font-size:20px; font-weight:600; color:{PINK};")
        layout.addWidget(title)

        ctype = city.get("type", "visited")
        type_text = "✨ 愿望清单" if ctype == "wish" else "🌸 已去过"
        type_label = QLabel(type_text, self)
        type_label.setStyleSheet("color:#888;font-size:13px;")
        layout.addWidget(type_label)

        date_str = city.get("date", "")
        if date_str:
            layout.addWidget(QLabel(f"📅 {date_str}", self))

        # 照片
        img_path = _resolve_travel_photo(city.get("image_path", ""))
        if img_path and Path(img_path).exists():
            photo = QLabel(self)
            pm = QPixmap(img_path)
            if not pm.isNull():
                photo.setPixmap(pm.scaledToWidth(320, Qt.SmoothTransformation))
                layout.addWidget(photo)

        # 故事
        story = city.get("story", "")
        if story:
            story_label = QLabel("💭 我们的故事：", self)
            story_label.setStyleSheet("color:#888;font-size:13px;")
            layout.addWidget(story_label)
            story_text = QLabel(story, self)
            story_text.setWordWrap(True)
            story_text.setStyleSheet(
                f"background:{CARD_BG};border-radius:8px;padding:10px;font-size:14px;"
            )
            layout.addWidget(story_text)

        layout.addStretch(1)

        # 按钮行
        btn_row = QHBoxLayout()
        edit_btn = QPushButton("编辑", self)
        edit_btn.setStyleSheet(
            f"QPushButton{{background:{PINK};color:#fff;border:none;border-radius:6px;padding:8px 16px;}}"
            f"QPushButton:hover{{background:#d94a6a;}}"
        )
        del_btn = QPushButton("删除", self)
        del_btn.setStyleSheet(
            "QPushButton{background:#eee;color:#c0392b;border:none;border-radius:6px;padding:8px 16px;}"
            "QPushButton:hover{background:#ddd;}"
        )
        close_btn = QPushButton("关闭", self)
        close_btn.setStyleSheet(
            "QPushButton{background:#eee;color:#666;border:none;border-radius:6px;padding:8px 16px;}"
            "QPushButton:hover{background:#ddd;}"
        )
        edit_btn.clicked.connect(self._do_edit)
        del_btn.clicked.connect(self._do_delete)
        close_btn.clicked.connect(self.accept)
        btn_row.addWidget(edit_btn)
        btn_row.addWidget(del_btn)
        btn_row.addStretch(1)
        btn_row.addWidget(close_btn)
        layout.addLayout(btn_row)

    def _do_edit(self) -> None:
        if self._on_edit:
            self._on_edit()
        self.accept()

    def _do_delete(self) -> None:
        if self._on_delete:
            self._on_delete()
        self.accept()


class TravelMapWindow(QMainWindow):
    """旅行地图主窗口。"""

    def __init__(self, hub=None) -> None:
        super().__init__()
        self._hub = hub
        self.setWindowTitle("旅行地图 🗺")
        self.resize(1000, 750)
        self._default_type = "visited"
        self._route_cities: list[dict] = []
        self._route_index = 0
        self._route_timer = QTimer(self)
        self._route_timer.setInterval(800)
        self._route_timer.timeout.connect(self._on_route_tick)
        self._build_ui()
        self._refresh()

    def set_hub(self, hub) -> None:
        """设置变更时热更新同步引用（避免使用已停止的旧 hub）。"""
        self._hub = hub

    def _build_ui(self) -> None:
        central = QWidget(self)
        self.setCentralWidget(central)
        layout = QVBoxLayout(central)
        layout.setContentsMargins(16, 14, 16, 14)
        layout.setSpacing(10)

        # 地图展示区：离线 QPainter 中国地图（支持缩放/拖动/标记点击）
        self.map_widget = ChinaMapWidget(self)
        self.map_widget.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self.map_widget.setMinimumSize(900, 600)
        self.map_widget.cityClicked.connect(self._on_map_city_clicked)
        layout.addWidget(self.map_widget, 1)
        self.map_label = None  # 兼容旧引用

        # 统计 + 操作按钮
        top_bar = QHBoxLayout()
        self.stats_label = QLabel("已解锁 0 个城市 🏆", self)
        self.stats_label.setStyleSheet(f"font-size:15px; font-weight:600; color:{PINK};")
        top_bar.addWidget(self.stats_label)
        top_bar.addStretch(1)

        self.add_btn = QPushButton("➕ 添加城市", self)
        self.play_btn = QPushButton("▶ 播放路线", self)
        self.switch_btn = QPushButton("🔄 切换愿望/已去", self)
        btn_style = (
            f"QPushButton{{background:{PINK};color:#fff;border:none;"
            f"border-radius:8px;padding:8px 14px;font-size:13px;}}"
            f"QPushButton:hover{{background:#d94a6a;}}"
        )
        for btn in (self.add_btn, self.play_btn, self.switch_btn):
            btn.setStyleSheet(btn_style)
        self.add_btn.clicked.connect(self._on_add_city)
        self.play_btn.clicked.connect(self._on_play_route)
        self.switch_btn.clicked.connect(self._on_switch_type)
        top_bar.addWidget(self.add_btn)
        top_bar.addWidget(self.play_btn)
        top_bar.addWidget(self.switch_btn)
        layout.addLayout(top_bar)

        # 城市列表（点击查看详情）
        self.city_list = QListWidget(self)
        self.city_list.setMaximumHeight(140)
        self.city_list.setStyleSheet(
            "QListWidget{border:1px solid #eee;border-radius:8px;font-size:13px;}"
            "QListWidget::item{padding:6px;}"
            "QListWidget::item:selected{background:#fdf2f5;color:#e65a7a;}"
        )
        self.city_list.itemClicked.connect(self._on_city_clicked)
        layout.addWidget(self.city_list)

    # ---------- 数据刷新 ----------

    def refresh(self) -> None:
        """公开刷新入口（收到对方 map 事件后由 launcher 调用）。"""
        self._refresh()

    def _refresh(self) -> None:
        cities = store.list_all()
        n = store.count_visited()
        self.stats_label.setText(f"已解锁 {n} 个城市 🏆")

        route = self._route_cities[: self._route_index] if self._route_cities else None

        # 离线地图：QPainter 绘制
        self.map_widget.set_cities(cities)
        if route:
            self.map_widget.highlight_route(route)
        else:
            # 显式传空，清除旧的路线高亮（避免用户切到「不画路线」状态时旧路线残留）
            self.map_widget.highlight_route([])

        self.city_list.clear()
        for c in cities:
            icon = "🌸" if c.get("type") == "visited" else "✨"
            date_str = c.get("date", "")
            suffix = f"  ({date_str})" if date_str else ""
            item = QListWidgetItem(f"{icon} {c.get('city_name', '')}{suffix}")
            item.setData(Qt.UserRole, c)
            self.city_list.addItem(item)

    def _on_map_city_clicked(self, name: str) -> None:
        """真实地图上点击城市标记：找到对应记录并打开详情。"""
        if not name:
            return
        city = store.get(name)
        if not city:
            return
        city["city_name"] = name
        self._open_detail(city)

    def _reset_route(self) -> None:
        self._route_timer.stop()
        self._route_cities = []
        self._route_index = 0

    # ---------- 添加城市 ----------

    def _send_city_event(self, city: str, lat, lng, note: str,
                        image_path: str) -> None:
        """保存城市后同步给对方（hub 为 None 时跳过）。

        读取照片字节作为 attachment，att_ext 取后缀；payload 含 photo_filename。
        """
        if not self._hub:
            return
        attachment: bytes | None = None
        att_ext = ""
        if image_path:
            full = _resolve_travel_photo(image_path)
            try:
                with open(full, "rb") as f:
                    attachment = f.read()
            except OSError:
                attachment = None
            att_ext = Path(image_path).suffix  # 如 ".jpg"
        try:
            lat_f = float(lat)
            lng_f = float(lng)
        except (TypeError, ValueError):
            lat_f = 0.0
            lng_f = 0.0
        self._hub.send_event(
            "map",
            {
                "city": city,
                "lat": lat_f,
                "lng": lng_f,
                "note": note,
                "photo_filename": image_path,
            },
            attachment=attachment,
            att_ext=att_ext,
            silent=True,
        )

    def _on_add_city(self) -> None:
        self._reset_route()
        picked = city_picker.pick_city_dialog(self)
        if not picked:
            return
        dlg = _EditCityDialog(self, city=picked, default_type=self._default_type)
        if dlg.exec() == QDialog.Accepted:
            v = dlg.values()
            store.add(
                picked["name"], float(picked["lat"]), float(picked["lng"]),
                v["type"], v["date"], v["story"], v["image_path"],
            )
            self._send_city_event(
                picked["name"], picked["lat"], picked["lng"],
                v["story"], v["image_path"],
            )
            self._refresh()

    # ---------- 城市详情 ----------

    def _on_city_clicked(self, item: QListWidgetItem) -> None:
        city = item.data(Qt.UserRole)
        if not city:
            return
        self._open_detail(city)

    def _open_detail(self, city: dict) -> None:
        """打开城市详情对话框（供列表点击和地图标记点击共用）。"""
        name = city.get("city_name") or city.get("name", "")
        if not name:
            return

        def on_edit() -> None:
            self._reset_route()
            cur = store.get(name)
            if not cur:
                return
            picked = {"name": name, "lat": cur.get("lat", 0.0), "lng": cur.get("lng", 0.0)}
            dlg = _EditCityDialog(self, city={**picked, **cur}, default_type=self._default_type)
            if dlg.exec() == QDialog.Accepted:
                v = dlg.values()
                store.update(name, **v)
                self._send_city_event(
                    name, cur.get("lat", 0.0), cur.get("lng", 0.0),
                    v["story"], v["image_path"],
                )
                self._refresh()

        def on_delete() -> None:
            confirm = QMessageBox.question(
                self, "确认删除", f"确定删除 {name} 吗？",
                QMessageBox.Yes | QMessageBox.No, QMessageBox.No,
            )
            if confirm == QMessageBox.Yes:
                self._reset_route()
                store.delete(name)
                self._refresh()

        _DetailDialog(self, city, on_edit=on_edit, on_delete=on_delete).exec()

    # ---------- 路线动画 ----------

    def _on_play_route(self) -> None:
        self._route_cities = store.sorted_by_date()
        if not self._route_cities:
            QMessageBox.information(self, "提示", "还没有城市记录，先添加一些吧～")
            return
        self._route_index = 0
        self._route_timer.start()
        self._refresh()

    def _on_route_tick(self) -> None:
        if self._route_index < len(self._route_cities):
            self._route_index += 1
            self._refresh()
        else:
            self._route_timer.stop()

    # ---------- 切换默认类型 ----------

    def _on_switch_type(self) -> None:
        self._default_type = "wish" if self._default_type == "visited" else "visited"
        label = "愿望 ✨" if self._default_type == "wish" else "已去过 🌸"
        QMessageBox.information(self, "已切换", f"新增城市默认类型：{label}")

    def closeEvent(self, event) -> None:
        self._route_timer.stop()
        super().closeEvent(event)
