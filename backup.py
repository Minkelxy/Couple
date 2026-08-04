"""数据备份与恢复：打包 AppData 数据为 zip，支持从 zip 恢复。"""
from __future__ import annotations
import zipfile
import shutil
from datetime import datetime
from pathlib import Path

import app_paths

def export_backup(dest_zip: Path) -> Path:
    """把 config/ + data/ + images/ 打包到 zip。
    返回实际保存路径。文件名自动加日期后缀。
    """
    # 如果 dest_zip 是目录，自动生成文件名
    if dest_zip.is_dir() or str(dest_zip).endswith("\\") or str(dest_zip).endswith("/"):
        name = f"CoupleSuite_backup_{datetime.now().strftime('%Y%m%d')}.zip"
        dest_zip = dest_zip / name
    # 确保以 .zip 结尾
    if not dest_zip.suffix == ".zip":
        dest_zip = dest_zip.with_suffix(".zip")
    
    with zipfile.ZipFile(dest_zip, "w", zipfile.ZIP_DEFLATED) as zf:
        # config 目录
        _add_dir_to_zip(zf, app_paths.CONFIG_DIR, "config")
        # data 目录（信箱数据）
        _add_dir_to_zip(zf, app_paths.DATA_DIR, "data")
        # images 目录（相框图片，可能很大，但用户选择备份时包含）
        _add_dir_to_zip(zf, app_paths.IMAGES_DIR, "images")
    return dest_zip

def _add_dir_to_zip(zf: zipfile.ZipFile, src_dir: Path, arcname_prefix: str):
    """递归把目录加到 zip。"""
    if not src_dir.exists():
        return
    for file in src_dir.rglob("*"):
        if file.is_file():
            arcname = f"{arcname_prefix}/{file.relative_to(src_dir).as_posix()}"
            zf.write(file, arcname)

def restore_backup(zip_path: Path) -> None:
    """从 zip 恢复数据，覆盖当前 AppData 数据。
    调用方应在调用前弹确认框。
    """
    with zipfile.ZipFile(zip_path, "r") as zf:
        # 解压到临时目录
        tmp = app_paths.CACHE_DIR / "_restore_tmp"
        if tmp.exists():
            shutil.rmtree(tmp)
        tmp.mkdir(parents=True, exist_ok=True)
        zf.extractall(tmp)
        
        # 覆盖 config
        src_config = tmp / "config"
        if src_config.exists():
            _overwrite_dir(src_config, app_paths.CONFIG_DIR)
        # 覆盖 data
        src_data = tmp / "data"
        if src_data.exists():
            _overwrite_dir(src_data, app_paths.DATA_DIR)
        # 覆盖 images
        src_images = tmp / "images"
        if src_images.exists():
            _overwrite_dir(src_images, app_paths.IMAGES_DIR)
        
        # 清理临时目录
        shutil.rmtree(tmp)

def _overwrite_dir(src: Path, dst: Path):
    """用 src 覆盖 dst：删除 dst 旧内容，把 src 复制过去。"""
    dst.mkdir(parents=True, exist_ok=True)
    for item in src.iterdir():
        target = dst / item.name
        if item.is_dir():
            if target.exists():
                shutil.rmtree(target)
            shutil.copytree(item, target)
        else:
            shutil.copy2(item, target)
