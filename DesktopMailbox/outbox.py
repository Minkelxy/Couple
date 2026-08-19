"""Durable cloud-send queue shared by letters and synchronization events."""
from __future__ import annotations

import base64
import time
import uuid
from pathlib import Path

from common_utils import AtomicJsonStore


class OutboxStore:
    def __init__(self, path: Path) -> None:
        self._store = AtomicJsonStore(path, [])

    def enqueue(self, meta: dict, content: str, attachment: bytes, att_ext: str) -> str:
        item_id = str(meta.get("message_id") or uuid.uuid4())
        item = {
            "id": item_id,
            "meta": meta,
            "content": content,
            "attachment_b64": base64.b64encode(attachment or b"").decode("ascii"),
            "attachment_ext": att_ext or "",
            "attempts": 0,
            "next_retry_at": 0.0,
        }
        items = self._load()
        items = [old for old in items if old.get("id") != item_id]
        items.append(item)
        self._store.save(items)
        return item_id

    def due(self, now: float | None = None) -> list[dict]:
        now = time.time() if now is None else now
        return [item for item in self._load() if item.get("next_retry_at", 0) <= now]

    def remove(self, item_id: str) -> None:
        self._store.save([item for item in self._load() if item.get("id") != item_id])

    def retry(self, item_id: str) -> None:
        items = self._load()
        for item in items:
            if item.get("id") == item_id:
                attempts = int(item.get("attempts", 0)) + 1
                item["attempts"] = attempts
                item["next_retry_at"] = time.time() + min(3600, 2 ** min(attempts, 10))
                break
        self._store.save(items)

    def _load(self) -> list[dict]:
        data = self._store.load()
        return [item for item in data if isinstance(item, dict) and item.get("id")] \
            if isinstance(data, list) else []
