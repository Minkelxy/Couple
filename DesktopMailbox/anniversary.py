"""纪念日自动投递：启动时检查今天是否匹配，未投递过则生成一封信。

通过 sent_log.json 记录 {anniv_id}-{year} 已投递，避免重复。
"""
from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

from . import config
from . import letter_store

_SENT_LOG = config.DATA_DIR / "anniv_sent_log.json"


def _load_sent() -> set[str]:
    if not _SENT_LOG.exists():
        return set()
    try:
        return set(json.loads(_SENT_LOG.read_text(encoding="utf-8")))
    except (json.JSONDecodeError, OSError):
        return set()


def _mark_sent(key: str) -> None:
    s = _load_sent()
    s.add(key)
    _SENT_LOG.write_text(json.dumps(sorted(s), ensure_ascii=False, indent=2),
                         encoding="utf-8")


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
        if key in _load_sent():
            continue  # 今年已投递
        # 送达时间：当天指定小时，已过则立即
        hour = int(anniv.get("deliver_hour", 8))
        deliver_at = today.replace(hour=hour, minute=0, second=0, microsecond=0)
        if deliver_at <= today:
            deliver_at = today
        meta = letter_store.write_letter(
            author=author,
            recipient=recipient,
            title=anniv.get("title", "纪念日"),
            content=anniv.get("content", ""),
            deliver_at=deliver_at,
        )
        _mark_sent(key)
        created.append(meta)
    return created
