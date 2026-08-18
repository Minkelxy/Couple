import tempfile
import unittest
from pathlib import Path

from DesktopMailbox import config
from common_utils import AtomicJsonStore


class MailboxConfigTests(unittest.TestCase):
    def test_update_preserves_defaults_and_does_not_share_lists(self):
        with tempfile.TemporaryDirectory() as tmp:
            original_store = config._STORE
            config._STORE = AtomicJsonStore(Path(tmp) / "mailbox.json", {})
            try:
                updated = config.update(my_name="Alice")
                self.assertEqual(updated["my_name"], "Alice")
                self.assertTrue(updated["anniversaries"])

                loaded = config.load()
                loaded["anniversaries"].clear()
                self.assertTrue(config.load()["anniversaries"])
            finally:
                config._STORE = original_store


if __name__ == "__main__":
    unittest.main()
