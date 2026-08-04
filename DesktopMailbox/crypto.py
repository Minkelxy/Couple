"""Fernet 对称加密：首次运行生成密钥文件，之后复用。

密钥保存在 data/key.key，明文落地。本模块只解决"信件内容不裸存"
这一需求，不是抵御物理访问的强安全方案——单机信箱够用。
"""
from __future__ import annotations

from pathlib import Path

from cryptography.fernet import Fernet

from . import config

_KEY_PATH = config.DATA_DIR / "key.key"
_fernet: Fernet | None = None


def _load_or_create_key() -> bytes:
    if _KEY_PATH.exists():
        return _KEY_PATH.read_bytes()
    key = Fernet.generate_key()
    _KEY_PATH.write_bytes(key)
    return key


def get_fernet() -> Fernet:
    global _fernet
    if _fernet is None:
        _fernet = Fernet(_load_or_create_key())
    return _fernet


def encrypt(data: bytes) -> bytes:
    return get_fernet().encrypt(data)


def decrypt(token: bytes) -> bytes:
    return get_fernet().decrypt(token)
