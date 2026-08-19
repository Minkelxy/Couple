from concurrent.futures import ThreadPoolExecutor
import tempfile
import time
import unittest
from pathlib import Path

from DesktopMailbox.outbox import OutboxStore


class OutboxStoreTests(unittest.TestCase):
    def test_concurrent_enqueues_do_not_drop_items(self):
        with tempfile.TemporaryDirectory() as tmp:
            outbox = OutboxStore(Path(tmp) / "outbox.json")
            with ThreadPoolExecutor(max_workers=8) as pool:
                ids = list(pool.map(
                    lambda index: outbox.enqueue(
                        {"message_id": f"message-{index}"},
                        str(index),
                        b"",
                        "",
                    ),
                    range(40),
                ))

            self.assertEqual(len(ids), 40)
            self.assertEqual(
                {item["id"] for item in outbox._load()},
                {f"message-{index}" for index in range(40)},
            )

    def test_corrupt_retry_fields_are_recovered(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "outbox.json"
            outbox = OutboxStore(path)
            outbox._store.save([{
                "id": "message-1",
                "meta": {},
                "content": "hello",
                "attachment_b64": "",
                "attachment_ext": "",
                "attempts": "bad",
                "next_retry_at": "bad",
            }])

            outbox.retry("message-1")
            item = outbox._load()[0]
            self.assertEqual(item["attempts"], 1)
            self.assertGreater(item["next_retry_at"], time.time())

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
