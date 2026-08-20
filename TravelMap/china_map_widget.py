"""中国地图 widget：QPainter 绘制真实省界 + 缩放/拖动/标记交互，完全离线。

特性：
- 离线：边界数据来自 assets/china_geo.json（DataV.GeoAtlas 真实省级行政区）
- 仅限中国：经纬度范围 lng 72-140, lat 15-54
- 真实省界：35 个省级行政区（含台湾、香港、澳门、海南）
- 缩放：滚轮缩放（0.5x - 12x，以鼠标位置为中心）
- 拖动：鼠标左键按住拖动平移
- 标记：城市标记按 source/type 分色（自己粉色 / 对方蓝色 / 愿望空心）
- 路线：按顺序粉色虚线连接
- 点击：点击标记触发 cityClicked 信号
- 双击：双击空白处重置视图
"""
from __future__ import annotations

from typing import Optional

from PySide6.QtCore import (
    QPointF, QRectF, Qt, Signal,
)
from PySide6.QtGui import (
    QBrush, QColor, QMouseEvent, QPainter, QPen, QPolygonF,
    QWheelEvent,
)
from PySide6.QtWidgets import QApplication, QWidget

from .china_outline import (
    all_polygons, load_provinces,
    LAT_MAX, LAT_MIN, LNG_MAX, LNG_MIN,
)


# 配色
_BG_COLOR = QColor("#eef5f7")             # 海洋浅青
_LAND_COLOR = QColor("#f8fbfc")           # 国土浅白
_LAND_OUTLINE = QColor("#b9c8cf")         # 国土描边
_PROVINCE_OUTLINE = QColor(170, 187, 195)  # 省界
_VISITED_COLOR = QColor("#e85d75")        # 自己 / 已去过（珊瑚）
_PARTNER_COLOR = QColor("#4d7ea8")        # 对方共享（蓝色）
_ROUTE_COLOR = QColor("#e85d75")          # 路线珊瑚
_TEXT_COLOR = QColor(38, 50, 56)


