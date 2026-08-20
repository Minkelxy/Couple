import tempfile
import unittest
from pathlib import Path

from DesktopMailbox import config
from common_utils import AtomicJsonStore


class MailboxConfigTests(unittest.TestCase):
    def test_load_normalizes_sync_settings_from_damaged_config(self):
        with tempfile.TemporaryDirectory() as tmp:
            original_store = config._STORE
            config._STORE = AtomicJsonStore(Path(tmp) / "mailbox.json", {})
            try:
                config._STORE.save({
                    "sync_enabled": "false",
                    "sync_mode": "invalid",
                    "peer_host": 1920,
                    "cloud_server": None,
                    "cloud_pair_code": ["unexpected"],
                })

                loaded = config.load()

                self.assertFalse(loaded["sync_enabled"])
                self.assertEqual(loaded["sync_mode"], "lan")
                self.assertEqual(loaded["peer_host"], "")
                self.assertEqual(loaded["cloud_server"], "")
                self.assertEqual(loaded["cloud_pair_code"], "")
            finally:
                config._STORE = original_store

    def test_load_recovers_invalid_numeric_settings(self):
        with tempfile.TemporaryDirectory() as tmp:
            original_store = config._STORE
            config._STORE = AtomicJsonStore(Path(tmp) / "mailbox.json", {})
            try:
                config._STORE.save({
                    "check_interval_sec": "invalid",
                    "peer_port": 70000,
                    "sync_port": 0,
                    "cloud_poll_interval_sec": None,
                })

                loaded = config.load()

                self.assertEqual(loaded["check_interval_sec"], 30)
                self.assertEqual(loaded["peer_port"], 65535)
                self.assertEqual(loaded["sync_port"], 1)
                self.assertEqual(loaded["cloud_poll_interval_sec"], 30)
            finally:
                config._STORE = original_store

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

    def test_update_persists_normalized_sync_settings(self):
        with tempfile.TemporaryDirectory() as tmp:
            original_store = config._STORE
            config._STORE = AtomicJsonStore(Path(tmp) / "mailbox.json", {})
            try:
                updated = config.update(sync_enabled="yes", sync_mode="bad", cloud_server=42)

                self.assertFalse(updated["sync_enabled"])
                self.assertEqual(updated["sync_mode"], "lan")
                self.assertEqual(updated["cloud_server"], "")
                self.assertFalse(config._STORE.load()["sync_enabled"])
            finally:
                config._STORE = original_store

    def test_load_normalizes_anniversary_records(self):
        with tempfile.TemporaryDirectory() as tmp:
            original_store = config._STORE
            config._STORE = AtomicJsonStore(Path(tmp) / "mailbox.json", {})
            try:
                config._STORE.save({
                    "my_name": 123,
                    "anniversaries": [
                        {"date": "02-30", "title": "bad"},
                        {"date": "08-20", "id": None, "title": 42,
                         "content": None, "deliver_hour": 99},
                        "invalid",
                    ],
                })

                loaded = config.load()

                self.assertEqual(loaded["my_name"], "我")
                self.assertEqual(loaded["anniversaries"], [{
                    "date": "08-20",
                    "id": "08-20",
                    "title": "纪念日",
                    "content": "",
                    "deliver_hour": 23,
                }])
            finally:
                config._STORE = original_store


if __name__ == "__main__":
    unittest.main()
