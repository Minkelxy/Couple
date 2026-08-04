"""旅行地图数据存储：JSON 格式城市列表。

存储结构：
  travel/cities.json   # 城市记录列表（明文 JSON，便于检索排序）
  travel/photos/       # 自己的城市照片（路径存于 image_path 字段）
  travel/partner_photos/  # 对方共享的城市照片

数据结构：list[dict]，每个 dict:
  {city_name, lat, lng, date, story, image_path, type, source}
  type 枚举: "visited"(去过) / "wish"(愿望)
  source 枚举: "self"(自己添加，粉色标记) / "partner"(对方共享，蓝色标记)
"""
from __future__ import annotations

import json

import app_paths

_DATA_PATH = app_paths.TRAVEL_DIR / "cities.json"

_VALID_TYPES = {"visited", "wish"}
_VALID_SOURCES = {"self", "partner"}


def _load() -> list[dict]:
    """从磁盘加载城市列表，文件缺失或损坏时返回空列表。"""
    if not _DATA_PATH.exists():
        return []
    try:
        items = json.loads(_DATA_PATH.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return []
    if not isinstance(items, list):
        return []
    # 向后兼容：旧记录无 source 字段或值非法，统一补默认值 "self"
    for it in items:
        if not isinstance(it, dict):
            continue
        if it.get("source") not in _VALID_SOURCES:
            it["source"] = "self"
    return items


def _save(items: list[dict]) -> None:
    """将城市列表写入磁盘。"""
    app_paths.TRAVEL_DIR.mkdir(parents=True, exist_ok=True)
    _DATA_PATH.write_text(
        json.dumps(items, ensure_ascii=False, indent=2), encoding="utf-8"
    )


def add(city_name: str, lat: float, lng: float, type: str,
        date: str = "", story: str = "", image_path: str = "") -> dict:
    """新增一个城市记录，返回新增项。

    若同名城市已存在，则覆盖旧记录（以最新为准）。
    """
    if type not in _VALID_TYPES:
        raise ValueError(f"无效的 type: {type}（应为 visited 或 wish）")
    items = _load()
    # 移除同名旧记录，避免重复（仅清理自己的记录，保留 partner 记录）
    items = [it for it in items
             if it.get("city_name") != city_name or it.get("source") == "partner"]
    record = {
        "city_name": city_name,
        "lat": float(lat),
        "lng": float(lng),
        "type": type,
        "date": date,
        "story": story,
        "image_path": image_path,
        "source": "self",
    }
    items.append(record)
    _save(items)
    return record


def add_partner_city(city: str, lat: float, lng: float,
                     note: str = "", photo_filename: str = "") -> dict:
    """新增对方共享的城市记录（source="partner"），追加不覆盖。

    与 add() 区别：不清理同名旧记录，type 默认 visited，date 留空。
    """
    items = _load()
    record = {
        "city_name": city,
        "lat": float(lat),
        "lng": float(lng),
        "type": "visited",
        "date": "",
        "story": note,
        "image_path": photo_filename,
        "source": "partner",
    }
    items.append(record)
    _save(items)
    return record


def update(city_name: str, **kwargs) -> None:
    """按 city_name 更新字段。"""
    if "type" in kwargs and kwargs["type"] not in _VALID_TYPES:
        raise ValueError(f"无效的 type: {kwargs['type']}")
    if "source" in kwargs and kwargs["source"] not in _VALID_SOURCES:
        raise ValueError(f"无效的 source: {kwargs['source']}")
    items = _load()
    for it in items:
        if it.get("city_name") == city_name:
            it.update(kwargs)
            break
    _save(items)


def delete(city_name: str) -> None:
    """按 city_name 删除记录。"""
    items = _load()
    items = [it for it in items if it.get("city_name") != city_name]
    _save(items)


def list_all() -> list[dict]:
    """返回全部城市记录。"""
    return _load()


def list_cities(source: str | None = None) -> list[dict]:
    """返回城市记录，可按 source 过滤（None 返回全部）。"""
    items = _load()
    if source is None:
        return items
    return [it for it in items if it.get("source", "self") == source]


def list_by_type(type: str) -> list[dict]:
    """返回指定类型的城市记录。"""
    return [it for it in _load() if it.get("type") == type]


def get(city_name: str) -> dict | None:
    """按 city_name 查询单条记录，无则返回 None。"""
    for it in _load():
        if it.get("city_name") == city_name:
            return it
    return None


def count_visited() -> int:
    """返回已去过（visited）城市数量。"""
    return len([it for it in _load() if it.get("type") == "visited"])


def sorted_by_date() -> list[dict]:
    """按 date 升序返回，用于路线动画。无 date 的排到最后。"""
    def _key(it: dict) -> tuple[int, str]:
        d = it.get("date", "")
        return (0, d) if d else (1, "")
    return sorted(_load(), key=_key)
