"""云中转服务器：在两台不在同一局域网的电脑间转发信件。

接口（与 DesktopMailbox/cloud_sync.py 对应）：
  POST /api/send   — 发送一封信
  GET  /api/poll   — 增量拉取新信件
  GET  /health     — 健康检查
  GET  /            — 简单状态页

存储：SQLite（letters.db，自动建表，WAL 模式支持多 worker）
清理：后台线程每 6 小时清理 30 天以上的信件（分批）。

运行：
  开发：python relay_server.py
  生产：gunicorn -w 2 -b 0.0.0.0:5000 relay_server:app
        （不建议超过 2 worker，SQLite 多 worker 并发仍受限，WAL 可减轻）

安全建议：
  - 配对码就是身份验证，双方共用同一码
  - 生产环境务必配置 HTTPS（nginx 反向代理 + Let's Encrypt）
  - 信件正文/附件在客户端已 base64 编码，但服务器明文存储，请勿在公共服务器长期保留
"""
from __future__ import annotations

import json
import re
import sqlite3
import threading
import time
from datetime import datetime, timedelta
from pathlib import Path

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

# pair_code 白名单：字母、数字、下划线、短横线（用作后续若扩展为文件名也安全）
_PAIR_RE = re.compile(r"^[A-Za-z0-9_\-]+$")
# ISO 8601 since 基本校验：YYYY-MM-DDTHH:MM:SS(.ffffff)?  长度 20~33
# （不要求精确匹配格式，只是拒绝明显乱码/超长/奇怪字符导致 SQLite 字符串比较拖慢索引）
_SINCE_RE = re.compile(r"^[0-9T:.\-]{16,64}$")


def _is_valid_pair(pair_code: str) -> bool:
    if not _MIN_PAIR_LEN <= len(pair_code) <= _MAX_PAIR_LEN:
        return False
    return _PAIR_RE.match(pair_code) is not None


def _is_valid_since(since: str) -> bool:
    if len(since) > _MAX_SINCE_LEN:
        return False
    return _SINCE_RE.match(since) is not None


# ---------- 数据库 ----------

def _get_db() -> sqlite3.Connection:
    conn = sqlite3.connect(str(_DB_PATH), check_same_thread=False, timeout=30.0)
    conn.row_factory = sqlite3.Row
    # WAL：多 worker gunicorn 并发不再 database is locked（减轻，仍建议 worker<=2）
    try:
        conn.execute("PRAGMA journal_mode=WAL;")
        conn.execute("PRAGMA synchronous=NORMAL;")
    except sqlite3.Error:
        pass
    return conn


def _init_db() -> None:
    with _LOCK, _get_db() as conn:
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
        conn.commit()


# ---------- 接口 ----------

@app.route("/health")
def health() -> tuple:
    return jsonify({"ok": True, "time": _now_iso()}), 200


@app.route("/")
def index() -> tuple:
    with _get_db() as conn:
        total = conn.execute("SELECT COUNT(*) AS n FROM letters").fetchone()["n"]
        pairs = conn.execute(
            "SELECT pair_code, COUNT(*) AS n FROM letters GROUP BY pair_code"
        ).fetchall()
    return jsonify({
        "service": "桌面相册云中转",
        "total_letters": total,
        "pairs": [dict(p) for p in pairs],
        "time": _now_iso(),
    }), 200


