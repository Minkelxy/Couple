"""影视记录数据层：SQLite 存储。

表 movies：id / title / douban_id / status / poster_path / intro /
rating_mine / rating_partner / review_mine / review_partner / added_at。
状态枚举：want（想看）、watching（在看）、watched（看完）。
"""
from __future__ import annotations

import json
import sqlite3
from contextlib import contextmanager
from datetime import datetime
from typing import Optional

import app_paths
from common_utils import AtomicJsonStore, log_warning

DB_PATH = app_paths.MOVIES_DIR / "movies.db"

STATUS_WANT = "want"
STATUS_WATCHING = "watching"
STATUS_WATCHED = "watched"

# who -> 列名，白名单避免 SQL 注入
_RATING_COLS = {"mine": "rating_mine", "partner": "rating_partner"}
_REVIEW_COLS = {"mine": "review_mine", "partner": "review_partner"}


def _now_iso() -> str:
    return datetime.now().isoformat(timespec="seconds")


@contextmanager
def _cursor():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


def init_db() -> None:
    """初始化表（幂等）。模块加载时自动调用。"""
    app_paths.MOVIES_DIR.mkdir(parents=True, exist_ok=True)
    with _cursor() as conn:
        conn.execute(
            """CREATE TABLE IF NOT EXISTS movies (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                title TEXT,
                douban_id TEXT,
                status TEXT,
                poster_path TEXT,
                intro TEXT,
                rating_mine INTEGER,
                rating_partner INTEGER,
                review_mine TEXT,
                review_partner TEXT,
                added_at TEXT
            )"""
        )


def add(
    title: str,
    douban_id: str = "",
    poster_path: str = "",
    intro: str = "",
) -> int:
    """添加到想看，返回新记录 id。"""
    with _cursor() as conn:
        cur = conn.execute(
            "INSERT INTO movies (title, douban_id, status, poster_path, intro, added_at) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (title, douban_id, STATUS_WANT, poster_path, intro, _now_iso()),
        )
        return int(cur.lastrowid)


def update_status(movie_id: int, status: str) -> None:
    with _cursor() as conn:
        conn.execute(
            "UPDATE movies SET status=? WHERE id=?", (status, movie_id)
        )


def update_rating(movie_id: int, who: str, rating: int) -> None:
    """who 为 'mine' 或 'partner'。非法值忽略。"""
    col = _RATING_COLS.get(who)
    if not col:
        return
    with _cursor() as conn:
        conn.execute(
            f"UPDATE movies SET {col}=? WHERE id=?", (int(rating), movie_id)
        )


def update_review(movie_id: int, who: str, review: str) -> None:
    """who 为 'mine' 或 'partner'。非法值忽略。"""
    col = _REVIEW_COLS.get(who)
    if not col:
        return
    with _cursor() as conn:
        conn.execute(
            f"UPDATE movies SET {col}=? WHERE id=?", (review, movie_id)
        )


def delete(movie_id: int) -> None:
    with _cursor() as conn:
        conn.execute("DELETE FROM movies WHERE id=?", (movie_id,))


def list_by_status(status: str) -> list[dict]:
    with _cursor() as conn:
        rows = conn.execute(
            "SELECT * FROM movies WHERE status=? ORDER BY added_at DESC",
            (status,),
        )
        return [dict(r) for r in rows.fetchall()]


def list_all() -> list[dict]:
    with _cursor() as conn:
        rows = conn.execute("SELECT * FROM movies ORDER BY added_at DESC")
        return [dict(r) for r in rows.fetchall()]


def get(movie_id: int) -> Optional[dict]:
    with _cursor() as conn:
        row = conn.execute(
            "SELECT * FROM movies WHERE id=?", (movie_id,)
        ).fetchone()
        return dict(row) if row else None


# 模块加载时自动建表
init_db()


# ===== 对方状态（partner_status）：独立 JSON 持久化 =====
# movie_id(str) -> {"status": "want"/"watching"/"watched"/None, "rating": int|None}
PARTNER_STATUS_FILE = app_paths.MOVIES_DIR / "partner_status.json"
# 对方状态原子写存储
_partner_status_store = AtomicJsonStore(PARTNER_STATUS_FILE, default={})


def _load_partner_status() -> dict:
    if not PARTNER_STATUS_FILE.exists():
        return {}
    try:
        return json.loads(PARTNER_STATUS_FILE.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError) as e:
        log_warning("影视对方状态加载失败，返回空: %s", e)
        return {}


def _save_partner_status(data: dict) -> None:
    _partner_status_store.save(data)


def set_partner_status(movie_id, status, rating) -> None:
    """记录对方对某影片的状态/评分。movie_id 统一转 str。"""
    mid = str(movie_id)
    data = _load_partner_status()
    data[mid] = {"status": status, "rating": rating}
    _save_partner_status(data)


def get_partner_status(movie_id) -> Optional[dict]:
    return _load_partner_status().get(str(movie_id))


def get_all_partner_status() -> dict:
    return _load_partner_status()
