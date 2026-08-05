"""版本号与资源定位工具。

- __version__: 主版本号，发 Release 前改这里
- resource_path(rel_path): 打包后在 sys._MEIPASS 下找资源，开发走项目根
"""
from __future__ import annotations

import sys
from pathlib import Path

__version__ = "0.2.0"
__author__ = "Couple Suite"


def project_root() -> Path:
    """开发模式：项目根目录（launcher.py / couple_suite.spec 所在）。"""
    return Path(__file__).resolve().parent


def _bundle_root() -> Path:
    """PyInstaller onefile/onedir：sys._MEIPASS；否则回退项目根。"""
    if getattr(sys, "frozen", False) and hasattr(sys, "_MEIPASS"):
        return Path(sys._MEIPASS)
    return project_root()


def resource_path(rel_path: str) -> Path:
    """返回只读资源的绝对路径（assets/china_geo.json、assets/icon.ico 等）。

    打包状态：sys._MEIPASS / rel_path
    开发状态：项目根目录 / rel_path
    """
    p = Path(rel_path)
    if p.is_absolute():
        return p
    return _bundle_root() / p
