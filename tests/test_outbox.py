import tempfile
import time
import unittest
from pathlib import Path

from DesktopMailbox.outbox import OutboxStore


class OutboxStoreTests(unittest.TestCase):
    def test_failed_item_is_retained_with_backoff_and_success_removes_it(self):
        with tempfile.TemporaryDirectory() as tmp:
            outbox = OutboxStore(Path(tmp) / "outbox.json")
            item_id = outbox.enqueue(
                {"message_id": "message-1", "type": "letter"},
                "hello",
                b"bytes",
                ".bin",
            )
            self.assertEqual(len(outbox.due(now=time.time())), 1)

            outbox.retry(item_id)
            self.assertEqual(outbox.due(now=time.time()), [])
            self.assertEqual(outbox._load()[0]["attempts"], 1)

            outbox.remove(item_id)
            self.assertEqual(outbox._load(), [])


if __name__ == "__main__":
    unittest.main()
