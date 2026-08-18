"""云中转服务器：在两台不在同一局域网的电脑间转发信件。

接口（与 DesktopMailbox/cloud_sync.py 对应）：

  == 旧的 legacy 路径（保留过渡期，仍支持 pair_code）==
  POST /api/send        — 发送一封信（入参带 pair_code）
  GET  /api/poll        — 增量拉取（入参带 pair_code）

  == 新的公钥身份路径（推荐）==
  POST /api/pairing/declare  — 配对双方分别声明自己的 pk/nickname 绑定一个 6 位 token
  GET  /api/pairing/poll     — 配对双方轮询：对方声明了吗？双方都 confirm 了吗？
  POST /api/pairing/confirm  — 配对双方各自用 nonce 签名证明身份 + 确认安全码
  POST /api/send        — 发送一封信（入参带 channel_id + pk_fp + sig_b64，签名校验通过才收）
  GET  /api/poll        — 增量拉取（入参带 channel_id + pk_fp + sig_b64，签名校验通过才回）

通用：
  GET  /health          — 健康检查
  GET  /                — 简单状态页

存储：
  - SQLite（letters.db，自动建表，WAL 模式支持多 worker）
  - 配对态：内存 dict（重启清空，TTL 10 分钟自动清）
  - 通道成员：SQLite channels 表（永久保留，已配对的双方永远能认出彼此）

清理：后台线程每 6 小时清理 30 天以上的信件（分批）。

运行：
  开发：python relay_server.py
  生产：gunicorn -w 2 -b 0.0.0.0:5000 relay_server:app
        （不建议超过 2 worker，SQLite 多 worker 并发仍受限，WAL 可减轻）

安全建议：
  - 配对成功后通道绑定双方公钥；所有 send/poll 请求都会在服务端 Ed25519 验签
  - 生产环境务必配置 HTTPS（nginx 反向代理 + Let's Encrypt）
  - 信件正文/附件在客户端已 base64 编码，但服务器明文存储，请勿在公共服务器长期保留
"""
from __future__ import annotations

import base64
import hashlib
import json
import re
import secrets
import sqlite3
import threading
import time
from contextlib import contextmanager
from datetime import datetime, timedelta
from pathlib import Path

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey
from flask import Flask, jsonify, request

app = Flask(__name__)

_DB_PATH = Path(__file__).parent / "letters.db"
_LOCK = threading.Lock()
_RETENTION_DAYS = 30
_CLEANUP_INTERVAL_SEC = 6 * 3600
# 单个附件上限（base64 编码后约 4/3 倍原始字节）
_MAX_ATTACH_B64_LEN = 50 * 1024 * 1024 * 2  # 允许原始 50MB，base64 放宽 2 倍
_MAX_CONTENT_B64_LEN = 2 * 1024 * 1024  # 正文文本 2MB 足够
_MAX_META_B64_LEN = 64 * 1024  # meta 元数据 JSON 序列化后上限 64KB
_MAX_PAIR_LEN = 128
_MIN_PAIR_LEN = 3
_MAX_ATTACH_EXT_LEN = 32
_MAX_SINCE_LEN = 64
_POLL_BATCH_LIMIT = 1000  # 单次 poll 最多返回 1000 封，避免断网很久回来的 OOM
# 整个请求体大小上限：content 2MB + attach 100MB + meta 64KB + pair_code 128B + 余量
_MAX_REQUEST_BYTES = 110 * 1024 * 1024
app.config["MAX_CONTENT_LENGTH"] = _MAX_REQUEST_BYTES

# pair_code / channel_id 白名单：字母、数字、下划线、短横线（hex 也合法）
_PAIR_RE = re.compile(r"^[A-Za-z0-9_\-]+$")
# ISO 8601 since 基本校验
_SINCE_RE = re.compile(r"^[0-9T:.\-]{16,64}$")

