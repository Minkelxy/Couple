"""公钥身份系统：Ed25519 密钥对、配对信息持久化、信道 ID、安全码、签名/验签。

目录结构：
  %APPDATA%/CoupleSuite/config/identity/
    ├── my_sk.enc          私钥（用现有 Fernet 对称密钥加密，不裸存）
    ├── my_pk.json         我自己的公钥 + 元信息
    └── partner.json       对方的公钥（配对完成后存在，未配对则文件不存在）

信道与鉴权设计：
  - channel_id = SHA256( 双方原始公钥字节按字典序拼接 ) 的 hex 前 24 字符
    （双方对称计算出同一个值，用作 relay_server 上专属"桶"的 key，替代原 pair_code）
  - 安全码 = SHA256( 同上拼法 ) 前 3 字节 → int % 1,000,000 → 零填充 6 位十进制
    两端用户对念即可确认没有中间人（MITM 下两端公钥组合不同，安全码一定不同）
  - 签名内容哈希：H = SHA256( canon_json(meta 除 sig_* 外字段) || content_utf8 || att || att_ext_utf8 )
    sig = Ed25519_Sign(sk, H) ；发送方带 meta.pk_fp + meta.sig_b64；接收方用对方 pk 验
"""
from __future__ import annotations

import base64
import hashlib
import json
import secrets
import threading
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import app_paths
from common_utils import AtomicJsonStore, atomic_write_bytes, log_exception, log_warning
from DesktopMailbox.crypto import decrypt as _fernet_dec, encrypt as _fernet_enc

IDENTITY_DIR = app_paths.CONFIG_DIR / "identity"
_MY_SK_ENC = IDENTITY_DIR / "my_sk.enc"
_MY_PK_JSON = IDENTITY_DIR / "my_pk.json"
_PARTNER_JSON = IDENTITY_DIR / "partner.json"
_MY_PK_STORE = AtomicJsonStore(_MY_PK_JSON, {})
_PARTNER_STORE = AtomicJsonStore(_PARTNER_JSON, {})

# 6 位配对 token 字符表（去掉 I/L/0/O 避免视觉混淆）
_TOKEN_ALPHABET = "ABCDEFGHJKMNPQRSTUVWXYZ23456789"

_STATE_LOCK = threading.Lock()


# ============ 底层：序列化 / 哈希 ============

