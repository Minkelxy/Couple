"""配置管理：两个角色名 + 数据目录。"""
from __future__ import annotations

from copy import deepcopy
from datetime import datetime
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
    "cloud_pair_code": "",         # 旧版 pair_code，仅迁移旧客户端时使用
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


def _bounded_int(value, default: int, minimum: int, maximum: int) -> int:
    if isinstance(value, bool):
        return default
    try:
        return min(max(int(value), minimum), maximum)
    except (TypeError, ValueError):
        return default


def _text(value, default: str = "") -> str:
    return value.strip() if isinstance(value, str) else default


def _normalize_anniversaries(value) -> list[dict]:
    if not isinstance(value, list):
        return []
    result = []
    for raw in value:
        if not isinstance(raw, dict):
            continue
        date_value = raw.get("date")
        if not isinstance(date_value, str):
            continue
        try:
            datetime.strptime(f"2000-{date_value}", "%Y-%m-%d")
        except ValueError:
            continue
        item = dict(raw)
        item["id"] = _text(item.get("id"), date_value)
        item["date"] = date_value
        item["title"] = _text(item.get("title"), "纪念日")
        item["content"] = _text(item.get("content"), "")
        item["deliver_hour"] = _bounded_int(
            item.get("deliver_hour"), 8, 0, 23
        )
        result.append(item)
    return result


def _normalize(data: dict | None) -> dict:
    stored = data if isinstance(data, dict) else {}
    data = deepcopy(DEFAULTS)
    data.update(stored)
    data["my_name"] = _text(data.get("my_name"), DEFAULTS["my_name"])
    data["their_name"] = _text(data.get("their_name"), DEFAULTS["their_name"])
    data["sync_enabled"] = data.get("sync_enabled") if isinstance(data.get("sync_enabled"), bool) else DEFAULTS["sync_enabled"]
    data["sync_mode"] = data.get("sync_mode") if data.get("sync_mode") in ("lan", "cloud", "both") else DEFAULTS["sync_mode"]
    for key in ("peer_host", "cloud_server", "cloud_pair_code"):
        data[key] = _text(data.get(key), DEFAULTS[key])
    data["check_interval_sec"] = _bounded_int(
        data.get("check_interval_sec"), DEFAULTS["check_interval_sec"], 10, 600
    )
    for key in ("peer_port", "sync_port"):
        data[key] = _bounded_int(data.get(key), DEFAULTS[key], 1, 65535)
    data["cloud_poll_interval_sec"] = _bounded_int(
        data.get("cloud_poll_interval_sec"), DEFAULTS["cloud_poll_interval_sec"], 5, 3600
    )
    data["anniversaries"] = _normalize_anniversaries(data.get("anniversaries", []))
    return data


def load() -> dict:
    return _normalize(_STORE.load())


def save(data: dict) -> None:
    _STORE.save(data)


def update(**kwargs) -> dict:
    data = _STORE.load()
    if not isinstance(data, dict):
        data = {}
    merged = dict(data)
    merged.update(kwargs)
    normalized = _normalize(merged)
    _STORE.save(normalized)
    return normalized


def ensure_dirs() -> None:
    app_paths.ensure_dirs()
