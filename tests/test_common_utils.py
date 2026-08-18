import tempfile
import threading
import unittest
from pathlib import Path

from common_utils import AtomicJsonStore


class AtomicJsonStoreTests(unittest.TestCase):
    def test_missing_default_is_not_shared_with_callers(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = AtomicJsonStore(Path(tmp) / "state.json", {"items": []})

            first = store.load()
            first["items"].append("local mutation")

            self.assertEqual(store.load(), {"items": []})

    def test_distinct_instances_do_not_lose_updates(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "state.json"
            first = AtomicJsonStore(path, {})
            second = AtomicJsonStore(path, {})
            barrier = threading.Barrier(2)

            def update(store, key):
                barrier.wait()
                store.update(**{key: True})

            threads = [
                threading.Thread(target=update, args=(first, "first")),
                threading.Thread(target=update, args=(second, "second")),
            ]
            for thread in threads:
                thread.start()
            for thread in threads:
                thread.join()

            self.assertEqual(first.load(), {"first": True, "second": True})

    def test_failed_write_does_not_replace_previous_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "state.json"
            store = AtomicJsonStore(path, {})
            store.save({"version": 1})

            with self.assertRaises(TypeError):
                store.save({"invalid": object()})

            self.assertEqual(store.load(), {"version": 1})


if __name__ == "__main__":
    unittest.main()
