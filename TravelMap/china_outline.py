"""中国地图轮廓数据加载器（真实边界，离线使用）。

数据来源：DataV.GeoAtlas 阿里云公开数据
https://geo.datav.aliyun.com/areas_v3/bound/100000_full.json

数据文件：assets/china_geo.json（582KB，35 个省级行政区）
首次加载后缓存到模块级变量，避免重复 IO。

坐标系：WGS84 经纬度（lng, lat），GeoJSON 标准顺序为 [lng, lat]
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Optional

# 经纬度边界（中国范围，含南海诸岛示意框）
LNG_MIN, LNG_MAX = 72.0, 140.0
LAT_MIN, LAT_MAX = 15.0, 54.0

# 数据文件路径
_GEO_JSON_PATH = Path(__file__).resolve().parent.parent / "assets" / "china_geo.json"

# 缓存
_cache: Optional[list] = None


def _resolve_geo_path() -> Path:
    """查找 china_geo.json，兼容开发环境和打包环境。

    开发环境：项目根/assets/china_geo.json
    打包环境：_MEIPASS/assets/china_geo.json（PyInstaller 解压目录）
    """
    # 1. 相对模块文件
    p1 = _GEO_JSON_PATH
    if p1.exists():
        return p1
    # 2. PyInstaller _MEIPASS
    import sys
    meipass = getattr(sys, "_MEIPASS", None)
    if meipass:
        p2 = Path(meipass) / "assets" / "china_geo.json"
        if p2.exists():
            return p2
    # 3. 当前工作目录
    p3 = Path("assets") / "china_geo.json"
    if p3.exists():
        return p3
    # 返回默认路径（即使不存在，让调用方报错）
    return p1


def load_provinces() -> list[dict]:
    """加载中国省级行政区边界数据。

    返回格式：[
        {
            "name": "北京市",
            "polygons": [         # MultiPolygon 展平后的多边形列表
                [(lng, lat), ...],  # 每个多边形是一个 (lng, lat) 点列表（外环）
                ...
            ]
        },
        ...
    ]

    GeoJSON 结构说明：
    - Polygon: coordinates = [外环, 内环1, 内环2, ...]
    - MultiPolygon: coordinates = [[外环, 内环...], [外环...], ...]
    本函数只取每个多边形的外环（第一个环），忽略内环洞（视觉上足够）
    """
    global _cache
    if _cache is not None:
        return _cache

    path = _resolve_geo_path()
    if not path.exists():
        _cache = []
        return _cache

    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)

    result: list[dict] = []
    for feature in data.get("features", []):
        name = feature.get("properties", {}).get("name", "")
        if not name:
            continue
        geom = feature.get("geometry", {})
        gtype = geom.get("type", "")
        coords = geom.get("coordinates", [])

        polygons: list[list[tuple[float, float]]] = []
        if gtype == "Polygon":
            # coords = [外环, 内环1, ...]
            if coords:
                outer = coords[0]
                polygons.append([(float(p[0]), float(p[1])) for p in outer])
        elif gtype == "MultiPolygon":
            # coords = [[外环, 内环...], [外环...], ...]
            for poly in coords:
                if poly:
                    outer = poly[0]
                    polygons.append([(float(p[0]), float(p[1])) for p in outer])

        if polygons:
            result.append({"name": name, "polygons": polygons})

    _cache = result
    return result


def all_polygons() -> list[list[tuple[float, float]]]:
    """返回所有省份的所有外环多边形（用于批量绘制）。"""
    polys: list[list[tuple[float, float]]] = []
    for prov in load_provinces():
        polys.extend(prov["polygons"])
    return polys