@app.route("/api/send", methods=["POST"])
def api_send() -> tuple:
    data = request.get_json(silent=True)
    if not isinstance(data, dict):
        return jsonify({"ok": False, "error": "invalid JSON body"}), 400
    pair_code = (data.get("pair_code") or "").strip()
    if not pair_code:
        return jsonify({"ok": False, "error": "missing pair_code"}), 400
    if not _is_valid_pair(pair_code):
        return jsonify({
            "ok": False,
            "error": f"invalid pair_code (len {_MIN_PAIR_LEN}-{_MAX_PAIR_LEN}, "
                     f"only letters/digits/-/_)",
        }), 400

    meta = data.get("meta")
    if not isinstance(meta, dict):
        # 兼容旧版本客户端 meta 缺省
        meta = {}
    content_b64 = data.get("content_base64") or ""
    attach_b64 = data.get("attachment_base64") or ""
    attach_ext = data.get("attachment_ext") or ""

    # 类型校验
    if not isinstance(content_b64, str) or not isinstance(attach_b64, str) \
            or not isinstance(attach_ext, str):
        return jsonify({"ok": False, "error": "invalid field type"}), 400

    # 防御：限制附件大小，防止恶意大包撑爆存储/内存
    if len(attach_b64) > _MAX_ATTACH_B64_LEN:
        return jsonify({"ok": False, "error": "attachment too large"}), 413
    # 正文也限制（文本，2MB 足够）
    if len(content_b64) > _MAX_CONTENT_B64_LEN:
        return jsonify({"ok": False, "error": "content too large"}), 413
    # meta 序列化后大小限制（避免超长 JSON 元数据）
    meta_str = _dumps(meta)
    if len(meta_str.encode("utf-8")) > _MAX_META_B64_LEN:
        return jsonify({"ok": False, "error": "meta too large"}), 413
    # attach_ext 长度限制
    if len(attach_ext) > _MAX_ATTACH_EXT_LEN:
        return jsonify({"ok": False, "error": "attachment_ext too long"}), 400

    with _LOCK, _get_db() as conn:
        conn.execute(
            "INSERT INTO letters(pair_code, meta, content_b64, attach_b64, attach_ext, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (
                pair_code,
                meta_str,
                content_b64,
                attach_b64,
                attach_ext,
                _now_iso(),
            ),
        )
        conn.commit()
    return jsonify({"ok": True}), 200


@app.route("/api/poll")
def api_poll() -> tuple:
    pair_code = (request.args.get("pair_code") or "").strip()
    if not pair_code:
        return jsonify({"ok": False, "error": "missing pair_code"}), 400
    if not _is_valid_pair(pair_code):
        return jsonify({
            "ok": False,
            "error": f"invalid pair_code (len {_MIN_PAIR_LEN}-{_MAX_PAIR_LEN}, "
                     f"only letters/digits/-/_)",
        }), 400
    since = (request.args.get("since") or "").strip()
    if since and not _is_valid_since(since):
        # since 格式不对：直接 since 置空返回前 1000 封，让客户端下次从新 server_ts 继续
        since = ""

    with _get_db() as conn:
        if since:
            rows = conn.execute(
                "SELECT meta, content_b64, attach_b64, attach_ext, created_at "
                "FROM letters WHERE pair_code = ? AND created_at > ? "
                "ORDER BY created_at ASC LIMIT ?",
                (pair_code, since, _POLL_BATCH_LIMIT + 1),
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT meta, content_b64, attach_b64, attach_ext, created_at "
                "FROM letters WHERE pair_code = ? "
                "ORDER BY created_at ASC LIMIT ?",
                (pair_code, _POLL_BATCH_LIMIT + 1),
            ).fetchall()

    has_more = len(rows) > _POLL_BATCH_LIMIT
    if has_more:
        rows = rows[:_POLL_BATCH_LIMIT]

    letters = []
    server_ts = _now_iso()
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
        cutoff = (datetime.utcnow() - timedelta(days=_RETENTION_DAYS)).isoformat(timespec="microseconds")
        try:
            with _LOCK, _get_db() as conn:
                # 分批删除：每次 500 条，避免长期持锁阻塞其他请求
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
                    print(f"[cleanup] removed {deleted} letters before {cutoff}",
                          flush=True)
        except Exception:
            # 单个清理异常不退出整个 daemon 线程，下一轮继续
            import traceback
            traceback.print_exc()


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
    # 开发模式：直接运行
    print("中转服务器启动: http://127.0.0.1:5000")
    print("健康检查: http://127.0.0.1:5000/health")
    print("生产部署请用: gunicorn -w 4 -b 0.0.0.0:5000 relay_server:app")
    app.run(host="0.0.0.0", port=5000, debug=False)