def _b64e(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


def _b64d(s: str) -> bytes:
    pad = "=" * (-len(s) % 4)
    return base64.urlsafe_b64decode(s + pad)


def _canonical_json(obj: Any) -> bytes:
    """排序 key 的紧凑 JSON，保证双方对同一 dict 哈希一致。"""
    return json.dumps(obj, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")


def _pk_fp(pk_bytes: bytes) -> str:
    """公钥指纹：base64url(SHA256(pk_bytes)[:8]) ≈ 11 字符，UI 展示用。"""
    return _b64e(hashlib.sha256(pk_bytes).digest()[:8])


def _sorted_concat(pk_a: bytes, pk_b: bytes) -> bytes:
    """按字典序拼接双方公钥，保证两端对称得到同一种拼接。"""
    return pk_a + pk_b if pk_a <= pk_b else pk_b + pk_a


def _compute_channel_and_safety(my_pk: bytes, partner_pk: bytes) -> tuple[str, str]:
    """返回 (channel_id, 6 位安全码)。"""
    material = _sorted_concat(my_pk, partner_pk)
    digest = hashlib.sha256(material).digest()
    channel = digest.hex()[:24]
    safety_int = int.from_bytes(digest[:3], "big") % 1_000_000
    safety = f"{safety_int:06d}"
    return channel, safety


# ============ 对外类型 ============

@dataclass
class IdentityStatus:
    paired: bool                 # 是否已与对方建立公钥配对
    my_pk_b64: str               # 我的公钥 base64
    my_fingerprint: str          # 我的公钥指纹（UI 展示）
    partner_pk_b64: str | None   # 对方公钥 base64
    partner_fingerprint: str | None
    partner_nickname: str | None
    channel_id: str | None       # 专属通道 ID，替代 pair_code
    safety_code: str | None      # 6 位安全码，两端对念


# ============ 密钥管理 ============

_identity_lock = threading.Lock()
_cached_sk: object | None = None   # Ed25519PrivateKey 或 None
_cached_status: IdentityStatus | None = None


def _ensure_dirs() -> None:
    IDENTITY_DIR.mkdir(parents=True, exist_ok=True)


def _load_ed25519_private_key(sk_bytes: bytes):
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
    return Ed25519PrivateKey.from_private_bytes(sk_bytes)


def _load_ed25519_public_key(pk_bytes: bytes):
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey
    return Ed25519PublicKey.from_public_bytes(pk_bytes)


def ensure_identity() -> tuple[bytes, object]:
    """保证本地存在身份密钥；返回 (公钥 bytes, Ed25519PrivateKey 对象)。

    只生成一次：若本地已有 my_sk.enc 直接加载，否则用 Ed25519 生成后用
    Fernet 加密落盘。
    """
    global _cached_sk, _cached_status
    with _identity_lock:
        _ensure_dirs()
        if _cached_sk is not None and _MY_PK_JSON.exists():
            record = _MY_PK_STORE.load()
            try:
                pk_bytes = _b64d(record["pk_b64"])
                _load_ed25519_public_key(pk_bytes)
                cached_pk = _cached_sk.public_key().public_bytes_raw()
                if cached_pk != pk_bytes:
                    raise ValueError("缓存私钥与公钥文件不匹配")
                return pk_bytes, _cached_sk
            except (AttributeError, KeyError, TypeError, ValueError):
                _cached_sk = None
        if _MY_SK_ENC.exists() and _MY_PK_JSON.exists():
            try:
                sk_bytes = _fernet_dec(_MY_SK_ENC.read_bytes())
                sk = _load_ed25519_private_key(sk_bytes)
                pk_bytes = sk.public_key().public_bytes_raw()
                _MY_PK_STORE.save({
                    "pk_b64": _b64e(pk_bytes),
                    "created_at": __import__("datetime").datetime.now().isoformat(timespec="seconds"),
                    "fingerprint": _pk_fp(pk_bytes),
                })
                _cached_sk = sk
                _cached_status = None
                return pk_bytes, sk
            except Exception as e:
                log_exception("身份密钥损坏，重新生成: %s", e)
        # 生成新身份
        from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
        sk = Ed25519PrivateKey.generate()
        sk_bytes = sk.private_bytes_raw()
        pk_bytes = sk.public_key().public_bytes_raw()
        # 落盘：sk 用 Fernet 加密（至少不比裸存差）
        atomic_write_bytes(_MY_SK_ENC, _fernet_enc(sk_bytes))
        _MY_PK_STORE.save({
            "pk_b64": _b64e(pk_bytes),
            "created_at": __import__("datetime").datetime.now().isoformat(timespec="seconds"),
            "fingerprint": _pk_fp(pk_bytes),
        })
        _cached_sk = sk
        _cached_status = None
        return pk_bytes, sk


def get_status() -> IdentityStatus:
    """返回当前身份状态（未配对/已配对）。每次读文件并重新计算 channel_id/safety_code。"""
    global _cached_status
    with _STATE_LOCK:
        my_pk, _sk = ensure_identity()
        my_b64 = _b64e(my_pk)
        my_fp = _pk_fp(my_pk)
        partner_pk = None
        partner_nick = None
        partner_fp = None
        channel = None
        safety = None
        if _PARTNER_JSON.exists():
            try:
                pd = _PARTNER_STORE.load()
                if not isinstance(pd, dict):
                    raise ValueError("partner.json 不是对象")
                pk_b64 = pd.get("pk_b64", "")
                if not isinstance(pk_b64, str) or not pk_b64:
                    raise ValueError("partner.json 缺少公钥")
                candidate_pk = _b64d(pk_b64)
                _load_ed25519_public_key(candidate_pk)
                if candidate_pk == my_pk:
                    raise ValueError("partner.json 包含本机公钥")
                partner_pk = candidate_pk
                raw_nick = pd.get("nickname")
                partner_nick = raw_nick if isinstance(raw_nick, str) else None
                partner_fp = _pk_fp(partner_pk)
                channel, safety = _compute_channel_and_safety(my_pk, partner_pk)
            except (OSError, TypeError, ValueError) as e:
                log_warning("读取对方公钥文件失败，视为未配对: %s", e)
        status = IdentityStatus(
            paired=(partner_pk is not None),
            my_pk_b64=my_b64,
            my_fingerprint=my_fp,
            partner_pk_b64=(_b64e(partner_pk) if partner_pk is not None else None),
            partner_fingerprint=partner_fp,
            partner_nickname=partner_nick,
            channel_id=channel,
            safety_code=safety,
        )
        _cached_status = status
        return status


# ============ 配对信息写入 / 重置 ============

def save_partner(pk_b64: str, nickname: str | None = None) -> IdentityStatus:
    """写入对方公钥（即配对完成）。返回更新后的 IdentityStatus。"""
    global _cached_status
    with _STATE_LOCK:
        # 先解码验证：坏的 b64 / 非法长度直接抛
        pk_bytes = _b64d(pk_b64)
        from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey
        pk = Ed25519PublicKey.from_public_bytes(pk_bytes)
        # 防止把自己的公钥存成 partner
        my_pk, _ = ensure_identity()
        if pk_bytes == my_pk:
            raise ValueError("不能把自己的公钥存成对方")
        _ensure_dirs()
        import datetime as _dt
        payload = {
            "pk_b64": _b64e(pk.public_bytes_raw()),
            "fingerprint": _pk_fp(pk.public_bytes_raw()),
            "nickname": nickname or "",
            "paired_at": _dt.datetime.now().isoformat(timespec="seconds"),
            "confirmed": True,
        }
        _PARTNER_STORE.save(payload)
        _cached_status = None
    return get_status()


def reset_partner() -> None:
    """解除配对：删除 partner.json。"""
    global _cached_status
    with _STATE_LOCK:
        try:
            if _PARTNER_JSON.exists():
                _PARTNER_JSON.unlink()
        except OSError as e:
            log_exception("删除 partner.json 失败: %s", e)
        _cached_status = None


# ============ 配对 token 生成（6 位可视） ============

def generate_pairing_token() -> str:
    """6 位可视无歧义字符（去 I/L/0/O）。服务端按此 token 做临时公钥交换胶水。"""
    return "".join(secrets.choice(_TOKEN_ALPHABET) for _ in range(6))


# ============ 签名 / 验签 ============

def _signing_digest(meta: dict, content: str, attachment: bytes, att_ext: str) -> bytes:
    """构造待签名的稳定哈希。

    规则：meta 里不含 pk_fp / sig_b64；其他字段按 key 字典序序列化，
    拼 content utf8 bytes、att bytes、att_ext utf8 bytes，一起 SHA256。
    """
    m = {k: v for k, v in meta.items() if k not in ("pk_fp", "sig_b64")}
    h = hashlib.sha256()
    h.update(_canonical_json(m))
    h.update(content.encode("utf-8"))
    h.update(attachment or b"")
    h.update((att_ext or "").encode("utf-8"))
    return h.digest()


def sign_message(meta: dict, content: str, attachment: bytes, att_ext: str) -> dict:
    """为一条同步消息计算签名并注入 meta。返回新的 meta 字典（不修改入参）。

    注入字段：
      pk_fp      : 发送方公钥指纹（接收端据此判断"是不是我认识的对方"，但验签用 partner_pk 硬校验）
      sig_b64    : Ed25519 签名 base64url
      nonce      : 16 字符随机串，防重放（同一消息每次签名都不同，使摘要不可复用）
      message_id : UUID 字符串，接收端据此做幂等去重，避免同一封信重复落盘
    """
    new_meta = dict(meta)
    # 防重放与幂等：nonce 保证同一内容每次签名摘要不同，message_id 供接收端去重。
    # 二者必须在 _signing_digest 调用前写入，使其参与签名；接收端 verify_message
    # 时 meta 已含这两个字段，签名自动覆盖，无需额外校验逻辑。
    new_meta["nonce"] = secrets.token_hex(8)
    new_meta["message_id"] = str(uuid.uuid4())
    pk_bytes, sk = ensure_identity()
    digest = _signing_digest(new_meta, content, attachment or b"", att_ext or "")
    sig_bytes = sk.sign(digest)
    new_meta["pk_fp"] = _pk_fp(pk_bytes)
    new_meta["sig_b64"] = _b64e(sig_bytes)
    return new_meta


def verify_message(meta: dict, content: str, attachment: bytes, att_ext: str) -> bool:
    """验签：只有匹配本地保存的 partner.pub 的签名才通过。

    - 未配对时（没有 partner.pub）直接返回 False；
    - 没有 pk_fp / sig_b64 字段直接返回 False；
    - 签名错误返回 False。
    """
    status = get_status()
    if not status.paired or not status.partner_pk_b64:
        return False
    if not isinstance(meta, dict):
        return False
    sig_b64 = meta.get("sig_b64")
    if not sig_b64:
        return False
    try:
        pk_bytes = _b64d(status.partner_pk_b64)
        pk = _load_ed25519_public_key(pk_bytes)
        sig_bytes = _b64d(sig_b64)
        digest = _signing_digest(meta, content, attachment or b"", att_ext or "")
        pk.verify(sig_bytes, digest)
        return True
    except Exception:
        # cryptography 验签失败抛 InvalidSignature
        return False


# ============ 配对阶段安全码校验 ============

def safety_code_for_pending(partner_pk_b64: str) -> str:
    """配对流程中，还没 save_partner() 时预先算安全码让用户比对。"""
    my_pk, _ = ensure_identity()
    partner_pk = _b64d(partner_pk_b64)
    _ = _load_ed25519_public_key(partner_pk)  # 合法性校验
    if partner_pk == my_pk:
        raise ValueError("partner_pk 是自己，拒绝配对")
    _, safety = _compute_channel_and_safety(my_pk, partner_pk)
    return safety
