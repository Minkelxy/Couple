"""地图渲染：用 Pillow 绘制中国地图底图 + 城市标记，返回 QPixmap。

经纬度到像素的映射采用简单线性映射：
  lng 73-135 → x 50-(size-50)
  lat 18-54  → y (size-50)-50 （纬度反向，高纬在上）
"""
from __future__ import annotations

from io import BytesIO
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

from PySide6.QtCore import QCoreApplication
from PySide6.QtGui import QImage, QPixmap

# 持有临时 QApplication 引用，避免被回收（仅在无应用实例时创建）
_qapp_holder: list = []

_BG_COLOR = (240, 248, 255)        # #f0f8ff 浅蓝背景
_LAND_COLOR = (255, 248, 220)      # #fff8dc 国土浅黄
_LAND_OUTLINE = (218, 200, 160)    # 国土描边
_VISITED_COLOR = (230, 90, 122)    # #e65a7a 粉色（自己 / 去过）
_WISH_COLOR = (74, 144, 226)       # #4a90e2 蓝色（愿望）
_PARTNER_COLOR = (90, 154, 214)    # #5a9ad6 蓝色（对方共享）
_ROUTE_COLOR = (230, 90, 122)      # 路线粉色
_TEXT_COLOR = (70, 70, 70)         # 城市名标签

# 经纬度范围（中国大致国土）
_LNG_MIN, _LNG_MAX = 73.0, 135.0
_LAT_MIN, _LAT_MAX = 18.0, 54.0

_MARGIN = 50


def _load_font(size: int) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    """尝试加载中文字体，失败回退到默认字体。"""
    for cand in (r"C:\Windows\Fonts\msyh.ttc", r"C:\Windows\Fonts\simhei.ttf"):
        if Path(cand).exists():
            try:
                return ImageFont.truetype(cand, size)
            except OSError:
                continue
    return ImageFont.load_default()


def _lnglat_to_pixel(lng: float, lat: float, size: tuple) -> tuple[int, int]:
    """经纬度转像素坐标。lng→x，lat→y（纬度反向）。"""
    w, h = size
    x = _MARGIN + (lng - _LNG_MIN) / (_LNG_MAX - _LNG_MIN) * (w - 2 * _MARGIN)
    y = (h - _MARGIN) - (lat - _LAT_MIN) / (_LAT_MAX - _LAT_MIN) * (h - 2 * _MARGIN)
    return (int(x), int(y))


def _to_pixmap(img: Image.Image) -> QPixmap:
    """Pillow Image 转 QPixmap（通过 QImage + fromData）。

    QPixmap 的创建依赖 QGuiApplication；若当前无应用实例（如独立脚本调用），
    则自动创建一个，避免在 Windows 上栈溢出崩溃。
    """
    if QCoreApplication.instance() is None:
        from PySide6.QtWidgets import QApplication
        if not _qapp_holder:
            _qapp_holder.append(QApplication([]))
    buf = BytesIO()
    img.save(buf, format="PNG")
    qimg = QImage.fromData(buf.getvalue(), "PNG")
    return QPixmap.fromImage(qimg)


def render_map(cities: list[dict],
               highlight_route: list[dict] | None = None,
               size: tuple = (900, 700)) -> QPixmap:
    """渲染地图，返回 QPixmap。

    - 底图：浅色背景 + 浅黄色国土多边形（简化轮廓）
    - 城市标记：颜色按 source 区分（self=粉色 / partner=蓝色），
      type=visited 实心圆 / wish 空心圆，半径 8
    - 城市名标签：标记右侧小字
    - 右上角图例：粉色=我、蓝色=TA
    - highlight_route：按顺序用粉色线连接，当前激活城市半径加大到 12
    """
    w, h = size
    img = Image.new("RGB", (w, h), _BG_COLOR)
    draw = ImageDraw.Draw(img)

    # 国土轮廓（简化多边形，按真实大致边界取点）
    land_pts = [
        _lnglat_to_pixel(73.5, 39.0, size),
        _lnglat_to_pixel(82.0, 45.0, size),
        _lnglat_to_pixel(92.0, 49.0, size),
        _lnglat_to_pixel(105.0, 52.0, size),
        _lnglat_to_pixel(120.0, 53.0, size),
        _lnglat_to_pixel(125.0, 50.0, size),
        _lnglat_to_pixel(134.5, 48.0, size),
        _lnglat_to_pixel(131.0, 43.0, size),
        _lnglat_to_pixel(124.0, 40.0, size),
        _lnglat_to_pixel(122.0, 37.0, size),
        _lnglat_to_pixel(121.5, 32.0, size),
        _lnglat_to_pixel(121.0, 28.0, size),
        _lnglat_to_pixel(120.0, 24.0, size),
        _lnglat_to_pixel(119.0, 22.0, size),
        _lnglat_to_pixel(110.0, 20.5, size),
        _lnglat_to_pixel(108.0, 18.5, size),
        _lnglat_to_pixel(100.0, 22.0, size),
        _lnglat_to_pixel(97.5, 24.0, size),
        _lnglat_to_pixel(92.0, 28.0, size),
        _lnglat_to_pixel(88.0, 27.5, size),
        _lnglat_to_pixel(79.0, 32.0, size),
        _lnglat_to_pixel(75.0, 37.0, size),
        _lnglat_to_pixel(74.0, 39.0, size),
    ]
    draw.polygon(land_pts, fill=_LAND_COLOR, outline=_LAND_OUTLINE)

    font_label = _load_font(16)

    active_name: str | None = None
    if highlight_route:
        active_name = highlight_route[-1].get("city_name")

    # 路线连线（按顺序）
    if highlight_route and len(highlight_route) >= 2:
        line_pts = [
            _lnglat_to_pixel(float(c["lng"]), float(c["lat"]), size)
            for c in highlight_route
        ]
        draw.line(line_pts, fill=_ROUTE_COLOR, width=3)

    # 城市标记：颜色按 source 区分（self=粉色 / partner=蓝色），实心/空心按 type
    for c in cities:
        try:
            cx, cy = _lnglat_to_pixel(float(c["lng"]), float(c["lat"]), size)
        except (KeyError, TypeError, ValueError):
            continue
        ctype = c.get("type", "visited")
        source = c.get("source", "self")
        color = _PARTNER_COLOR if source == "partner" else _VISITED_COLOR
        is_active = active_name is not None and c.get("city_name") == active_name
        r = 12 if is_active else 8
        if ctype == "wish":
            # 空心圆
            draw.ellipse([cx - r, cy - r, cx + r, cy + r],
                         outline=color, width=2)
        else:
            # 实心圆
            draw.ellipse([cx - r, cy - r, cx + r, cy + r],
                         fill=color)
        # 城市名标签（标记右侧）
        name = c.get("city_name", "")
        if name:
            draw.text((cx + r + 4, cy - 8), name, fill=_TEXT_COLOR, font=font_label)

    # 图例（右上角：粉色=我、蓝色=TA）
    font_legend = _load_font(14)
    leg_y = 18
    draw.ellipse([w - 188, leg_y, w - 176, leg_y + 12], fill=_VISITED_COLOR)
    draw.text((w - 172, leg_y - 2), "粉色=我", fill=_TEXT_COLOR, font=font_legend)
    draw.ellipse([w - 92, leg_y, w - 80, leg_y + 12], fill=_PARTNER_COLOR)
    draw.text((w - 76, leg_y - 2), "蓝色=TA", fill=_TEXT_COLOR, font=font_legend)

    return _to_pixmap(img)