class ChinaMapWidget(QWidget):
    """中国地图 widget：QPainter 自绘真实省界 + 缩放/拖动交互。"""

    cityClicked = Signal(str)

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self.setMouseTracking(True)
        self.setMinimumSize(800, 600)

        # 视图变换
        self._scale = 1.0          # 缩放倍数
        self._offset = QPointF(0, 0)  # 拖动偏移（屏幕像素）
        self._dragging = False
        self._last_pos = QPointF()

        # 预加载省份多边形数据（只加载一次）
        self._provinces = load_provinces()
        self._all_polys = all_polygons()

        # 数据
        self._cities: list[dict] = []
        self._route: list[dict] = []

        # 省界屏幕坐标缓存：仅在视图变换（尺寸/缩放/偏移）变化时重算
        # paintEvent 每帧都调 _draw_provinces，中国省界数千顶点，缓存避免重复投影
        self._cached_fill: list[QPolygonF] = []
        self._cached_outline: list[list[QPointF]] = []
        self._cache_key: tuple = ()  # (w, h, scale, offset.x, offset.y)

    # ---------- 公共接口 ----------

    def set_cities(self, cities: list[dict]) -> None:
        """设置城市标记数据并重绘。"""
        self._cities = list(cities)
        self.update()

    def highlight_route(self, cities: list[dict]) -> None:
        """设置高亮路线（按顺序连接）。"""
        self._route = list(cities)
        self.update()

    def clear_map(self) -> None:
        """清空标记和路线。"""
        self._cities = []
        self._route = []
        self.update()

    def reset_view(self) -> None:
        """重置缩放和偏移。"""
        self._scale = 1.0
        self._offset = QPointF(0, 0)
        self.update()

    # ---------- 坐标转换 ----------

    def _lnglat_to_screen(self, lng: float, lat: float) -> QPointF:
        """经纬度转屏幕坐标（含缩放和偏移）。

        采用等距投影：lng→x 线性，lat→y 线性（纬度反向）。
        用 min(scale_x, scale_y) 保证经纬度比例不变形。
        """
        w = self.width()
        h = self.height()
        margin = 20
        avail_w = w - 2 * margin
        avail_h = h - 2 * margin
        scale_x = avail_w / (LNG_MAX - LNG_MIN)
        scale_y = avail_h / (LAT_MAX - LAT_MIN)
        base_scale = min(scale_x, scale_y)

        # 居中
        center_lng = (LNG_MAX + LNG_MIN) / 2
        center_lat = (LAT_MAX + LAT_MIN) / 2
        x0 = w / 2 - center_lng * base_scale
        y0 = h / 2 + center_lat * base_scale  # 纬度反向

        # 应用缩放（以窗口中心为缩放原点）
        bx = x0 + lng * base_scale
        by = y0 - lat * base_scale
        cx, cy = w / 2, h / 2
        sx = cx + (bx - cx) * self._scale + self._offset.x()
        sy = cy + (by - cy) * self._scale + self._offset.y()
        return QPointF(sx, sy)

    # ---------- 绘制 ----------

    def paintEvent(self, event) -> None:
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing, True)
        p.setRenderHint(QPainter.SmoothPixmapTransform, True)

        # 背景：海洋
        p.fillRect(self.rect(), _BG_COLOR)

        # 绘制所有省份多边形（真实省界）
        self._draw_provinces(p)
        # 绘制路线
        self._draw_route(p)
        # 绘制城市标记
        self._draw_cities(p)
        # 绘制图例
        self._draw_legend(p)

    def _draw_provinces(self, p: QPainter) -> None:
        """绘制所有省份的真实边界多边形。

        性能：省界顶点数千个，每次 paintEvent 都全量投影会很卡。
        这里按视图变换 key 缓存投影结果，仅在尺寸/缩放/偏移变化时重算。
        """
        if not self._all_polys:
            return

        # 缓存 key：视图变换决定投影结果
        key = (
            self.width(), self.height(),
            round(self._scale, 4),
            round(self._offset.x(), 1), round(self._offset.y(), 1),
        )
        if key != self._cache_key:
            self._cache_key = key
            self._cached_fill = [
                QPolygonF([self._lnglat_to_screen(lng, lat)
                          for lng, lat in poly_pts])
                for poly_pts in self._all_polys
                if len(poly_pts) >= 3
            ]
            self._cached_outline = []
            for prov in self._provinces:
                for poly_pts in prov["polygons"]:
                    if len(poly_pts) < 2:
                        continue
                    self._cached_outline.append(
                        [self._lnglat_to_screen(lng, lat)
                         for lng, lat in poly_pts]
                    )

        # 先画所有省份填充 + 外轮廓
        p.setBrush(QBrush(_LAND_COLOR))
        p.setPen(QPen(_LAND_OUTLINE, 1.0))
        for qpoly in self._cached_fill:
            p.drawPolygon(qpoly)

        # 再画省界（用稍深的颜色描边每个省份的边界）
        p.setPen(QPen(_PROVINCE_OUTLINE, 0.5))
        for pts in self._cached_outline:
            for i in range(len(pts) - 1):
                p.drawLine(pts[i], pts[i + 1])

    def _draw_route(self, p: QPainter) -> None:
        if len(self._route) < 2:
            return
        # 与 _draw_cities 保持一致：lat/lng 非数值时跳过该点，避免 paintEvent 崩溃
        pts = []
        for c in self._route:
            try:
                lng = float(c.get("lng", 0))
                lat = float(c.get("lat", 0))
            except (TypeError, ValueError):
                continue
            pts.append(self._lnglat_to_screen(lng, lat))
        if len(pts) < 2:
            return
        pen = QPen(_ROUTE_COLOR, 2.5)
        pen.setStyle(Qt.PenStyle.DashLine)
        pen.setDashPattern([8, 6])
        p.setPen(pen)
        for i in range(len(pts) - 1):
            p.drawLine(pts[i], pts[i + 1])

    def _draw_cities(self, p: QPainter) -> None:
        font = QApplication.font()
        font.setPointSize(9)
        p.setFont(font)
        for c in self._cities:
            try:
                lng = float(c.get("lng", 0))
                lat = float(c.get("lat", 0))
            except (TypeError, ValueError):
                continue
            pt = self._lnglat_to_screen(lng, lat)
            source = c.get("source", "self")
            ctype = c.get("type", "visited")
            name = c.get("city_name", c.get("name", ""))

            if source == "partner":
                color = _PARTNER_COLOR
            else:
                color = _VISITED_COLOR

            r = 7
            if ctype == "wish":
                # 空心圆
                p.setBrush(QBrush(QColor(255, 255, 255)))
                p.setPen(QPen(color, 2))
                p.drawEllipse(pt, r, r)
            else:
                # 实心圆
                p.setBrush(QBrush(color))
                p.setPen(QPen(QColor(255, 255, 255), 1.5))
                p.drawEllipse(pt, r, r)

            # 城市名标签（标记右侧，加白色描边提高可读性）
            if name:
                # 白色描边
                p.setPen(QPen(QColor(255, 255, 255, 200), 3))
                for dx, dy in [(-1, 0), (1, 0), (0, -1), (0, 1)]:
                    p.drawText(QPointF(pt.x() + r + 3 + dx, pt.y() + 4 + dy), name)
                # 正文
                p.setPen(QPen(_TEXT_COLOR))
                p.drawText(QPointF(pt.x() + r + 3, pt.y() + 4), name)

    def _draw_legend(self, p: QPainter) -> None:
        font = QApplication.font()
        font.setPointSize(9)
        p.setFont(font)
        x = self.width() - 130
        y = 16
        # 背景
        p.setBrush(QBrush(QColor(255, 255, 255, 220)))
        p.setPen(QPen(QColor(200, 200, 200), 1))
        p.drawRoundedRect(QRectF(x - 8, y - 6, 122, 70), 6, 6)

        # 我（粉色实心）
        p.setBrush(QBrush(_VISITED_COLOR))
        p.setPen(QPen(QColor(255, 255, 255), 1))
        p.drawEllipse(QPointF(x + 5, y + 5), 5, 5)
        p.setPen(QPen(_TEXT_COLOR))
        p.drawText(QPointF(x + 16, y + 9), "我（已去过）")

        # 愿望（粉色空心）
        p.setBrush(QBrush(QColor(255, 255, 255)))
        p.setPen(QPen(_VISITED_COLOR, 2))
        p.drawEllipse(QPointF(x + 5, y + 25), 5, 5)
        p.setPen(QPen(_TEXT_COLOR))
        p.drawText(QPointF(x + 16, y + 29), "愿望清单")

        # TA（蓝色）
        p.setBrush(QBrush(_PARTNER_COLOR))
        p.setPen(QPen(QColor(255, 255, 255), 1))
        p.drawEllipse(QPointF(x + 5, y + 45), 5, 5)
        p.setPen(QPen(_TEXT_COLOR))
        p.drawText(QPointF(x + 16, y + 49), "对方共享")

    # ---------- 鼠标交互 ----------

    def wheelEvent(self, event: QWheelEvent) -> None:
        # 滚轮缩放，以鼠标位置为缩放中心
        delta = event.angleDelta().y() / 120.0  # ±1
        factor = 1.15 if delta > 0 else 1 / 1.15
        new_scale = self._scale * factor
        # 限制缩放范围
        if new_scale < 0.5 or new_scale > 12.0:
            return

        # 以鼠标位置为缩放原点
        mouse_pos = event.position()
        cx, cy = self.width() / 2, self.height() / 2
        # 当前鼠标对应的"世界坐标"（缩放前）
        wx = cx + (mouse_pos.x() - cx - self._offset.x()) / self._scale
        wy = cy + (mouse_pos.y() - cy - self._offset.y()) / self._scale

        self._scale = new_scale
        # 缩放后让鼠标位置仍对应同一世界坐标
        self._offset = QPointF(
            mouse_pos.x() - cx - (wx - cx) * self._scale,
            mouse_pos.y() - cy - (wy - cy) * self._scale,
        )
        self.update()

    def mousePressEvent(self, event: QMouseEvent) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            # 检查是否点击了城市标记
            clicked = self._find_city_at(event.position())
            if clicked:
                name = clicked.get("city_name", clicked.get("name", ""))
                if name:
                    self.cityClicked.emit(name)
                    return
            # 否则开始拖动
            self._dragging = True
            self._last_pos = event.position()

    def mouseMoveEvent(self, event: QMouseEvent) -> None:
        if self._dragging:
            delta = event.position() - self._last_pos
            self._offset += delta
            self._last_pos = event.position()
            self.update()

    def mouseReleaseEvent(self, event: QMouseEvent) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            self._dragging = False

    def mouseDoubleClickEvent(self, event: QMouseEvent) -> None:
        # 双击重置视图
        self.reset_view()

    def _find_city_at(self, pos: QPointF) -> Optional[dict]:
        """找到距离 pos 最近的、半径 12 像素内的城市。"""
        best = None
        best_dist = 12.0  # 像素半径
        for c in self._cities:
            try:
                lng = float(c.get("lng", 0))
                lat = float(c.get("lat", 0))
            except (TypeError, ValueError):
                continue
            pt = self._lnglat_to_screen(lng, lat)
            d = ((pt.x() - pos.x()) ** 2 + (pt.y() - pos.y()) ** 2) ** 0.5
            if d < best_dist:
                best_dist = d
                best = c
        return best
