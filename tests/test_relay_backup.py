import sqlite3
import tempfile
import unittest
from contextlib import closing
from datetime import datetime, timezone
from pathlib import Path

from relay_backup import backup_database, restore_database


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

    def test_backup_rejects_invalid_sqlite_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            db_path = root / "letters.db"
            db_path.write_bytes(b"not a sqlite database")

            with self.assertRaises(sqlite3.DatabaseError):
                backup_database(db_path, root / "backups")

    def test_restore_replaces_database_from_verified_backup(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = root / "source.db"
            target = root / "letters.db"
            with closing(sqlite3.connect(source)) as conn:
                conn.execute("CREATE TABLE letters (body TEXT)")
                conn.execute("INSERT INTO letters VALUES ('restored')")
                conn.commit()
            backup = backup_database(source, root / "backups")
            with closing(sqlite3.connect(target)) as conn:
                conn.execute("CREATE TABLE letters (body TEXT)")
                conn.execute("INSERT INTO letters VALUES ('old')")
                conn.commit()

            restore_database(backup, target)

            with closing(sqlite3.connect(target)) as conn:
                self.assertEqual(
                    conn.execute("SELECT body FROM letters").fetchone()[0],
                    "restored",
                )


if __name__ == "__main__":
    unittest.main()
