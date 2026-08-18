"""配置管理：两个角色名 + 数据目录。"""
from __future__ import annotations

from copy import deepcopy
from pathlib import Path

import app_paths
from common_utils import AtomicJsonStore

CONFIG_PATH = app_paths.CONFIG_DIR / "mailbox.json"
DATA_DIR = app_paths.DATA_DIR
_STORE = AtomicJsonStore(CONFIG_PATH, {})

DEFAULTS = {
    "my_name": "我",
    "their_name": "你",
    # 到期检查间隔（秒）
    "check_interval_sec": 30,
    # 局域网双机同步
    "sync_enabled": False,
    "peer_host": "",          # 对方 IP，如 192.168.1.20
    "peer_port": 52014,       # 对方端口
    "sync_port": 52014,       # 本机监听端口
    # 云中转同步
    "sync_mode": "lan",            # "lan" / "cloud" / "both"
    "cloud_server": "",            # 如 https://couple-relay.example.com
    "cloud_pair_code": "",         # 配对码，双方填相同码
    "cloud_poll_interval_sec": 30, # 云轮询间隔
    # 纪念日自动投递：每年这天自动生成一封信
    # date: "MM-DD"；deliver_hour: 当天几点送达（已过则立即）
    "anniversaries": [
        {
            "id": "meet",
            "date": "08-14",
            "title": "相识纪念日",
            "content": "今天是我们相识的纪念日，谢谢你一直在我身边。",
            "deliver_hour": 8,
        },
        {
            "id": "valentine",
            "date": "02-14",
            "title": "情人节快乐",
            "content": "情人节快乐，愿我们年年岁岁都如今日。",
            "deliver_hour": 9,
        },
    ],
}


def load() -> dict:
    data = deepcopy(DEFAULTS)
    stored = _STORE.load()
    if isinstance(stored, dict):
        data.update(stored)
    anniv = data.get("anniversaries", [])
    data["anniversaries"] = anniv if isinstance(anniv, list) else []
    return data


def save(data: dict) -> None:
    _STORE.save(data)


def update(**kwargs) -> dict:
    data = _STORE.load()
    if not isinstance(data, dict):
        data = {}
    merged = deepcopy(DEFAULTS)
    merged.update(data)
    merged.update(kwargs)
    _STORE.save(merged)
    return merged


def ensure_dirs() -> None:
    app_paths.ensure_dirs()
