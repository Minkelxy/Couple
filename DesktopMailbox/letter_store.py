"""信件存储：元数据明文索引 + 正文/附件加密落盘。

存储结构：
  data/mailbox.json          # 元数据列表（明文，便于检索排序）
  data/letters/{id}.enc      # 加密的正文（UTF-8 文本）
  data/letters/{id}_att.enc  # 加密的附件（图片字节）
"""
from __future__ import annotations

import json
import os
import re
import threading
import uuid
from datetime import datetime
from pathlib import Path
from typing import Optional

from common_utils import log_exception, log_warning

from . import config
from . import crypto

_META_PATH = config.DATA_DIR / "mailbox.json"
_LETTERS_DIR = config.DATA_DIR / "letters"

# letter_id 仅允许 12 位十六进制（write_letter 用 uuid4().hex[:12] 生成）
# 防御路径遍历：read/delete 时校验，避免 ../ 逃逸 _LETTERS_DIR
_SAFE_ID_RE = re.compile(r"^[0-9a-f]{1,16}$")

# 同步线程（LAN socket / 云轮询）与主线程并发写 mailbox.json，
# read-modify-write 非原子会丢信；用一把模块级锁串行化所有写操作
_LOCK = threading.Lock()


def _now_iso() -> str:
    return datetime.now().isoformat(timespec="seconds")


def _safe_id(letter_id: str) -> bool:
    """校验 letter_id 是否为安全格式（纯十六进制），防路径遍历。"""
    return bool(letter_id) and bool(_SAFE_ID_RE.match(letter_id))


def _load_meta() -> list[dict]:
    if not _META_PATH.exists():
        return []
    try:
        return json.loads(_META_PATH.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError) as e:
        log_warning("信件元数据加载失败，返回空列表: %s", e)
        return []


def _save_meta(items: list[dict]) -> None:
    """原子写：先写临时文件再 os.replace，避免写入中途崩溃导致 JSON 截断损坏。"""
    tmp = _META_PATH.with_suffix(".tmp")
    tmp.write_text(
        json.dumps(items, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    os.replace(tmp, _META_PATH)


def write_letter(
    *,
    author: str,
    recipient: str,
    title: str,
    content: str,
    deliver_at: datetime,
    attachment_bytes: Optional[bytes] = None,
    attachment_ext: str = "",
    message_id: Optional[str] = None,
) -> dict:
    """落盘一封信，返回元数据。

    message_id 非 None 时做幂等去重：若本地已存在同 message_id 的信件，
    直接返回已有信件 meta，不再写入（用于同步消息防重复落盘）。
    message_id 为 None（本地草稿、旧版同步消息）按原逻辑写入，不做去重。
    """
    _LETTERS_DIR.mkdir(parents=True, exist_ok=True)

    with _LOCK:
        items = _load_meta()
        # 幂等去重：同 message_id 的信件已存在则跳过写入，直接返回已有 meta
        if message_id is not None:
            for it in items:
                if it.get("message_id") == message_id:
                    return it

        letter_id = uuid.uuid4().hex[:12]

        # 加密正文
        enc_text = crypto.encrypt(content.encode("utf-8"))
        (_LETTERS_DIR / f"{letter_id}.enc").write_bytes(enc_text)

        meta = {
            "id": letter_id,
            "author": author,
            "recipient": recipient,
            "title": title,
            "created_at": _now_iso(),
            "deliver_at": deliver_at.isoformat(timespec="minutes"),
            "read": False,
            "has_attachment": attachment_bytes is not None,
            "attachment_ext": attachment_ext,
        }
        if message_id is not None:
            meta["message_id"] = message_id

        if attachment_bytes is not None:
            enc_att = crypto.encrypt(attachment_bytes)
            (_LETTERS_DIR / f"{letter_id}_att.enc").write_bytes(enc_att)

        items.append(meta)
        _save_meta(items)
    return meta


def read_content(letter_id: str) -> str:
    """解密并返回正文。"""
    if not _safe_id(letter_id):
        log_warning("非法 letter_id，拒绝读取正文: %r", letter_id)
        return "(正文缺失)"
    path = _LETTERS_DIR / f"{letter_id}.enc"
    if not path.exists():
        return "(正文缺失)"
    try:
        return crypto.decrypt(path.read_bytes()).decode("utf-8")
    except Exception:
        log_exception("解密正文失败: %s", letter_id)
        return "(正文损坏)"


def read_attachment(letter_id: str) -> Optional[bytes]:
    """解密并返回附件字节，无则 None。"""
    if not _safe_id(letter_id):
        log_warning("非法 letter_id，拒绝读取附件: %r", letter_id)
        return None
    path = _LETTERS_DIR / f"{letter_id}_att.enc"
    if not path.exists():
        return None
    try:
        return crypto.decrypt(path.read_bytes())
    except Exception:
        log_exception("解密附件失败: %s", letter_id)
        return None


def list_letters(*, include_unsent: bool = False) -> list[dict]:
    """返回信件列表，按送达时间升序。

    include_unsent=False（默认）：只返回已到送达时间的信件（收件箱视图）。
    include_unsent=True：返回全部（含未送达，写信人可见自己的草稿）。
    """
    items = _load_meta()
    now = datetime.now()
    if not include_unsent:
        items = [
            it for it in items
            if datetime.fromisoformat(it["deliver_at"]) <= now
        ]
    items.sort(key=lambda it: it["deliver_at"])
    return items


def list_due_unread() -> list[dict]:
    """到期且未读的信件（用于通知）。"""
    now = datetime.now()
    return [
        it for it in _load_meta()
        if not it["read"]
        and datetime.fromisoformat(it["deliver_at"]) <= now
    ]


def mark_read(letter_id: str) -> None:
    with _LOCK:
        items = _load_meta()
        for it in items:
            if it["id"] == letter_id:
                it["read"] = True
                break
        _save_meta(items)


def delete_letter(letter_id: str) -> None:
    if not _safe_id(letter_id):
        log_warning("非法 letter_id，拒绝删除: %r", letter_id)
        return
    with _LOCK:
        items = _load_meta()
        items = [it for it in items if it["id"] != letter_id]
        _save_meta(items)
    for suffix in (".enc", "_att.enc"):
        p = _LETTERS_DIR / f"{letter_id}{suffix}"
        if p.exists():
            p.unlink()


def count_unread() -> int:
    return len(list_due_unread())
