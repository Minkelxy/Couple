import sqlite3
import tempfile
import unittest
from contextlib import closing
from datetime import datetime, timezone
from pathlib import Path

from relay_backup import backup_database


class RelayBackupTests(unittest.TestCase):
    def test_backup_uses_sqlite_online_backup_and_is_readable(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            db_path = root / "letters.db"
            backup_dir = root / "backups"
            with closing(sqlite3.connect(db_path)) as conn:
                conn.execute("CREATE TABLE letters (id INTEGER PRIMARY KEY, body TEXT)")
                conn.execute("INSERT INTO letters(body) VALUES ('hello')")
                conn.commit()

            backup = backup_database(
                db_path,
                backup_dir,
                datetime(2026, 8, 19, 3, 15, tzinfo=timezone.utc),
            )

            with closing(sqlite3.connect(backup)) as conn:
                self.assertEqual(conn.execute("SELECT body FROM letters").fetchone()[0], "hello")
            self.assertEqual(list(backup_dir.glob("*.tmp")), [])

    def test_backup_retention_keeps_latest_fourteen_files(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            db_path = root / "letters.db"
            backup_dir = root / "backups"
            with closing(sqlite3.connect(db_path)) as conn:
                conn.execute("CREATE TABLE letters (id INTEGER PRIMARY KEY)")
                conn.commit()

            for day in range(15):
                backup_database(
                    db_path,
                    backup_dir,
                    datetime(2026, 8, 1 + day, tzinfo=timezone.utc),
                )

            self.assertEqual(len(list(backup_dir.glob("letters-*.db"))), 14)


if __name__ == "__main__":
    unittest.main()
