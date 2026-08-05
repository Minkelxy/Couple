"""数据备份与恢复：打包 AppData 数据为 zip，支持从 zip 恢复。"""
from __future__ import annotations
import os
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

def _safe_extract_all(zf: zipfile.ZipFile, dest: Path) -> None:
    """安全解压：逐条校验路径，防止 ZipSlip 路径穿越（../../etc/passwd）。"""
    dest_resolved = dest.resolve()
    for member in zf.infolist():
        target = (dest / member.filename).resolve()
        if not (str(target).startswith(str(dest_resolved) + os.sep)
                or target == dest_resolved):
            raise ValueError(f"zip 条目含非法路径，拒绝解压: {member.filename}")
        # 3.12+ 的 extractall filter 更安全，但我们自己逐条校验兼容性更好
        zf.extract(member, dest)


def restore_backup(zip_path: Path) -> None:
    """从 zip 恢复数据，覆盖当前 AppData 数据（与"恢复将覆盖所有数据"提示一致）。

    - 先安全解压到临时目录（防 ZipSlip）
    - 目录整体覆盖而非合并（原 _overwrite_dir 合并导致旧信件/配置残留）
    调用方应在调用前弹确认框。
    """
    with zipfile.ZipFile(zip_path, "r") as zf:
        # 解压到临时目录
        tmp = app_paths.CACHE_DIR / "_restore_tmp"
        if tmp.exists():
            shutil.rmtree(tmp)
        tmp.mkdir(parents=True, exist_ok=True)
        _safe_extract_all(zf, tmp)

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


def _overwrite_dir(src: Path, dst: Path) -> None:
    """用 src 覆盖 dst：整体替换（删除 dst 再 copytree）。

    原实现只把 src 的条目拷过去，不删 dst 中 src 没有的文件——
    与用户确认框提示"恢复将覆盖当前所有数据"不一致，会遗留备份后新增的信件/配置。
    """
    if dst.exists():
        shutil.rmtree(dst)
    dst.parent.mkdir(parents=True, exist_ok=True)
    shutil.copytree(src, dst)
