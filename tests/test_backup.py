import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest.mock import patch

import backup
from backup import _safe_extract_all


class BackupExtractionTests(unittest.TestCase):
    def test_export_and_restore_cover_all_persistent_directories(self):
        directory_names = ("CONFIG_DIR", "DATA_DIR", "IMAGES_DIR", "CHECKIN_DIR", "MOVIES_DIR", "TRAVEL_DIR")
        archive_names = ("config", "data", "images", "checkin", "movies", "travel")
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source_dirs = {name: root / name.lower() for name in directory_names}
            destination_dirs = {name: root / f"restored_{name.lower()}" for name in directory_names}
            patches = [patch.object(backup.app_paths, name, source_dirs[name]) for name in directory_names]
            with patches[0], patches[1], patches[2], patches[3], patches[4], patches[5]:
                for name, directory in source_dirs.items():
                    directory.mkdir(parents=True)
                    (directory / "marker.txt").write_text(name, encoding="utf-8")
                archive = root / "backup.zip"
                backup.export_backup(archive)
                with zipfile.ZipFile(archive) as zf:
                    self.assertEqual(
                        {f"{arcname}/marker.txt" for arcname in archive_names},
                        {name for name in zf.namelist() if name.endswith("/marker.txt")},
                    )

            restore_patches = [patch.object(backup.app_paths, name, destination_dirs[name]) for name in directory_names]
            with restore_patches[0], restore_patches[1], restore_patches[2], restore_patches[3], restore_patches[4], restore_patches[5], patch.object(backup.app_paths, "CACHE_DIR", root / "cache"):
                backup.restore_backup(archive)

            for name, directory in destination_dirs.items():
                self.assertEqual((directory / "marker.txt").read_text(encoding="utf-8"), name)

    def test_rejects_path_traversal(self):
        with tempfile.TemporaryDirectory() as tmp:
            archive = Path(tmp) / "unsafe.zip"
            dest = Path(tmp) / "dest"
            dest.mkdir()
            with zipfile.ZipFile(archive, "w") as zf:
                zf.writestr("../outside.txt", "blocked")

            with zipfile.ZipFile(archive) as zf:
                with self.assertRaises(ValueError):
                    _safe_extract_all(zf, dest)

            self.assertFalse((Path(tmp) / "outside.txt").exists())

    def test_rejects_duplicate_targets(self):
        with tempfile.TemporaryDirectory() as tmp:
            archive = Path(tmp) / "duplicate.zip"
            dest = Path(tmp) / "dest"
            dest.mkdir()
            with zipfile.ZipFile(archive, "w") as zf:
                zf.writestr("config.json", "first")
                zf.writestr("./config.json", "second")

            with zipfile.ZipFile(archive) as zf:
                with self.assertRaises(ValueError):
                    _safe_extract_all(zf, dest)

    def test_rejects_oversized_member_before_extracting(self):
        with tempfile.TemporaryDirectory() as tmp:
            archive = Path(tmp) / "large.zip"
            dest = Path(tmp) / "dest"
            dest.mkdir()
            with zipfile.ZipFile(archive, "w") as zf:
                zf.writestr("large.bin", b"x")

            with zipfile.ZipFile(archive) as zf:
                with patch.object(backup, "_MAX_BACKUP_MEMBER_BYTES", 0):
                    with self.assertRaises(ValueError):
                        _safe_extract_all(zf, dest)

    def test_restore_cleans_staging_directory_after_extract_failure(self):
        with tempfile.TemporaryDirectory() as tmp:
            archive = Path(tmp) / "unsafe.zip"
            cache_dir = Path(tmp) / "cache"
            cache_dir.mkdir()
            with zipfile.ZipFile(archive, "w") as zf:
                zf.writestr("../outside.txt", "blocked")

            with patch.object(backup.app_paths, "CACHE_DIR", cache_dir):
                with self.assertRaises(ValueError):
                    backup.restore_backup(archive)

            self.assertFalse((cache_dir / "_restore_tmp").exists())

    def test_export_writes_parent_and_preserves_existing_archive_on_failure(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            target = root / "nested" / "backup.zip"
            with patch.object(backup, "_add_dir_to_zip", side_effect=OSError("disk full")):
                with self.assertRaises(OSError):
                    backup.export_backup(target)

            self.assertFalse(target.exists())
            self.assertEqual(len(list(target.parent.glob(".backup.zip.*.tmp"))), 1)
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(b"old archive")
            with patch.object(backup, "_add_dir_to_zip", side_effect=OSError("disk full")):
                with self.assertRaises(OSError):
                    backup.export_backup(target)
            self.assertEqual(target.read_bytes(), b"old archive")
            self.assertEqual(len(list(target.parent.glob(".backup.zip.*.tmp"))), 1)


if __name__ == "__main__":
    unittest.main()