# ========== 配对状态（内存，重启清空，10 分钟 TTL）==========
_PAIRING: dict[str, dict] = {}
_PAIRING_TTL_SEC = 600
_PAIRING_LOCK = threading.Lock()


def _b64e(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


def _b64d(s: str) -> bytes:
    pad = "=" * (-len(s) % 4)
    return base64.urlsafe_b64decode(s + pad)


def _is_valid_pair(pair_code: str) -> bool:
    if not _MIN_PAIR_LEN <= len(pair_code) <= _MAX_PAIR_LEN:
        return False
    return _PAIR_RE.match(pair_code) is not None


def _is_valid_since(since: str) -> bool:
    if len(since) > _MAX_SINCE_LEN:
        return False
    return _SINCE_RE.match(since) is not None


def _is_valid_pk_b64(pk_b64: str) -> bool:
    """Ed25519 公钥：32 字节 raw，base64url 编码约 43 字符。"""
    if not isinstance(pk_b64, str) or not (40 <= len(pk_b64) <= 64):
        return False
    try:
        pk_bytes = _b64d(pk_b64)
        Ed25519PublicKey.from_public_bytes(pk_bytes)
        return True
    except Exception:
        return False


def _verify_sig(pk_b64: str, sig_b64: str, plain: bytes) -> bool:
    try:
        pk = Ed25519PublicKey.from_public_bytes(_b64d(pk_b64))
        pk.verify(_b64d(sig_b64), plain)
        return True
    except (InvalidSignature, ValueError, Exception):
        return False


def _canonical_json(obj) -> bytes:
    return json.dumps(obj, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")


def _pk_fp(pk_bytes: bytes) -> str:
    return _b64e(hashlib.sha256(pk_bytes).digest()[:8])


# ---------- 数据库 ----------

def _get_db() -> sqlite3.Connection:
    conn = sqlite3.connect(str(_DB_PATH), check_same_thread=False, timeout=30.0)
    conn.row_factory = sqlite3.Row
    try:
        conn.execute("PRAGMA journal_mode=WAL;")
        conn.execute("PRAGMA synchronous=NORMAL;")
    except sqlite3.Error:
        pass
    return conn


@contextmanager
def _db_session():
    """Open a database connection and always close it after the operation."""
    conn = _get_db()
    try:
        yield conn
    finally:
        conn.close()


def _init_db() -> None:
    with _LOCK, _db_session() as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS letters (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                pair_code   TEXT    NOT NULL,
                meta        TEXT    NOT NULL,
                content_b64 TEXT    NOT NULL,
                attach_b64  TEXT    NOT NULL,
                attach_ext  TEXT    NOT NULL,
                created_at  TEXT    NOT NULL
            )
        """)
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_pair_created ON letters(pair_code, created_at)"
        )
        conn.execute("""
            CREATE TABLE IF NOT EXISTS channels (
                channel_id   TEXT PRIMARY KEY NOT NULL,
                member_a_pk  TEXT NOT NULL,
                member_b_pk  TEXT NOT NULL,
                created_at   TEXT NOT NULL
            )
        """)
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_chan_a ON channels(member_a_pk)"
        )
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_chan_b ON channels(member_b_pk)"
        )
        conn.commit()


def _channel_members(channel_id: str) -> tuple[str, str] | None:
    """返回 (member_a_pk_b64, member_b_pk_b64)。"""
    if not _is_valid_pair(channel_id):
        return None
    with _db_session() as conn:
        row = conn.execute(
            "SELECT member_a_pk, member_b_pk FROM channels WHERE channel_id = ?",
            (channel_id,),
        ).fetchone()
        if not row:
            return None
        return row["member_a_pk"], row["member_b_pk"]


def _channel_resolve_pk(channel_id: str, pk_fp: str) -> str | None:
    """给定 fp 反查该 channel 下对应的完整 pk_b64，找不到返回 None。"""
    members = _channel_members(channel_id)
    if not members:
        return None
    for pkb64 in members:
        if _pk_fp(_b64d(pkb64)) == pk_fp:
            return pkb64
    return None


def _save_channel(channel_id: str, pk_a: str, pk_b: str) -> None:
    with _LOCK, _db_session() as conn:
        conn.execute(
            "INSERT OR IGNORE INTO channels(channel_id, member_a_pk, member_b_pk, created_at) "
            "VALUES (?, ?, ?, ?)",
            (channel_id, pk_a, pk_b, _now_iso()),
        )
        conn.commit()


# ---------- 配对 API ----------

def _pairing_expire_locked() -> None:
    now = time.time()
    to_del = [tok for tok, s in _PAIRING.items() if now - s["created_at"] > _PAIRING_TTL_SEC]
    for t in to_del:
        del _PAIRING[t]


def _clean_text(value) -> str | None:
    """Return stripped request text, or None when the field has a wrong type."""
    return value.strip() if isinstance(value, str) else None


@app.route("/api/pairing/declare", methods=["POST"])
def api_pairing_declare() -> tuple:
    data = request.get_json(silent=True)
    if not isinstance(data, dict):
        return jsonify({"ok": False, "message": "JSON body 必须是对象"}), 400
    token_raw = _clean_text(data.get("token"))
    role_raw = _clean_text(data.get("role"))
    pk_raw = _clean_text(data.get("pk_b64"))
    nickname_raw = data.get("nickname", "")
    nickname_raw = "" if nickname_raw is None else _clean_text(nickname_raw)
    if token_raw is None or role_raw is None or pk_raw is None or nickname_raw is None:
        return jsonify({"ok": False, "message": "字段类型非法"}), 400
    token = token_raw.upper()
    role = role_raw.lower()
    pk_b64 = pk_raw
    nickname = nickname_raw[:40]
    if len(token) != 6 or not re.fullmatch(r"[A-HJ-NP-Z2-9]{6}", token):
        return jsonify({"ok": False, "message": "token 格式必须是 6 位不含 I/L/0/O 的字母数字"}), 400
    if role not in ("host", "guest"):
        return jsonify({"ok": False, "message": "role 必须是 host 或 guest"}), 400
    if not _is_valid_pk_b64(pk_b64):
        return jsonify({"ok": False, "message": "非法公钥"}), 400

    with _PAIRING_LOCK:
        _pairing_expire_locked()
        state = _PAIRING.get(token)
        if state is None:
            state = {
                "host": None,
                "guest": None,
                "created_at": time.time(),
            }
            _PAIRING[token] = state
        slot = state.get(role)
        # 允许同角色同 pk 重复 declare（刷新 TTL 用），但不同 pk 抢同一 slot 拒绝
        if slot is not None and slot["pk_b64"] != pk_b64:
            return jsonify({
                "ok": False,
                "message": "该 token 已被另一个设备占用，请双方重新生成配对码。",
            }), 409
        nonce = secrets.token_urlsafe(12)
        state[role] = {
            "pk_b64": pk_b64,
            "nickname": nickname,
            "nonce": nonce,
            "confirmed": False,
        }
        # 每次 declare 刷新该 token 的 TTL（等价于重置到 now）
        state["created_at"] = time.time()
    return jsonify({"ok": True, "nonce": nonce}), 200


@app.route("/api/pairing/poll")
def api_pairing_poll() -> tuple:
    token = (request.args.get("token") or "").strip().upper()
    role = (request.args.get("role") or "").strip().lower()
    step = (request.args.get("step") or "wait_partner").strip()
    if len(token) != 6 or role not in ("host", "guest"):
        return jsonify({"ok": False, "message": "token/role 缺失或非法"}), 400
    with _PAIRING_LOCK:
        _pairing_expire_locked()
        state = _PAIRING.get(token)
        if state is None or state.get(role) is None:
            return jsonify({"ok": False, "message": "配对记录不存在（可能已过期）", "fatal": True}), 410
        partner_role = "guest" if role == "host" else "host"
        partner = state.get(partner_role)
        if step == "wait_partner":
            if partner is None:
                return jsonify({"ok": True, "partner_ready": False}), 200
            return jsonify({
                "ok": True,
                "partner_ready": True,
                "partner": {
                    "pk_b64": partner["pk_b64"],
                    "nickname": partner["nickname"],
                },
            }), 200
        if step == "both_confirmed":
            host = state.get("host") or {}
            guest = state.get("guest") or {}
            if not host.get("confirmed") or not guest.get("confirmed"):
                return jsonify({"ok": True, "both_confirmed": False}), 200
            # 双方都确认：计算 channel_id，写库，从 _PAIRING 移除
            a_pk, b_pk = host["pk_b64"], guest["pk_b64"]
            a_bytes, b_bytes = _b64d(a_pk), _b64d(b_pk)
            concat = a_bytes + b_bytes if a_bytes <= b_bytes else b_bytes + a_bytes
            channel_id = hashlib.sha256(concat).hexdigest()[:24]
            _save_channel(channel_id, a_pk, b_pk)
            _PAIRING.pop(token, None)
            return jsonify({
                "ok": True,
                "both_confirmed": True,
                "channel_id": channel_id,
            }), 200
        return jsonify({"ok": False, "message": "未知 step"}), 400


@app.route("/api/pairing/confirm", methods=["POST"])
def api_pairing_confirm() -> tuple:
    data = request.get_json(silent=True)
    if not isinstance(data, dict):
        return jsonify({"ok": False, "message": "JSON body 必须是对象"}), 400
    token_raw = _clean_text(data.get("token"))
    role_raw = _clean_text(data.get("role"))
    nonce_raw = _clean_text(data.get("my_nonce"))
    sig_raw = _clean_text(data.get("sig_b64"))
    if None in (token_raw, role_raw, nonce_raw, sig_raw):
        return jsonify({"ok": False, "message": "字段类型非法"}), 400
    token = token_raw.upper()
    role = role_raw.lower()
    my_nonce = nonce_raw
    sig_b64 = sig_raw
    safety_confirmed = data.get("safety_confirmed") is True
    if len(token) != 6 or role not in ("host", "guest"):
        return jsonify({"ok": False, "message": "token/role 非法"}), 400
    if not safety_confirmed:
        return jsonify({"ok": False, "message": "未确认安全码一致"}), 400
    with _PAIRING_LOCK:
        state = _PAIRING.get(token)
        if state is None:
            return jsonify({"ok": False, "message": "配对记录不存在或已过期", "fatal": True}), 410
        slot = state.get(role)
        if slot is None:
            return jsonify({"ok": False, "message": "请先 declare 再 confirm"}), 400
        if slot.get("nonce") != my_nonce:
            return jsonify({"ok": False, "message": "nonce 不匹配，请重新配对"}), 400
        # 对方 role 的 partner_pk_b64（用于签名原文构造）
        partner_role = "guest" if role == "host" else "host"
        partner_pk_b64 = ""
        if state.get(partner_role) is not None:
            partner_pk_b64 = state[partner_role]["pk_b64"]
        pk_b64 = slot["pk_b64"]
        plain = f"{role}|{token}|{my_nonce}|{partner_pk_b64}".encode("utf-8")
        if not _verify_sig(pk_b64, sig_b64, plain):
            return jsonify({"ok": False, "message": "确认签名校验失败"}), 403
        slot["confirmed"] = True
    return jsonify({"ok": True}), 200


# ---------- 旧接口 send / poll 的签名校验 + channel 支持 ----------

def _signing_digest(meta: dict, content_b64: str, attach_b64: str, attach_ext: str) -> bytes:
    """注意：客户端签名用的是「明文 content + att + meta(剔除 sig_*)」。
    服务端这里存的 b64 就是客户端上传的 b64，所以签名原文应与客户端 identity.sign_message 一致。
    但客户端传上来的 content_base64 是「已 base64 的 content」，对应客户端的 content.decode(base64) 后原内容；
    所以这里必须把 content_b64 解码后再拼哈希，才能和客户端的 sha256(canon_meta + utf8(content) + att_bytes + utf8(att_ext)) 对齐。
    """
    m = {k: v for k, v in meta.items() if k not in ("pk_fp", "sig_b64")}
    h = hashlib.sha256()
    h.update(_canonical_json(m))
    try:
        content_bytes = _b64d(content_b64) if content_b64 else b""
    except Exception:
        content_bytes = content_b64.encode("utf-8", errors="ignore")
    h.update(content_bytes)
    try:
        att_bytes = _b64d(attach_b64) if attach_b64 else b""
    except Exception:
        att_bytes = attach_b64.encode("utf-8", errors="ignore")
    h.update(att_bytes)
    h.update((attach_ext or "").encode("utf-8"))
    return h.digest()


def _resolve_and_verify_channel(
    channel_id: str,
    meta: dict,
    content_b64: str,
    attach_b64: str,
    attach_ext: str,
) -> tuple[bool, str]:
    """用 channel_id + meta.pk_fp + meta.sig_b64 做签名校验。
    返回 (是否通过, 说明)。
    """
    if not isinstance(meta, dict):
        return False, "meta 不是 dict"
    pk_fp = meta.get("pk_fp") or ""
    sig_b64 = meta.get("sig_b64") or ""
    if not pk_fp or not sig_b64:
        return False, "缺少 pk_fp/sig_b64（新的身份系统已启用，请先完成配对向导）"
    member_pk = _channel_resolve_pk(channel_id, pk_fp)
    if not member_pk:
        return False, "该 channel_id 下找不到此发送方（请双方先完成配对向导，或走旧 pair_code 模式）"
    digest = _signing_digest(meta, content_b64, attach_b64, attach_ext)
    if not _verify_sig(member_pk, sig_b64, digest):
        return False, "签名校验失败，消息被拒绝"
    return True, "ok"


@app.route("/health")
def health() -> tuple:
    return jsonify({"ok": True, "time": _now_iso()}), 200


@app.route("/")
def index() -> tuple:
    with _db_session() as conn:
        total = conn.execute("SELECT COUNT(*) AS n FROM letters").fetchone()["n"]
        pairs = conn.execute(
            "SELECT pair_code, COUNT(*) AS n FROM letters GROUP BY pair_code"
        ).fetchall()
        chans = conn.execute("SELECT COUNT(*) AS n FROM channels").fetchone()["n"]
    return jsonify({
        "service": "CoupleSuite 云中转 (公钥身份版本)",
        "total_letters": total,
        "paired_channels": chans,
        "pairs": [dict(p) for p in pairs],
        "time": _now_iso(),
    }), 200


@app.route("/api/send", methods=["POST"])
def api_send() -> tuple:
    data = request.get_json(silent=True)
    if not isinstance(data, dict):
        return jsonify({"ok": False, "error": "invalid JSON body"}), 400
    pair_value = data.get("pair_code", "")
    channel_value = data.get("channel_id", "")
    pair_code = "" if pair_value is None else _clean_text(pair_value)
    channel_id = "" if channel_value is None else _clean_text(channel_value)
    if pair_code is None or channel_id is None:
        return jsonify({"ok": False, "error": "pair_code/channel_id 类型非法"}), 400
    if not pair_code and not channel_id:
        return jsonify({"ok": False, "error": "missing pair_code 或 channel_id"}), 400

    meta = data.get("meta")
    if not isinstance(meta, dict):
        return jsonify({"ok": False, "error": "meta 必须是对象"}), 400
    content_b64 = data.get("content_base64") or ""
    attach_b64 = data.get("attachment_base64") or ""
    attach_ext = data.get("attachment_ext") or ""
    if not isinstance(content_b64, str) or not isinstance(attach_b64, str) \
            or not isinstance(attach_ext, str):
        return jsonify({"ok": False, "error": "invalid field type"}), 400
    if len(attach_b64) > _MAX_ATTACH_B64_LEN:
        return jsonify({"ok": False, "error": "attachment too large"}), 413
    if len(content_b64) > _MAX_CONTENT_B64_LEN:
        return jsonify({"ok": False, "error": "content too large"}), 413
    if len(attach_ext) > _MAX_ATTACH_EXT_LEN:
        return jsonify({"ok": False, "error": "attachment_ext too long"}), 400
    meta_str = _dumps(meta)
    if len(meta_str.encode("utf-8")) > _MAX_META_B64_LEN:
        return jsonify({"ok": False, "error": "meta too large"}), 413

    # ------- 路由：channel_id 模式 vs legacy pair_code 模式 -------
    bucket_key: str
    if channel_id:
        if not _is_valid_pair(channel_id):
            return jsonify({"ok": False, "error": "非法 channel_id 格式"}), 400
        ok, msg = _resolve_and_verify_channel(channel_id, meta, content_b64, attach_b64, attach_ext)
        if not ok:
            return jsonify({"ok": False, "error": f"channel 校验失败：{msg}"}), 403
        bucket_key = channel_id
    else:
        # legacy 路径：仍然保留 pair_code 模式（过渡期），不做签名，只是 pair_code 基本校验
        if not _is_valid_pair(pair_code):
            return jsonify({
                "ok": False,
                "error": f"invalid pair_code (len {_MIN_PAIR_LEN}-{_MAX_PAIR_LEN}, "
                         f"only letters/digits/-/_)",
            }), 400
        bucket_key = pair_code

    with _LOCK, _db_session() as conn:
        conn.execute(
            "INSERT INTO letters(pair_code, meta, content_b64, attach_b64, attach_ext, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (bucket_key, meta_str, content_b64, attach_b64, attach_ext, _now_iso()),
        )
        conn.commit()
    return jsonify({"ok": True}), 200


@app.route("/api/poll")
def api_poll() -> tuple:
    pair_code = (request.args.get("pair_code") or "").strip()
    channel_id = (request.args.get("channel_id") or "").strip()
    pk_fp = (request.args.get("pk_fp") or "").strip()
    sig_b64 = (request.args.get("sig_b64") or "").strip()
    if not pair_code and not channel_id:
        return jsonify({"ok": False, "error": "missing pair_code 或 channel_id"}), 400

    bucket_key: str
    if channel_id:
        if not _is_valid_pair(channel_id):
            return jsonify({"ok": False, "error": "非法 channel_id 格式"}), 400
        if not pk_fp or not sig_b64:
            return jsonify({
                "ok": False,
                "error": "channel 模式必须附带 pk_fp + sig_b64 签名参数证明你是该通道成员之一",
            }), 401
        member_pk = _channel_resolve_pk(channel_id, pk_fp)
        if not member_pk:
            return jsonify({
                "ok": False,
                "error": "该 channel_id 下找不到你这个发送方（请双方先完成配对向导，或走旧 pair_code 模式）",
            }), 403
        # 签名原文：poll_auth|channel_id|pk_fp|since
        since = (request.args.get("since") or "").strip()
        plain = f"poll_auth|{channel_id}|{pk_fp}|{since}".encode("utf-8")
        if not _verify_sig(member_pk, sig_b64, plain):
            return jsonify({"ok": False, "error": "poll 签名校验失败"}), 403
        bucket_key = channel_id
    else:
        if not _is_valid_pair(pair_code):
            return jsonify({
                "ok": False,
                "error": f"invalid pair_code (len {_MIN_PAIR_LEN}-{_MAX_PAIR_LEN}, "
                         f"only letters/digits/-/_)",
            }), 400
        bucket_key = pair_code

    since = (request.args.get("since") or "").strip()
    if since and not _is_valid_since(since):
        since = ""

    # Bound the query to a timestamp captured before opening the DB snapshot.
    # Messages arriving after this point must be left for the next poll.
    poll_until = _now_iso()
    with _db_session() as conn:
        if since:
            rows = conn.execute(
                "SELECT meta, content_b64, attach_b64, attach_ext, created_at "
                "FROM letters WHERE pair_code = ? AND created_at > ? "
                "AND created_at <= ? "
                "ORDER BY created_at ASC LIMIT ?",
                (bucket_key, since, poll_until, _POLL_BATCH_LIMIT + 1),
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT meta, content_b64, attach_b64, attach_ext, created_at "
                "FROM letters WHERE pair_code = ? AND created_at <= ? "
                "ORDER BY created_at ASC LIMIT ?",
                (bucket_key, poll_until, _POLL_BATCH_LIMIT + 1),
            ).fetchall()

    has_more = len(rows) > _POLL_BATCH_LIMIT
    if has_more:
        rows = rows[:_POLL_BATCH_LIMIT]

    letters = []
    # Never advance beyond the snapshot. With no rows, returning poll_until is
    # safe because rows created after it are excluded from this query.
    server_ts = poll_until
    for r in rows:
        letters.append({
            "meta": _loads(r["meta"]),
            "content_base64": r["content_b64"],
            "attachment_base64": r["attach_b64"],
            "attachment_ext": r["attach_ext"],
        })
        if r["created_at"] > server_ts:
            server_ts = r["created_at"]
    result = {"server_ts": server_ts, "letters": letters}
    if has_more:
        result["has_more"] = True
    return jsonify(result), 200


# ---------- 清理线程 ----------

def _cleanup_loop() -> None:
    while True:
        time.sleep(_CLEANUP_INTERVAL_SEC)
        # 1. 信件：30 天过期
        cutoff = (datetime.utcnow() - timedelta(days=_RETENTION_DAYS)).isoformat(timespec="microseconds")
        try:
            with _LOCK, _db_session() as conn:
                deleted = 0
                while True:
                    cur = conn.execute(
                        "DELETE FROM letters WHERE id IN ("
                        "  SELECT id FROM letters WHERE created_at < ? LIMIT 500"
                        ")",
                        (cutoff,),
                    )
                    conn.commit()
                    if cur.rowcount <= 0:
                        break
                    deleted += cur.rowcount
                if deleted:
                    print(f"[cleanup] removed {deleted} letters before {cutoff}", flush=True)
        except Exception:
            import traceback
            traceback.print_exc()
        # 2. 配对态：10 分钟
        try:
            with _PAIRING_LOCK:
                _pairing_expire_locked()
        except Exception:
            pass


# ---------- 工具 ----------

def _now_iso() -> str:
    # 微秒精度:增量拉取用 created_at > since,秒级精度会漏掉同一秒内的信件
    return datetime.utcnow().isoformat(timespec="microseconds")


def _dumps(obj) -> str:
    return json.dumps(obj, ensure_ascii=False)


def _loads(s: str):
    try:
        return json.loads(s)
    except (json.JSONDecodeError, TypeError):
        return {}


# ---------- 启动 ----------

_init_db()
threading.Thread(target=_cleanup_loop, daemon=True).start()


if __name__ == "__main__":
    print("中转服务器启动: http://127.0.0.1:5000")
    print("健康检查: http://127.0.0.1:5000/health")
    print("公钥身份通道说明：先 /api/pairing/declare→poll→confirm 配对，"
          "然后 /api/send 和 /api/poll 走 channel_id 模式")
    print("生产部署请用: gunicorn -w 4 -b 0.0.0.0:5000 relay_server:app")
    app.run(host="0.0.0.0", port=5000, debug=False)
