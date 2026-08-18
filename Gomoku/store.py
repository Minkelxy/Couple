"""五子棋对局历史持久化：JSON 文件存储。

每局保存为 GOMOKU_DIR/<game_id>.json：
{id, winner, moves:[{row,col,color}], moves_count, played_at}
"""
from __future__ import annotations

import json
import os
import re
import uuid
from datetime import datetime
from pathlib import Path

import app_paths
from common_utils import AtomicJsonStore, log_warning

GOMOKU_DIR = app_paths.DATA_DIR / "gomoku"
_SAFE_ID = re.compile(r"[A-Za-z0-9_-]+\Z")


def _ensure_dir() -> None:
    GOMOKU_DIR.mkdir(parents=True, exist_ok=True)


def _now_iso() -> str:
    return datetime.now().isoformat(timespec="seconds")


def _path_for(identifier: str, suffix: str) -> Path:
    if not isinstance(identifier, str) or not _SAFE_ID.fullmatch(identifier):
        raise ValueError("invalid gomoku identifier")
    return GOMOKU_DIR / f"{identifier}{suffix}"


def save_game(winner: str, moves: list[dict], played_at: str) -> str:
    """保存一局对局，返回 game_id。

    moves: [{"row":int, "col":int, "color":"black"/"white"}, ...]
    """
    _ensure_dir()
    game_id = uuid.uuid4().hex[:12]
    record = {
        "id": game_id,
        "winner": winner,
        "moves": moves,
        "moves_count": len(moves),
        "played_at": played_at,
    }
    path = _path_for(game_id, ".json")
    AtomicJsonStore(path, default={}).save(record)
    return game_id


def append_move(session_id: str, move_dict: dict) -> None:
    """以 JSONL 追加写方式记录单手棋，供断线重连回放。

    move_dict 含 {session_id, color, row, col, ts, source}。
    """
    _ensure_dir()
    path = _path_for(session_id, ".jsonl")
    with path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(move_dict, ensure_ascii=False) + "\n")
        f.flush()
        os.fsync(f.fileno())


def load_moves(session_id: str) -> list[dict]:
    """读取会话的 JSONL 棋谱，逐行解析返回 move 列表。

    文件不存在返回 []；损坏行跳过并记日志。
    """
    try:
        path = _path_for(session_id, ".jsonl")
    except ValueError:
        return []
    if not path.exists():
        return []
    moves: list[dict] = []
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError as e:
        log_warning("读取棋谱失败 %s: %s", session_id, e)
        return []
    for line in lines:
        line = line.strip()
        if not line:
            continue
        try:
            moves.append(json.loads(line))
        except json.JSONDecodeError as e:
            log_warning("跳过损坏的棋谱行 %s: %s", session_id, e)
            continue
    return moves


def list_games() -> list[dict]:
    """列出所有对局，按 played_at 降序。"""
    _ensure_dir()
    result: list[dict] = []
    for p in GOMOKU_DIR.glob("*.json"):
        try:
            rec = AtomicJsonStore(p, default={}).load()
        except OSError as e:
            log_warning("跳过损坏的对局记录 %s: %s", p.name, e)
            continue
        if not isinstance(rec, dict):
            log_warning("跳过格式错误的对局记录 %s", p.name)
            continue
        result.append({
            "id": rec.get("id", p.stem),
            "winner": rec.get("winner", ""),
            "moves_count": rec.get("moves_count", len(rec.get("moves", []))),
            "played_at": rec.get("played_at", ""),
        })
    result.sort(key=lambda r: r.get("played_at", ""), reverse=True)
    return result


def get_game(game_id: str) -> dict | None:
    """获取完整对局记录。"""
    try:
        path = _path_for(game_id, ".json")
    except ValueError:
        return None
    if not path.exists():
        return None
    record = AtomicJsonStore(path, default={}).load()
    return record if isinstance(record, dict) else None
