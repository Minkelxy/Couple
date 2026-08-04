"""云中转服务器：在两台不在同一局域网的电脑间转发信件。

接口（与 DesktopMailbox/cloud_sync.py 对应）：
  POST /api/send   — 发送一封信
  GET  /api/poll   — 增量拉取新信件
  GET  /health     — 健康检查
  GET  /            — 简单状态页

存储：SQLite（letters.db，自动建表）
清理：后台线程每 6 小时清理 30 天以上的已投递信件。

运行：
  开发：python relay_server.py
  生产：gunicorn -w 4 -b 0.0.0.0:5000 relay_server:app

安全建议：
  - 配对码就是身份验证，双方共用同一码
  - 生产环境务必配置 HTTPS（nginx 反向代理 + Let's Encrypt）
  - 信件正文/附件在客户端已 base64 编码，但服务器明文存储，请勿在公共服务器长期保留
"""
from __future__ import annotations

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


# ---------- 数据库 ----------

def _get_db() -> sqlite3.Connection:
    conn = sqlite3.connect(str(_DB_PATH), check_same_thread=False)
    conn.row_factory = sqlite3.Row
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
    data = request.get_json(silent=True) or {}
    pair_code = (data.get("pair_code") or "").strip()
    if not pair_code:
        return jsonify({"ok": False, "error": "missing pair_code"}), 400

    meta = data.get("meta") or {}
    content_b64 = data.get("content_base64") or ""
    attach_b64 = data.get("attachment_base64") or ""
    attach_ext = data.get("attachment_ext") or ""

    # 防御：限制附件大小，防止恶意大包撑爆存储/内存
    if len(attach_b64) > _MAX_ATTACH_B64_LEN:
        return jsonify({"ok": False, "error": "attachment too large"}), 413
    # 正文也限制（文本，1MB 足够）
    if len(content_b64) > 2 * 1024 * 1024:
        return jsonify({"ok": False, "error": "content too large"}), 413

    with _LOCK, _get_db() as conn:
        conn.execute(
            "INSERT INTO letters(pair_code, meta, content_b64, attach_b64, attach_ext, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (
                pair_code,
                _dumps(meta),
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
    since = (request.args.get("since") or "").strip()

    with _get_db() as conn:
        if since:
            rows = conn.execute(
                "SELECT meta, content_b64, attach_b64, attach_ext, created_at "
                "FROM letters WHERE pair_code = ? AND created_at > ? "
                "ORDER BY created_at ASC",
                (pair_code, since),
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT meta, content_b64, attach_b64, attach_ext, created_at "
                "FROM letters WHERE pair_code = ? "
                "ORDER BY created_at ASC",
                (pair_code,),
            ).fetchall()

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
    return jsonify({"server_ts": server_ts, "letters": letters}), 200


# ---------- 清理线程 ----------

def _cleanup_loop() -> None:
    while True:
        time.sleep(_CLEANUP_INTERVAL_SEC)
        cutoff = (datetime.utcnow() - timedelta(days=_RETENTION_DAYS)).isoformat()
        with _LOCK, _get_db() as conn:
            conn.execute("DELETE FROM letters WHERE created_at < ?", (cutoff,))
            conn.commit()


# ---------- 工具 ----------

def _now_iso() -> str:
    # 微秒精度:增量拉取用 created_at > since,秒级精度会漏掉同一秒内的信件
    return datetime.utcnow().isoformat(timespec="microseconds")


def _dumps(obj) -> str:
    import json
    return json.dumps(obj, ensure_ascii=False)


def _loads(s: str):
    import json
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
