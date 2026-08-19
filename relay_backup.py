"""Create consistent SQLite backups for the Ubuntu relay service."""
from __future__ import annotations

import os
import sqlite3
import tempfile
import argparse
from contextlib import closing
from datetime import datetime, timezone
from pathlib import Path


DEFAULT_DB_PATH = Path(
    os.environ.get("COUPLE_RELAY_DB", "/var/lib/couple-relay/letters.db")
).expanduser()
DEFAULT_BACKUP_DIR = Path(
    os.environ.get("COUPLE_RELAY_BACKUP_DIR", "/var/backups/couple-relay")
).expanduser()
BACKUP_RETENTION_COUNT = 14


def _assert_integrity(conn: sqlite3.Connection) -> None:
    result = conn.execute("PRAGMA integrity_check").fetchone()
    if not result or result[0] != "ok":
        detail = result[0] if result else "no result"
        raise sqlite3.DatabaseError(f"SQLite integrity check failed: {detail}")


def backup_database(
    db_path: Path = DEFAULT_DB_PATH,
    backup_dir: Path = DEFAULT_BACKUP_DIR,
    now: datetime | None = None,
) -> Path:
    """Atomically create a consistent backup and remove old backup files."""
    db_path = Path(db_path)
    backup_dir = Path(backup_dir)
    if not db_path.exists():
        raise FileNotFoundError(db_path)
    backup_dir.mkdir(parents=True, exist_ok=True)
    current = now or datetime.now(timezone.utc)
    stamp = current.strftime("%Y%m%d-%H%M%S")
    target = backup_dir / f"letters-{stamp}.db"
    fd, tmp_name = tempfile.mkstemp(
        prefix=f".{target.name}.", suffix=".tmp", dir=backup_dir
    )
    os.close(fd)
    try:
        with closing(sqlite3.connect(str(db_path))) as source, closing(
            sqlite3.connect(tmp_name)
        ) as dest:
            _assert_integrity(source)
            source.backup(dest)
            dest.commit()
            _assert_integrity(dest)
        os.chmod(tmp_name, 0o600)
        os.replace(tmp_name, target)
    finally:
        try:
            os.unlink(tmp_name)
        except FileNotFoundError:
            pass

    backups = sorted(
        backup_dir.glob("letters-*.db"),
        key=lambda path: path.stat().st_mtime,
        reverse=True,
    )
    for old in backups[BACKUP_RETENTION_COUNT:]:
        try:
            old.unlink()
        except OSError:
            pass
    return target


def restore_database(backup_path: Path, db_path: Path) -> Path:
    """Restore a verified backup into db_path using an atomic replacement.

    The relay service must be stopped before calling this function so no live
    connection can recreate WAL sidecar files after the replacement.
    """
    backup_path = Path(backup_path)
    db_path = Path(db_path)
    if not backup_path.exists():
        raise FileNotFoundError(backup_path)
    db_path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(
        prefix=f".{db_path.name}.", suffix=".restore.tmp", dir=db_path.parent
    )
    os.close(fd)
    try:
        with closing(sqlite3.connect(str(backup_path))) as source, closing(
            sqlite3.connect(tmp_name)
        ) as dest:
            _assert_integrity(source)
            source.backup(dest)
            dest.commit()
            _assert_integrity(dest)
        os.chmod(tmp_name, 0o600)
        os.replace(tmp_name, db_path)
        for suffix in ("-wal", "-shm"):
            try:
                (Path(f"{db_path}{suffix}")).unlink()
            except FileNotFoundError:
                pass
    finally:
        try:
            os.unlink(tmp_name)
        except FileNotFoundError:
            pass
    return db_path


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("backup", "restore"), nargs="?", default="backup")
    parser.add_argument("backup_path", nargs="?", type=Path)
    parser.add_argument("--db", dest="db_path", type=Path, default=DEFAULT_DB_PATH)
    args = parser.parse_args()
    if args.command == "backup":
        print(backup_database(args.db_path))
    elif args.backup_path is None:
        parser.error("restore requires BACKUP_PATH")
    else:
        print(restore_database(args.backup_path, args.db_path))
