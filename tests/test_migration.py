import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import migration


class MigrationTests(unittest.TestCase):
    def test_atomic_copy_does_not_replace_destination_when_copy_fails(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = root / "source.bin"
            destination = root / "destination.bin"
            source.write_bytes(b"new content")
            destination.write_bytes(b"old content")

            with patch.object(migration.shutil, "copy2", side_effect=OSError("disk full")):
                with self.assertRaises(OSError):
                    migration._copy_file_atomic(source, destination)

            self.assertEqual(destination.read_bytes(), b"old content")
            self.assertEqual(list(root.glob(".destination.bin.*")), [])

    def test_successful_migration_writes_marker_atomically(self):
        with tempfile.TemporaryDirectory() as tmp:
            marker = Path(tmp) / ".migrated"
            original_marker = migration._MIGRATED_MARKER
            migration._MIGRATED_MARKER = marker
            try:
                with patch.object(migration.app_paths, "ensure_dirs"), \
                        patch.object(migration, "_migrate_file"), \
                        patch.object(migration, "_migrate_tree"), \
                        patch.object(migration, "_migrate_images"), \
                        patch.object(migration, "_seed_default_album"), \
                        patch.object(migration, "atomic_write_bytes") as write:
                    self.assertTrue(migration.run_migration())

                write.assert_called_once()
                self.assertEqual(write.call_args.args[0], marker)
                self.assertEqual(write.call_args.args[1].decode("utf-8").count("T"), 1)
            finally:
                migration._MIGRATED_MARKER = original_marker

    def test_existing_marker_skips_migration(self):
        with tempfile.TemporaryDirectory() as tmp:
            marker = Path(tmp) / ".migrated"
            marker.write_text("done", encoding="utf-8")
            original_marker = migration._MIGRATED_MARKER
            migration._MIGRATED_MARKER = marker
            try:
                with patch.object(migration, "atomic_write_bytes") as write:
                    self.assertFalse(migration.run_migration())
                write.assert_not_called()
            finally:
                migration._MIGRATED_MARKER = original_marker


if __name__ == "__main__":
    unittest.main()
