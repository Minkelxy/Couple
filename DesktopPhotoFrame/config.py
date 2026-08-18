"""配置管理：从 config.json 读写，缺失项用默认值补齐。"""
from __future__ import annotations

from copy import deepcopy
from pathlib import Path

import app_paths
from common_utils import AtomicJsonStore, atomic_copy_file, log_exception, log_warning
from version import resource_path

CONFIG_PATH = app_paths.CONFIG_DIR / "photo_frame.json"
# 配置统一通过原子 JSON 存储读写。
_store = AtomicJsonStore(CONFIG_PATH, default={})
DEFAULT_ALBUM_NAME = "默认相册"
_IMG_EXTS = {
    ".jpg", ".jpeg", ".png", ".bmp", ".webp",
    ".gif", ".tif", ".tiff", ".heic", ".heif",
}


def _is_images_dir_empty(images_dir: Path) -> bool:
    """images 目录里是否没有任何图片（忽略子目录和非图片文件）。"""
    if not images_dir.exists():
        return True
    for p in images_dir.iterdir():
        if p.is_file() and p.suffix.lower() in _IMG_EXTS:
            return False
    return True


def ensure_default_album() -> Path:
    """首次或空目录时，把 assets/default_album 示例图复制到用户 IMAGES_DIR。

    返回值：默认相册目录（app_paths.IMAGES_DIR，用户可写）。

    策略：
    1. 资源默认相册源：开发走项目根 assets/default_album，exe 打包走 sys._MEIPASS/assets/default_album
    2. 目标目录：app_paths.IMAGES_DIR（%APPDATA%/CoupleSuite/images，用户可写）
    3. 仅当「目标目录不存在任何图片」时才拷贝，避免覆盖用户自己丢进去的照片
    """
    images_dir = app_paths.IMAGES_DIR
    images_dir.mkdir(parents=True, exist_ok=True)
    src_dir = resource_path("assets/default_album")

    # 目标目录里已经有用户图片，尊重现状不复制
    if not _is_images_dir_empty(images_dir):
        return images_dir
    # 源目录不存在（开发机没放图？极端情况），直接返回
    if not src_dir.exists() or not src_dir.is_dir():
        return images_dir

    copied = 0
    for src in src_dir.iterdir():
        if not src.is_file():
            continue
        if src.suffix.lower() not in _IMG_EXTS:
            continue
        dst = images_dir / src.name
        # 同名文件已存在（.mkdir 后被其他进程写），跳过
        if dst.exists():
            continue
        try:
            atomic_copy_file(src, dst)
            copied += 1
        except OSError as e:
            log_exception("默认相册示例图复制失败 %s -> %s: %s", src, dst, e)
    if copied:
        log_warning("首次启动：复制默认示例图 %d 张到 %s", copied, images_dir)
    return images_dir


DEFAULTS = {
    # 图片目录：默认 %APPDATA%/CoupleSuite/images，由 ensure_default_album 填充示例图
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
    # 首次启动默认内置一个「默认相册」指向 IMAGES_DIR
    "albums": [{"name": DEFAULT_ALBUM_NAME, "path": str(app_paths.IMAGES_DIR)}],
    # 对方共享相册：[{name, path}]，接收对方照片的目录
    "partner_albums": [],
    # 收藏列表（文件绝对路径字符串）
    "favorites": [],
    # 相框窗口位置（拖动后持久化，None 表示首次启动用默认右下角）
    "window_x": None,
    "window_y": None,
}


def _ensure_default_album_entry(albums: list[dict]) -> list[dict]:
    """如果用户从未配置过相册（老用户 albums=[]），补一条默认相册项。

    - 不覆盖用户自己已有的相册记录；
    - 如果默认相册 IMAGES_DIR 已在用户 albums 里（不管名字），也不重复加。
    """
    if not isinstance(albums, list):
        albums = []
    albums = [
        album for album in albums
        if isinstance(album, dict)
        and isinstance(album.get("path"), str)
        and album["path"]
    ]
    default_path = str(app_paths.IMAGES_DIR)
    if any(isinstance(a, dict) and str(a.get("path", "")) == default_path for a in albums):
        return albums
    albums = list(albums)
    albums.append({"name": DEFAULT_ALBUM_NAME, "path": default_path})
    return albums


def load() -> dict:
    data = deepcopy(DEFAULTS)
    app_paths.CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    stored = _store.load()
    if isinstance(stored, dict):
        data.update(stored)
    # 类型校正：防止 JSON 里写出错误类型
    for key, minimum in (
        ("interval_sec", 3),
        ("window_width", 160),
        ("window_height", 200),
    ):
        try:
            value = int(data.get(key, DEFAULTS[key]))
        except (TypeError, ValueError):
            value = DEFAULTS[key]
        data[key] = max(minimum, value)
    anniv = data.get("anniversaries", [])
    data["anniversaries"] = anniv if isinstance(anniv, list) else []
    data["albums"] = _ensure_default_album_entry(data.get("albums", []))
    partner_albums = data.get("partner_albums", [])
    data["partner_albums"] = [
        album for album in partner_albums
        if isinstance(album, dict)
        and isinstance(album.get("path"), str)
        and album["path"]
    ] if isinstance(partner_albums, list) else []
    # favorites 类型校正：必须是字符串列表
    favs = data.get("favorites", [])
    if not isinstance(favs, list):
        favs = []
    data["favorites"] = [str(p) for p in favs if p]
    # window_x/y 类型校正：None 或 int
    for k in ("window_x", "window_y"):
        v = data.get(k)
        if v is not None:
            try:
                data[k] = int(v)
            except (TypeError, ValueError):
                data[k] = None
    # image_dir 的兜底：如果用户之前把它设到了不存在/空的路径，就切回默认相册目录
    image_dir_str = str(data.get("image_dir", "") or str(app_paths.IMAGES_DIR))
    if not image_dir_str or image_dir_str.lower() in {"null", "none"}:
        image_dir_str = str(app_paths.IMAGES_DIR)
    data["image_dir"] = image_dir_str
    return data


def save(data: dict) -> None:
    _store.save(data)


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


# ---------- 收藏 ----------

def toggle_favorite(path: str) -> bool:
    """切换收藏状态，返回切换后是否为收藏。"""
    data = load()
    favs = set(data.get("favorites", []))
    is_fav = path in favs
    if is_fav:
        favs.discard(path)
    else:
        favs.add(path)
    data["favorites"] = sorted(favs)
    save(data)
    return not is_fav


def is_favorite(path: str) -> bool:
    """是否已收藏。"""
    return path in set(load().get("favorites", []))


def list_favorites() -> list[str]:
    """返回收藏列表（绝对路径字符串）。"""
    return load().get("favorites", [])


# ---------- 相框窗口位置持久化 ----------

def save_window_pos(x: int, y: int) -> None:
    """保存相框窗口位置（拖动结束调用）。"""
    update(window_x=int(x), window_y=int(y))
