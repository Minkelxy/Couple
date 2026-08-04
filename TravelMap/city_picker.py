"""城市选择器：预置中国主要城市列表 + 搜索弹窗。"""
from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLineEdit, QListWidget,
    QListWidgetItem, QPushButton, QLabel,
)

PINK = "#e65a7a"

# 中国主要城市列表（含经纬度，大致真实坐标）
CHINA_CITIES: list[dict] = [
    {"name": "北京", "lat": 39.90, "lng": 116.40},
    {"name": "上海", "lat": 31.23, "lng": 121.47},
    {"name": "广州", "lat": 23.13, "lng": 113.26},
    {"name": "深圳", "lat": 22.54, "lng": 114.06},
    {"name": "杭州", "lat": 30.27, "lng": 120.15},
    {"name": "成都", "lat": 30.67, "lng": 104.07},
    {"name": "重庆", "lat": 29.56, "lng": 106.55},
    {"name": "西安", "lat": 34.34, "lng": 108.94},
    {"name": "武汉", "lat": 30.59, "lng": 114.31},
    {"name": "南京", "lat": 32.04, "lng": 118.78},
    {"name": "苏州", "lat": 31.30, "lng": 120.62},
    {"name": "厦门", "lat": 24.48, "lng": 118.09},
    {"name": "青岛", "lat": 36.07, "lng": 120.38},
    {"name": "大连", "lat": 38.91, "lng": 121.60},
    {"name": "长沙", "lat": 28.23, "lng": 112.94},
    {"name": "昆明", "lat": 25.04, "lng": 102.71},
    {"name": "大理", "lat": 25.69, "lng": 100.16},
    {"name": "丽江", "lat": 26.87, "lng": 100.23},
    {"name": "拉萨", "lat": 29.65, "lng": 91.11},
    {"name": "乌鲁木齐", "lat": 43.83, "lng": 87.62},
    {"name": "哈尔滨", "lat": 45.80, "lng": 126.53},
    {"name": "沈阳", "lat": 41.80, "lng": 123.43},
    {"name": "天津", "lat": 39.08, "lng": 117.20},
    {"name": "郑州", "lat": 34.75, "lng": 113.62},
    {"name": "合肥", "lat": 31.82, "lng": 117.27},
    {"name": "南昌", "lat": 28.68, "lng": 115.86},
    {"name": "福州", "lat": 26.07, "lng": 119.30},
    {"name": "贵阳", "lat": 26.65, "lng": 106.71},
    {"name": "南宁", "lat": 22.82, "lng": 108.37},
    {"name": "海口", "lat": 20.04, "lng": 110.20},
    {"name": "三亚", "lat": 18.25, "lng": 109.51},
    {"name": "呼和浩特", "lat": 40.84, "lng": 111.75},
    {"name": "银川", "lat": 38.49, "lng": 106.23},
    {"name": "西宁", "lat": 36.63, "lng": 101.78},
    {"name": "兰州", "lat": 36.06, "lng": 103.83},
    {"name": "太原", "lat": 37.87, "lng": 112.55},
    {"name": "石家庄", "lat": 38.04, "lng": 114.51},
    {"name": "济南", "lat": 36.65, "lng": 117.00},
    {"name": "长春", "lat": 43.82, "lng": 125.32},
    {"name": "珠海", "lat": 22.27, "lng": 113.58},
    {"name": "桂林", "lat": 25.27, "lng": 110.29},
]


def pick_city_dialog(parent=None) -> dict | None:
    """弹出城市选择对话框。

    提供搜索框 + 列表，输入文字过滤城市名。
    选中后返回 {name, lat, lng}，取消返回 None。
    """
    dlg = QDialog(parent)
    dlg.setWindowTitle("选择城市 🏙")
    dlg.resize(320, 460)

    layout = QVBoxLayout(dlg)
    layout.setContentsMargins(18, 16, 18, 16)
    layout.setSpacing(10)

    title = QLabel("选择一个城市 ✈", dlg)
    title.setStyleSheet(f"font-size:16px; font-weight:600; color:{PINK};")
    layout.addWidget(title)

    search = QLineEdit(dlg)
    search.setPlaceholderText("搜索城市名…")
    search.setStyleSheet(
        "QLineEdit{padding:8px;border:1px solid #ddd;border-radius:6px;font-size:14px;}"
        "QLineEdit:focus{border:1px solid #e65a7a;}"
    )
    layout.addWidget(search)

    list_widget = QListWidget(dlg)
    list_widget.setStyleSheet(
        "QListWidget{border:1px solid #eee;border-radius:6px;font-size:14px;}"
        "QListWidget::item{padding:8px;}"
        "QListWidget::item:selected{background:#fdf2f5;color:#e65a7a;}"
    )
    layout.addWidget(list_widget)

    def _populate(filter_text: str = ""):
        list_widget.clear()
        ft = filter_text.strip()
        for c in CHINA_CITIES:
            if ft and ft not in c["name"]:
                continue
            item = QListWidgetItem(c["name"])
            item.setData(Qt.UserRole, c)
            list_widget.addItem(item)
        if list_widget.count() > 0:
            list_widget.setCurrentRow(0)

    search.textChanged.connect(_populate)
    _populate()

    # 按钮行
    btn_row = QHBoxLayout()
    cancel_btn = QPushButton("取消", dlg)
    cancel_btn.setStyleSheet(
        "QPushButton{background:#eee;color:#666;border:none;border-radius:6px;padding:8px 16px;}"
        "QPushButton:hover{background:#ddd;}"
    )
    ok_btn = QPushButton("确定", dlg)
    ok_btn.setStyleSheet(
        f"QPushButton{{background:{PINK};color:#fff;border:none;border-radius:6px;padding:8px 16px;}}"
        f"QPushButton:hover{{background:#d94a6a;}}"
    )
    btn_row.addStretch(1)
    btn_row.addWidget(cancel_btn)
    btn_row.addWidget(ok_btn)
    layout.addLayout(btn_row)

    result: dict | None = {"value": None}

    def _accept():
        cur = list_widget.currentItem()
        if cur is not None:
            result["value"] = cur.data(Qt.UserRole)
            dlg.accept()

    ok_btn.clicked.connect(_accept)
    cancel_btn.clicked.connect(dlg.reject)
    list_widget.itemDoubleClicked.connect(lambda _it: _accept())

    if dlg.exec() == QDialog.Accepted:
        return result["value"]
    return None
