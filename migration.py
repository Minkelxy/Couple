"""旧数据迁移：把包内 config/data/images 迁移到 %APPDATA%\\CoupleSuite。

幂等：检测 APP_ROOT\\.migrated 标记，存在则跳过。每步独立 try/except。
"""
from __future__ import annotations

import shutil
from datetime import datetime
from pathlib import Path

import app_paths
from common_utils import log_exception

# 旧路径（相对项目根目录，即本文件所在目录）
_PROJECT_ROOT = Path(__file__).parent
_OLD_PF_CONFIG = _PROJECT_ROOT / "DesktopPhotoFrame" / "config.json"
_OLD_MB_CONFIG = _PROJECT_ROOT / "DesktopMailbox" / "config.json"
_OLD_MB_DATA = _PROJECT_ROOT / "DesktopMailbox" / "data"
_OLD_PF_IMAGES = _PROJECT_ROOT / "DesktopPhotoFrame" / "images"

# 默认相册（内置素材）：开发环境在 assets/default_album，打包环境在 _MEIPASS/assets/default_album
def _resolve_default_album() -> Path:
    import sys
    # 1. 开发环境：项目根/assets/default_album
    p1 = _PROJECT_ROOT / "assets" / "default_album"
    if p1.is_dir():
        return p1
    # 2. 打包环境：_MEIPASS/assets/default_album
    meipass = getattr(sys, "_MEIPASS", None)
    if meipass:
        p2 = Path(meipass) / "assets" / "default_album"
        if p2.is_dir():
            return p2
    # 3. 当前工作目录
    p3 = Path("assets") / "default_album"
    if p3.is_dir():
        return p3
    return p1  # 返回默认路径（即使不存在）

# 新路径
_NEW_PF_CONFIG = app_paths.CONFIG_DIR / "photo_frame.json"
_NEW_MB_CONFIG = app_paths.CONFIG_DIR / "mailbox.json"
_NEW_DATA_DIR = app_paths.DATA_DIR
_NEW_IMAGES_DIR = app_paths.IMAGES_DIR

_MIGRATED_MARKER = app_paths.APP_ROOT / ".migrated"

_IMAGE_EXTS = {".png", ".jpg", ".jpeg", ".bmp", ".gif", ".webp", ".tiff"}


def _migrate_file(src: Path, dst: Path) -> None:
    if not src.exists():
        return
    if dst.exists():
        return
    dst.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(src, dst)


def _migrate_tree(src: Path, dst: Path) -> None:
    if not src.exists() or not src.is_dir():
        return
    dst.mkdir(parents=True, exist_ok=True)
    for item in src.rglob("*"):
        if item.is_dir():
            (dst / item.relative_to(src)).mkdir(parents=True, exist_ok=True)
        elif item.is_file():
            rel = item.relative_to(src)
            target = dst / rel
            if target.exists():
                continue
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(item, target)


def _migrate_images(src: Path, dst: Path) -> None:
    if not src.exists() or not src.is_dir():
        return
    dst.mkdir(parents=True, exist_ok=True)
    for item in src.iterdir():
        if not item.is_file():
            continue
        if item.suffix.lower() not in _IMAGE_EXTS:
            continue
        target = dst / item.name
        if target.exists():
            continue
        shutil.copy2(item, target)


def run_migration() -> bool:
    """执行迁移。返回 True 表示本次执行了迁移，False 表示已迁移跳过。

    幂等：已存在 .migrated 标记则直接返回 False。
    任一步骤失败 → 记录日志 + 不写标记 → 下次启动重新尝试。
    """
    if _MIGRATED_MARKER.exists():
        return False

    app_paths.ensure_dirs()

    all_ok = True

    # 相框配置
    try:
        _migrate_file(_OLD_PF_CONFIG, _NEW_PF_CONFIG)
    except Exception:
        log_exception("迁移相框配置失败")
        all_ok = False

    # 信箱配置
    try:
        _migrate_file(_OLD_MB_CONFIG, _NEW_MB_CONFIG)
    except Exception:
        log_exception("迁移信箱配置失败")
        all_ok = False

    # 信箱数据目录（递归）
    try:
        _migrate_tree(_OLD_MB_DATA, _NEW_DATA_DIR)
    except Exception:
        log_exception("迁移信箱数据目录失败")
        all_ok = False

    # 相框图片目录（仅图片文件）
    try:
        _migrate_images(_OLD_PF_IMAGES, _NEW_IMAGES_DIR)
    except Exception:
        log_exception("迁移相框图片目录失败")
        all_ok = False

    # 默认相册：若 images 目录为空（首次运行），复制内置默认相册
    try:
        _seed_default_album()
    except Exception:
        log_exception("复制默认相册失败")
        all_ok = False

    # 仅当所有步骤都成功时才写迁移标记，任一步骤失败下次启动重新尝试
    if all_ok:
        try:
            _MIGRATED_MARKER.write_text(
                datetime.now().isoformat(timespec="seconds"), encoding="utf-8"
            )
        except Exception:
            log_exception("写迁移标记失败")

    return True


def _seed_default_album() -> None:
    """首次运行时把内置默认相册复制到 APP_DATA/images。

    条件：images 目录无任何图片文件时才复制（避免覆盖用户图片）。
    """
    src_dir = _resolve_default_album()
    if not src_dir.is_dir():
        return

    # 检查目标目录是否已有图片
    _NEW_IMAGES_DIR.mkdir(parents=True, exist_ok=True)
    existing = [f for f in _NEW_IMAGES_DIR.iterdir()
                if f.is_file() and f.suffix.lower() in _IMAGE_EXTS]
    if existing:
        return  # 已有图片，不覆盖

    # 复制默认相册
    for item in src_dir.iterdir():
        if not item.is_file():
            continue
        if item.suffix.lower() not in _IMAGE_EXTS:
            continue
        target = _NEW_IMAGES_DIR / item.name
        if target.exists():
            continue
        shutil.copy2(item, target)
