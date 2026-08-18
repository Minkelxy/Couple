import tempfile
import unittest
from pathlib import Path

from common_utils import AtomicJsonStore
from DesktopPhotoFrame import config


class PhotoFrameConfigTests(unittest.TestCase):
    def test_load_uses_atomic_store_and_recovers_invalid_values(self):
        with tempfile.TemporaryDirectory() as tmp:
            original_store = config._store
            config._store = AtomicJsonStore(Path(tmp) / "photo_frame.json", {})
            try:
                config._store.save({
                    "interval_sec": "invalid",
                    "window_width": "invalid",
                    "window_height": None,
                })

                loaded = config.load()

                self.assertEqual(loaded["interval_sec"], 15)
                self.assertEqual(loaded["window_width"], 320)
                self.assertEqual(loaded["window_height"], 400)
            finally:
                config._store = original_store

    def test_load_does_not_share_nested_defaults(self):
        with tempfile.TemporaryDirectory() as tmp:
            original_store = config._store
            config._store = AtomicJsonStore(Path(tmp) / "photo_frame.json", {})
            try:
                first = config.load()
                first["albums"].append({"name": "Temporary", "path": "x"})
                first["favorites"].append("x")

                second = config.load()

                self.assertNotIn("x", second["favorites"])
                self.assertNotIn(
                    {"name": "Temporary", "path": "x"}, second["albums"]
                )
            finally:
                config._store = original_store

    def test_load_filters_malformed_album_entries(self):
        with tempfile.TemporaryDirectory() as tmp:
            original_store = config._store
            config._store = AtomicJsonStore(Path(tmp) / "photo_frame.json", {})
            try:
                config._store.save({
                    "albums": ["invalid", {"name": "No path"},
                               {"name": "Valid", "path": "C:/photos"}],
                    "partner_albums": [None, {"path": "C:/shared"}],
                })

                loaded = config.load()

                self.assertEqual(
                    loaded["albums"],
                    [
                        {"name": "Valid", "path": "C:/photos"},
                        {"name": config.DEFAULT_ALBUM_NAME,
                         "path": str(config.app_paths.IMAGES_DIR)},
                    ],
                )
                self.assertEqual(
                    loaded["partner_albums"], [{"path": "C:/shared"}]
                )
                config.add_album("Added", "C:/added")
            finally:
                config._store = original_store


if __name__ == "__main__":
    unittest.main()
