"""Windows 开机自启动：通过注册表 HKCU Run 键控制。"""
from __future__ import annotations
import sys
import winreg
from pathlib import Path

APP_NAME = "CoupleSuite"
RUN_KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"

def _exe_path() -> str:
    """返回当前可执行路径。打包后是 exe 路径，开发时是 pythonw + 脚本。"""
    if getattr(sys, "frozen", False):
        # PyInstaller 打包后
        return sys.executable
    # 开发模式：用 pythonw 运行 launcher.py
    return f'"{sys.executable}" "{Path(__file__).parent / "launcher.py"}"'

def is_enabled() -> bool:
    """检查是否已开启自启动。"""
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY) as key:
            winreg.QueryValueEx(key, APP_NAME)
            return True
    except FileNotFoundError:
        return False
    except OSError:
        return False

def enable() -> bool:
    """开启自启动，返回是否成功。"""
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY, 0, winreg.KEY_SET_VALUE) as key:
            winreg.SetValueEx(key, APP_NAME, 0, winreg.REG_SZ, _exe_path())
            return True
    except OSError:
        return False

def disable() -> bool:
    """关闭自启动，返回是否成功。"""
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY, 0, winreg.KEY_SET_VALUE) as key:
            winreg.DeleteValue(key, APP_NAME)
            return True
    except FileNotFoundError:
        return True  # 本来就没有，视为成功
    except OSError:
        return False

def toggle(enabled: bool) -> bool:
    """根据 enabled 开关自启动。"""
    if enabled:
        return enable()
    else:
        return disable()
