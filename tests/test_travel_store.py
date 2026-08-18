import tempfile
import unittest
from pathlib import Path

from common_utils import AtomicJsonStore
from TravelMap import store


class TravelStoreTests(unittest.TestCase):
    def test_load_uses_atomic_store_and_normalizes_records(self):
        with tempfile.TemporaryDirectory() as tmp:
            original_store = store._store
            store._store = AtomicJsonStore(Path(tmp) / "cities.json", [])
            try:
                store._store.save([{"city_name": "Suzhou"}, "invalid"])

                self.assertEqual(
                    store._load(),
                    [{"city_name": "Suzhou", "source": "self"}],
                )
            finally:
                store._store = original_store

    def test_load_returns_empty_list_for_non_list_data(self):
        with tempfile.TemporaryDirectory() as tmp:
            original_store = store._store
            store._store = AtomicJsonStore(Path(tmp) / "cities.json", [])
            try:
                store._store.save({"city_name": "Suzhou"})

                self.assertEqual(store._load(), [])
            finally:
                store._store = original_store


if __name__ == "__main__":
    unittest.main()
