import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest.mock import patch

import backup
from backup import _safe_extract_all


class BackupExtractionTests(unittest.TestCase):
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


if __name__ == "__main__":
    unittest.main()
