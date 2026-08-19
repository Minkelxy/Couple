"""Durable cloud-send queue shared by letters and synchronization events."""
from __future__ import annotations

import base64
import math
import threading
import time
import uuid
from pathlib import Path

from common_utils import AtomicJsonStore


class OutboxStore:
    def __init__(self, path: Path) -> None:
        self._store = AtomicJsonStore(path, [])
        self._lock = threading.RLock()

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
        with self._lock:
            items = [old for old in self._load() if old.get("id") != item_id]
            items.append(item)
            self._store.save(items)
        return item_id

    def due(self, now: float | None = None) -> list[dict]:
        now = time.time() if now is None else now
        with self._lock:
            return [item for item in self._load()
                    if item.get("next_retry_at", 0.0) <= now]

    def remove(self, item_id: str) -> None:
        with self._lock:
            self._store.save(
                [item for item in self._load() if item.get("id") != item_id]
            )

    def retry(self, item_id: str) -> None:
        with self._lock:
            items = self._load()
            for item in items:
                if item.get("id") == item_id:
                    attempts = _nonnegative_int(item.get("attempts", 0)) + 1
                    item["attempts"] = attempts
                    item["next_retry_at"] = time.time() + min(
                        3600, 2 ** min(attempts, 10)
                    )
                    break
            self._store.save(items)

    def _load(self) -> list[dict]:
        data = self._store.load()
        if not isinstance(data, list):
            return []
        result = []
        for item in data:
            if not isinstance(item, dict) or not item.get("id"):
                continue
            normalized = dict(item)
            normalized["id"] = str(normalized["id"])
            normalized["attempts"] = _nonnegative_int(normalized.get("attempts", 0))
            retry_at = normalized.get("next_retry_at", 0.0)
            try:
                retry_at = float(retry_at)
            except (TypeError, ValueError):
                retry_at = 0.0
            normalized["next_retry_at"] = retry_at if math.isfinite(retry_at) else 0.0
            result.append(normalized)
        return result


def _nonnegative_int(value) -> int:
    try:
        return max(0, int(value))
    except (TypeError, ValueError, OverflowError):
        return 0
