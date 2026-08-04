"""五子棋对局历史持久化：JSON 文件存储。

每局保存为 GOMOKU_DIR/<game_id>.json：
{id, winner, moves:[{row,col,color}], moves_count, played_at}
"""
from __future__ import annotations

import json
import uuid
from datetime import datetime
from pathlib import Path

import app_paths
from common_utils import log_warning

GOMOKU_DIR = app_paths.DATA_DIR / "gomoku"


def _ensure_dir() -> None:
    GOMOKU_DIR.mkdir(parents=True, exist_ok=True)


def _now_iso() -> str:
    return datetime.now().isoformat(timespec="seconds")


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
    path = GOMOKU_DIR / f"{game_id}.json"
    path.write_text(
        json.dumps(record, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return game_id


def list_games() -> list[dict]:
    """列出所有对局，按 played_at 降序。"""
    _ensure_dir()
    result: list[dict] = []
    for p in GOMOKU_DIR.glob("*.json"):
        try:
            rec = json.loads(p.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError) as e:
            log_warning("跳过损坏的对局记录 %s: %s", p.name, e)
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
    path = GOMOKU_DIR / f"{game_id}.json"
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError) as e:
        log_warning("读取对局记录失败 %s: %s", game_id, e)
        return None
