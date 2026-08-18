"""打卡日历数据层：SQLite 存储打卡记录。"""
from __future__ import annotations

import sqlite3
from datetime import date, datetime, timedelta

import app_paths
from common_utils import AtomicJsonStore

DB_PATH = app_paths.CHECKIN_DIR / "checkin.db"
IMAGES_DIR = app_paths.CHECKIN_DIR / "images"
PARTNER_FILE = app_paths.CHECKIN_DIR / "partner_checkins.json"
PARTNER_IMAGES_DIR = app_paths.CHECKIN_DIR / "partner_images"
# 对方打卡记录原子写存储
_partner_store = AtomicJsonStore(PARTNER_FILE, default={})

# 5=最开心，1=最困
MOOD_MAP = {5: "😊", 4: "😍", 3: "😢", 2: "😡", 1: "😴"}


def _connect() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db() -> None:
    """初始化表结构。"""
    app_paths.CHECKIN_DIR.mkdir(parents=True, exist_ok=True)
    IMAGES_DIR.mkdir(parents=True, exist_ok=True)
    with _connect() as conn:
        conn.execute(
            """CREATE TABLE IF NOT EXISTS records (
                date TEXT PRIMARY KEY,
                mood INTEGER,
                text TEXT,
                image_path TEXT,
                created_at TEXT
            )"""
        )


def add_or_update(date_str: str, mood: int, text: str, image_path: str = "") -> None:
    """新增或更新指定日期的打卡记录。date 格式 YYYY-MM-DD。"""
    now = datetime.now().isoformat(timespec="seconds")
    with _connect() as conn:
        conn.execute(
            """INSERT INTO records (date, mood, text, image_path, created_at)
               VALUES (?, ?, ?, ?, ?)
               ON CONFLICT(date) DO UPDATE SET
                   mood=excluded.mood,
                   text=excluded.text,
                   image_path=excluded.image_path,
                   created_at=excluded.created_at""",
            (date_str, mood, text, image_path, now),
        )


def get_by_date(date_str: str) -> dict | None:
    """获取指定日期的打卡记录，无则 None。"""
    with _connect() as conn:
        row = conn.execute(
            "SELECT * FROM records WHERE date=?", (date_str,)
        ).fetchone()
    return dict(row) if row else None


def get_range(start_date: str, end_date: str) -> list[dict]:
    """获取日期区间内的记录（含起止），按日期升序。"""
    with _connect() as conn:
        rows = conn.execute(
            "SELECT * FROM records WHERE date>=? AND date<=? ORDER BY date ASC",
            (start_date, end_date),
        ).fetchall()
    return [dict(r) for r in rows]


def get_streak() -> int:
    """计算从今天往前的连续打卡天数。今天没打则从昨天开始算。"""
    today = date.today()
    with _connect() as conn:
        checked = {
            row["date"]
            for row in conn.execute("SELECT date FROM records").fetchall()
        }
    start = today
    if today.isoformat() not in checked:
        start = today - timedelta(days=1)
    streak = 0
    cur = start
    while cur.isoformat() in checked:
        streak += 1
        cur -= timedelta(days=1)
    return streak


def get_recent(days: int = 30) -> list[dict]:
    """获取最近 N 天的记录，按日期升序。"""
    today = date.today()
    start = today - timedelta(days=days - 1)
    return get_range(start.isoformat(), today.isoformat())


# ---------- 对方打卡记录（JSON 持久化） ----------


def _load_partner() -> dict:
    """读取对方打卡记录，返回 {date_str: record}。"""
    data = _partner_store.load()
    if not isinstance(data, dict):
        return {}
    return {
        key: value
        for key, value in data.items()
        if isinstance(key, str) and isinstance(value, dict)
    }


def _save_partner(data: dict) -> None:
    _partner_store.save(data)


def add_partner_record(date_str: str, mood: int, note: str,
                       image_path: str = "") -> None:
    """新增/更新对方指定日期的打卡记录。"""
    data = _load_partner()
    data[date_str] = {
        "date": date_str,
        "mood": mood,
        "note": note,
        "image_path": image_path,
        "created_at": datetime.now().isoformat(timespec="seconds"),
    }
    _save_partner(data)


def list_partner_records(days: int = 7) -> list[dict]:
    """获取对方最近 N 天的打卡记录，按日期降序（最新在前）。"""
    today = date.today()
    start = today - timedelta(days=days - 1)
    data = _load_partner()
    result = []
    for rec in data.values():
        try:
            d = date.fromisoformat(rec.get("date", ""))
        except (ValueError, TypeError):
            continue
        if start <= d <= today:
            result.append(rec)
    result.sort(key=lambda r: r.get("date", ""), reverse=True)
    return result


def get_partner_range(start_date: str, end_date: str) -> list[dict]:
    """获取对方在日期区间内的记录（含起止），按日期升序。"""
    data = _load_partner()
    result = [
        rec for rec in data.values()
        if isinstance(rec.get("date", ""), str)
        and start_date <= rec.get("date", "") <= end_date
    ]
    result.sort(key=lambda r: r.get("date", ""))
    return result

def get_partner_recent(days: int = 30) -> list[dict]:
    """获取对方最近 N 天的记录，按日期升序。"""
    today = date.today()
    start = today - timedelta(days=days - 1)
    return get_partner_range(start.isoformat(), today.isoformat())


init_db()
