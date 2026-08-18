import tempfile
import unittest
from pathlib import Path

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


if __name__ == "__main__":
    unittest.main()
