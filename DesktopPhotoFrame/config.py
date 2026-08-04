"""配置管理：从 config.json 读写，缺失项用默认值补齐。"""
from __future__ import annotations

import json
from pathlib import Path

import app_paths
from common_utils import log_warning

CONFIG_PATH = app_paths.CONFIG_DIR / "photo_frame.json"

DEFAULTS = {
    # 图片目录：默认 ./images，可由托盘菜单切换
    "image_dir": str(app_paths.IMAGES_DIR),
    # 轮播间隔（秒）
    "interval_sec": 15,
    # 是否加拍立得边框
    "polaroid_frame": True,
    # 是否显示日期水印
    "show_watermark": True,
    # 默认窗口尺寸（小模式）
    "window_width": 320,
    "window_height": 400,
    # 放大模式倍数
    "zoom_factor": 2.0,
    # 圆角半径（像素）
    "corner_radius": 18,
    # 纪念日列表（MM-DD），当天自动切换主题色
    "anniversaries": ["02-14", "12-25"],
    # 纪念日主题色（#RRGGBB）
    "theme_color": "#e65a7a",
    # Ken Burns 缓慢平移动画
    "ken_burns": True,
    # 模糊背景填充（contain 模式下，竖图横屏无留白，Instagram 风格）
    # 与 Ken Burns 互斥：Ken Burns 开启时此项不生效
    "blur_background": False,
    # 滚轮缩放
    "wheel_zoom_enabled": True,
    # 多相册：[{name, path}]，image_dir 为当前选中相册的 path
    "albums": [],
    # 对方共享相册：[{name, path}]，接收对方照片的目录
    "partner_albums": [],
}


def load() -> dict:
    data = dict(DEFAULTS)
    app_paths.CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    if CONFIG_PATH.exists():
        try:
            data.update(json.loads(CONFIG_PATH.read_text(encoding="utf-8")))
        except (json.JSONDecodeError, OSError) as e:
            log_warning("相框配置加载失败，使用默认值: %s", e)
    # 类型校正：防止 JSON 里写出错误类型
    data["interval_sec"] = max(3, int(data.get("interval_sec", 15)))
    data["window_width"] = max(160, int(data.get("window_width", 320)))
    data["window_height"] = max(200, int(data.get("window_height", 400)))
    anniv = data.get("anniversaries", [])
    data["anniversaries"] = anniv if isinstance(anniv, list) else []
    albums = data.get("albums", [])
    data["albums"] = albums if isinstance(albums, list) else []
    partner_albums = data.get("partner_albums", [])
    data["partner_albums"] = partner_albums if isinstance(partner_albums, list) else []
    return data


def save(data: dict) -> None:
    CONFIG_PATH.write_text(
        json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8"
    )


def update(**kwargs) -> dict:
    data = load()
    data.update(kwargs)
    save(data)
    return data


def add_album(name: str, path: str) -> dict:
    """添加相册到列表，返回更新后的配置。"""
    data = load()
    albums = data.get("albums", [])
    # 避免重复路径
    if not any(a.get("path") == path for a in albums):
        albums.append({"name": name, "path": path})
        data["albums"] = albums
        save(data)
    return data


def remove_album(path: str) -> dict:
    """移除相册。"""
    data = load()
    data["albums"] = [a for a in data.get("albums", []) if a.get("path") != path]
    save(data)
    return data


def list_albums() -> list[dict]:
    """返回相册列表。"""
    return load().get("albums", [])


def add_partner_album_path(path: str) -> dict:
    """添加对方共享相册目录，返回更新后的配置。"""
    data = load()
    partner_albums = data.get("partner_albums", [])
    # 避免重复路径
    if not any(a.get("path") == path for a in partner_albums):
        partner_albums.append({"name": "对方共享", "path": path})
        data["partner_albums"] = partner_albums
        save(data)
    return data


def get_partner_albums() -> list[dict]:
    """返回对方共享相册列表。"""
    return load().get("partner_albums", [])
