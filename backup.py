"""数据备份与恢复：打包 AppData 数据为 zip，支持从 zip 恢复。"""
from __future__ import annotations
import os
import zipfile
import shutil
import tempfile
from datetime import datetime
from pathlib import Path

import app_paths


_MAX_BACKUP_ENTRIES = 10_000
_MAX_BACKUP_MEMBER_BYTES = 500 * 1024 * 1024
_MAX_BACKUP_UNCOMPRESSED_BYTES = 2 * 1024 * 1024 * 1024

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
    final_dest = dest_zip
    final_dest.parent.mkdir(parents=True, exist_ok=True)
    for stale_path in final_dest.parent.glob(f".{final_dest.name}.*.tmp"):
        try:
            stale_path.unlink()
        except OSError:
            pass
    with tempfile.NamedTemporaryFile(
        mode="wb", dir=final_dest.parent, prefix=f".{final_dest.name}.",
        suffix=".tmp", delete=False,
    ) as temp_file:
        temp_path = Path(temp_file.name)
    dest_zip = temp_path
    
    with zipfile.ZipFile(dest_zip, "w", zipfile.ZIP_DEFLATED) as zf:
        # config 目录
        _add_dir_to_zip(zf, app_paths.CONFIG_DIR, "config")
        # data 目录（信箱数据）
        _add_dir_to_zip(zf, app_paths.DATA_DIR, "data")
        # images 目录（相框图片，可能很大，但用户选择备份时包含）
        _add_dir_to_zip(zf, app_paths.IMAGES_DIR, "images")
    os.replace(dest_zip, final_dest)
    return final_dest

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
    members = zf.infolist()
    if len(members) > _MAX_BACKUP_ENTRIES:
        raise ValueError(f"zip 鏉＄洰杩囧锛屾嫤鎴厓绱犳暟: {len(members)}")

    total_size = 0
    seen_targets: set[Path] = set()
    for member in members:
        mode = (member.external_attr >> 16) & 0xFFFF
        if mode and (mode & 0o170000) == 0o120000:
            raise ValueError(f"zip 鍖呭惈涓嶅厑璁哥殑绗﹀彿閾炬帴: {member.filename}")
        if member.file_size > _MAX_BACKUP_MEMBER_BYTES:
            raise ValueError(f"zip 鏂囦欢杩囧ぇ锛屾嫤鎴В鍘嬶細{member.filename}")
        total_size += member.file_size
        if total_size > _MAX_BACKUP_UNCOMPRESSED_BYTES:
            raise ValueError("zip 瑙ｅ帇鍚庢�诲ぇ灏忚秴杩囦笂闄愶紝鎷掔粷瑙ｅ帇")
        target = (dest / member.filename).resolve()
        try:
            target.relative_to(dest_resolved)
        except ValueError:
            raise ValueError(f"zip 条目含非法路径，拒绝解压: {member.filename}")
        # 3.12+ 的 extractall filter 更安全，但我们自己逐条校验兼容性更好
        if target in seen_targets:
            raise ValueError(f"zip 鍖呭惈閲嶅璺緞: {member.filename}")
        seen_targets.add(target)
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
        try:
            _safe_extract_all(zf, tmp)
        except Exception:
            shutil.rmtree(tmp, ignore_errors=True)
            raise

        # 覆盖 config
        src_config = tmp / "config"
        if src_config.exists():
            try:
                _overwrite_dir(src_config, app_paths.CONFIG_DIR)
            except Exception:
                shutil.rmtree(tmp, ignore_errors=True)
                raise
        # 覆盖 data
        src_data = tmp / "data"
        if src_data.exists():
            try:
                _overwrite_dir(src_data, app_paths.DATA_DIR)
            except Exception:
                shutil.rmtree(tmp, ignore_errors=True)
                raise
        # 覆盖 images
        src_images = tmp / "images"
        if src_images.exists():
            try:
                _overwrite_dir(src_images, app_paths.IMAGES_DIR)
            except Exception:
                shutil.rmtree(tmp, ignore_errors=True)
                raise

        # 清理临时目录
        shutil.rmtree(tmp, ignore_errors=True)


def _overwrite_dir(src: Path, dst: Path) -> None:
    """用 src 覆盖 dst：整体替换（删除 dst 再 copytree）。

    原实现只把 src 的条目拷过去，不删 dst 中 src 没有的文件——
    与用户确认框提示"恢复将覆盖当前所有数据"不一致，会遗留备份后新增的信件/配置。
    """
    if dst.exists():
        shutil.rmtree(dst)
    dst.parent.mkdir(parents=True, exist_ok=True)
    shutil.copytree(src, dst)
