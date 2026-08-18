import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from DesktopMailbox import sync


class SenderIdTests(unittest.TestCase):
    def test_new_sender_id_is_written_atomically(self):
        with tempfile.TemporaryDirectory() as tmp:
            cfg_dir = Path(tmp)
            with patch.object(sync, "atomic_write_bytes", wraps=sync.atomic_write_bytes) as write:
                sender_id = sync._ensure_uuid(cfg_dir)

            self.assertRegex(sender_id, r"^[0-9a-f]{16}$")
            self.assertEqual((cfg_dir / "sender_id.txt").read_text(), sender_id)
            write.assert_called_once_with(
                cfg_dir / "sender_id.txt", sender_id.encode("ascii")
            )

    def test_existing_sender_id_is_reused_without_writing(self):
        with tempfile.TemporaryDirectory() as tmp:
            cfg_dir = Path(tmp)
            path = cfg_dir / "sender_id.txt"
            path.write_text("existing-id", encoding="utf-8")
            with patch.object(sync, "atomic_write_bytes") as write:
                self.assertEqual(sync._ensure_uuid(cfg_dir), "existing-id")
            write.assert_not_called()


if __name__ == "__main__":
    unittest.main()
