"""信件存储：元数据明文索引 + 正文/附件加密落盘。

存储结构：
  data/mailbox.json          # 元数据列表（明文，便于检索排序）
  data/letters/{id}.enc      # 加密的正文（UTF-8 文本）
  data/letters/{id}_att.enc  # 加密的附件（图片字节）
"""
from __future__ import annotations

import re
import threading
import uuid
from datetime import datetime
from pathlib import Path
from typing import Optional

from common_utils import AtomicJsonStore, atomic_write_bytes, log_exception, log_warning

from . import config
from . import crypto

_META_PATH = config.DATA_DIR / "mailbox.json"
_LETTERS_DIR = config.DATA_DIR / "letters"
_META_STORE = AtomicJsonStore(_META_PATH, [])

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
    data = _META_STORE.load()
    if not isinstance(data, list):
        return []
    valid: list[dict] = []
    for raw in data:
        if not isinstance(raw, dict):
            continue
        letter_id = raw.get("id")
        if not isinstance(letter_id, str) or not _safe_id(letter_id):
            continue
        deliver_at = raw.get("deliver_at")
        if not isinstance(deliver_at, str):
            continue
        try:
            parsed = datetime.fromisoformat(deliver_at)
        except ValueError:
            continue
        # Keep comparisons deterministic even if an imported record has a timezone.
        if parsed.tzinfo is not None:
            parsed = parsed.astimezone().replace(tzinfo=None)
        item = dict(raw)
        item["deliver_at"] = parsed.isoformat(timespec="minutes")
        created_at = item.get("created_at")
        if not isinstance(created_at, str):
            created_at = deliver_at
        try:
            created_parsed = datetime.fromisoformat(created_at)
        except ValueError:
            created_parsed = parsed
        if created_parsed.tzinfo is not None:
            created_parsed = created_parsed.astimezone().replace(tzinfo=None)
        item["created_at"] = created_parsed.isoformat(timespec="seconds")
        for field, fallback in (
            ("author", "?"),
            ("recipient", "?"),
            ("title", "(无标题)"),
        ):
            if not isinstance(item.get(field), str):
                item[field] = fallback
        if not isinstance(item.get("has_attachment"), bool):
            item["has_attachment"] = False
        if not isinstance(item.get("attachment_ext"), str):
            item["attachment_ext"] = ""
        if not isinstance(item.get("read"), bool):
            item["read"] = False
        valid.append(item)
    return valid


def _save_meta(items: list[dict]) -> None:
    _META_STORE.save(items)


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
        written_paths: list[Path] = []

        # 加密正文
        enc_text = crypto.encrypt(content.encode("utf-8"))
        text_path = _LETTERS_DIR / f"{letter_id}.enc"
        atomic_write_bytes(text_path, enc_text)
        written_paths.append(text_path)

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
            try:
                enc_att = crypto.encrypt(attachment_bytes)
                attachment_path = _LETTERS_DIR / f"{letter_id}_att.enc"
                atomic_write_bytes(attachment_path, enc_att)
                written_paths.append(attachment_path)
            except Exception:
                for path in written_paths:
                    try:
                        path.unlink()
                    except OSError:
                        pass
                raise

        items.append(meta)
        try:
            _save_meta(items)
        except Exception:
            for path in written_paths:
                try:
                    path.unlink()
                except OSError:
                    pass
            raise
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
            if it.get("id") == letter_id:
                it["read"] = True
                break
        _save_meta(items)


def delete_letter(letter_id: str) -> None:
    if not _safe_id(letter_id):
        log_warning("非法 letter_id，拒绝删除: %r", letter_id)
        return
    with _LOCK:
        items = _load_meta()
        items = [it for it in items if it.get("id") != letter_id]
        _save_meta(items)
    for suffix in (".enc", "_att.enc"):
        p = _LETTERS_DIR / f"{letter_id}{suffix}"
        if p.exists():
            p.unlink()


def count_unread() -> int:
    return len(list_due_unread())
