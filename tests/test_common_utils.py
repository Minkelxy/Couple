import tempfile
import threading
import unittest
from pathlib import Path
from unittest import mock

from common_utils import AtomicJsonStore, atomic_copy_file, atomic_write_bytes


class AtomicJsonStoreTests(unittest.TestCase):
    def test_atomic_write_bytes_round_trips(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "secret.bin"
            atomic_write_bytes(path, b"encrypted payload")

            self.assertEqual(path.read_bytes(), b"encrypted payload")

    def test_atomic_copy_file_preserves_existing_target_on_failure(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = root / "source.bin"
            target = root / "target.bin"
            source.write_bytes(b"new payload")
            target.write_bytes(b"old payload")
            atomic_copy_file(source, target)
            self.assertEqual(target.read_bytes(), b"new payload")
            target.write_bytes(b"old payload")

            with mock.patch("common_utils.shutil.copy2", side_effect=OSError("disk full")):
                with self.assertRaises(OSError):
                    atomic_copy_file(source, target)

            self.assertEqual(target.read_bytes(), b"old payload")
            self.assertEqual(list(root.glob(".target.bin.*.tmp")), [])

    def test_missing_default_is_not_shared_with_callers(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = AtomicJsonStore(Path(tmp) / "state.json", {"items": []})

            first = store.load()
            first["items"].append("local mutation")

            self.assertEqual(store.load(), {"items": []})

    def test_invalid_utf8_returns_default(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "state.json"
            path.write_bytes(b"{\xff\xfe")
            store = AtomicJsonStore(path, {"fallback": True})

            self.assertEqual(store.load(), {"fallback": True})

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
