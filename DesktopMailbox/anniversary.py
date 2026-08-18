"""纪念日自动投递：启动时检查今天是否匹配，未投递过则生成一封信。

通过 sent_log.json 记录 {anniv_id}-{year} 已投递，避免重复。
"""
from __future__ import annotations

import threading
from datetime import datetime
from pathlib import Path

from common_utils import AtomicJsonStore, log_exception

from . import config
from . import letter_store

_SENT_LOG = config.DATA_DIR / "anniv_sent_log.json"
_SENT_STORE = AtomicJsonStore(_SENT_LOG, [])
_LOCK = threading.Lock()


def _load_sent() -> set[str]:
    data = _SENT_STORE.load()
    return {item for item in data if isinstance(item, str)} if isinstance(data, list) else set()


def _mark_sent(*keys: str) -> None:
    """原子写入 sent_log，先于 write_letter 调用（占坑语义：崩溃后也不重复）。"""
    s = _load_sent()
    for k in keys:
        s.add(k)
    _SENT_STORE.save(sorted(s))


def check_and_deliver() -> list[dict]:
    """启动时调用：对今天匹配的纪念日生成信件，返回新生成的元数据列表。"""
    cfg = config.load()
    today = datetime.now()
    today_md = today.strftime("%m-%d")
    year = today.year
    author = cfg.get("my_name", "我")
    recipient = cfg.get("their_name", "你")

    created: list[dict] = []
    for anniv in cfg.get("anniversaries", []):
        if not isinstance(anniv, dict):
            continue
        if anniv.get("date") != today_md:
            continue
        anniv_id = anniv.get("id") or anniv.get("date")
        key = f"{anniv_id}-{year}"
        # 兜底稳定 key：基于 date + title，anniv_id 变更（编辑 id 或删除 id 回退 date）
        # 后只要 date + title 不变仍能命中，防同年重复投递
        stable_key = f"stable-{year}-{anniv.get('date')}-{anniv.get('title', '')}"
        # 多线程串行化 + 先占坑：先把 key 写入 sent_log，再落信
        # 崩溃/异常发生在中间：下一次启动 key 已在 sent_log 里，不会重复投递
        with _LOCK:
            sent = _load_sent()
            if key in sent or stable_key in sent:
                continue
            _mark_sent(key, stable_key)
        # 送达时间：当天指定小时，已过则立即
        try:
            hour = int(anniv.get("deliver_hour", 8))
        except (TypeError, ValueError):
            hour = 8
        hour = max(0, min(23, hour))
        deliver_at = today.replace(hour=hour, minute=0, second=0, microsecond=0)
        if deliver_at <= today:
            deliver_at = today
        try:
            meta = letter_store.write_letter(
                author=author,
                recipient=recipient,
                title=anniv.get("title", "纪念日"),
                content=anniv.get("content", ""),
                deliver_at=deliver_at,
            )
        except Exception:
            log_exception("纪念日信件写入失败，sent_log 已占坑避免重启重复: %s", key)
            continue
        created.append(meta)
    return created
