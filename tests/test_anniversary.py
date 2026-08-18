import tempfile
import unittest
from datetime import datetime
from pathlib import Path
from unittest.mock import patch

from DesktopMailbox import anniversary
from common_utils import AtomicJsonStore


class AnniversaryLogTests(unittest.TestCase):
    def test_sent_log_uses_atomic_store_and_filters_invalid_entries(self):
        with tempfile.TemporaryDirectory() as tmp:
            original_store = anniversary._SENT_STORE
            anniversary._SENT_STORE = AtomicJsonStore(Path(tmp) / "sent.json", [])
            try:
                anniversary._SENT_STORE.save(["first", 42, None])
                self.assertEqual(anniversary._load_sent(), {"first"})

                anniversary._mark_sent("second")
                self.assertEqual(anniversary._load_sent(), {"first", "second"})
            finally:
                anniversary._SENT_STORE = original_store

    def test_failed_delivery_is_retried_before_marking_sent(self):
        with tempfile.TemporaryDirectory() as tmp:
            original_store = anniversary._SENT_STORE
            anniversary._SENT_STORE = AtomicJsonStore(Path(tmp) / "sent.json", [])
            today = datetime.now()
            cfg = {
                "my_name": "A",
                "their_name": "B",
                "anniversaries": [{
                    "id": "test",
                    "date": today.strftime("%m-%d"),
                    "title": "Title",
                    "content": "Content",
                    "deliver_hour": today.hour,
                }],
            }
            try:
                with patch.object(anniversary.config, "load", return_value=cfg), patch.object(
                    anniversary.letter_store,
                    "write_letter",
                    side_effect=[RuntimeError("disk full"), {"id": "letter-1"}],
                ) as write_letter:
                    self.assertEqual(anniversary.check_and_deliver(), [])
                    self.assertEqual(anniversary._load_sent(), set())

                    self.assertEqual(
                        anniversary.check_and_deliver(), [{"id": "letter-1"}]
                    )
                    self.assertEqual(write_letter.call_count, 2)
                    self.assertEqual(len(anniversary._load_sent()), 2)
            finally:
                anniversary._SENT_STORE = original_store


if __name__ == "__main__":
    unittest.main()
