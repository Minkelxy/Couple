import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from common_utils import atomic_write_bytes
from DailyCheckin import checkin_window
from DesktopPhotoFrame import gallery_window
from TravelMap import map_window


class ReceivedImageTests(unittest.TestCase):
    def test_checkin_partner_image_uses_atomic_write(self):
        with tempfile.TemporaryDirectory() as tmp:
            original_dir = checkin_window.store.PARTNER_IMAGES_DIR
            checkin_window.store.PARTNER_IMAGES_DIR = Path(tmp)
            try:
                with patch.object(
                    checkin_window,
                    "atomic_write_bytes",
                    wraps=atomic_write_bytes,
                ) as write:
                    filename = checkin_window._save_partner_image(
                        b"image", ".jpg", "2026-08-18"
                    )

                path = Path(tmp) / filename
                self.assertEqual(path.read_bytes(), b"image")
                write.assert_called_once_with(path, b"image")
            finally:
                checkin_window.store.PARTNER_IMAGES_DIR = original_dir

    def test_travel_partner_image_uses_atomic_write(self):
        with tempfile.TemporaryDirectory() as tmp:
            original_dir = map_window.app_paths.TRAVEL_DIR
            map_window.app_paths.TRAVEL_DIR = Path(tmp)
            try:
                with patch.object(map_window.store, "add_partner_city") as add_city, \
                        patch.object(
                            map_window,
                            "atomic_write_bytes",
                            wraps=atomic_write_bytes,
                        ) as write:
                    map_window.handle_partner_event(
                        {"city": "Suzhou", "lat": 31.3, "lng": 120.6},
                        "",
                        b"image",
                        ".jpg",
                    )

                filename = add_city.call_args.args[4]
                path = Path(tmp) / filename
                self.assertEqual(path.read_bytes(), b"image")
                write.assert_called_once_with(path, b"image")
            finally:
                map_window.app_paths.TRAVEL_DIR = original_dir

    def test_photo_frame_partner_image_uses_atomic_write(self):
        with tempfile.TemporaryDirectory() as tmp:
            original_dir = gallery_window.app_paths.DATA_DIR
            gallery_window.app_paths.DATA_DIR = Path(tmp)
            try:
                with patch.object(
                    gallery_window.config, "add_partner_album_path"
                ) as add_album, patch.object(
                    gallery_window,
                    "atomic_write_bytes",
                    wraps=atomic_write_bytes,
                ) as write:
                    gallery_window.handle_partner_event(
                        {"filename": "shared.jpg"}, "", b"image", ".jpg"
                    )

                path = Path(tmp) / "shared_photos"
                files = list(path.iterdir())
                self.assertEqual(len(files), 1)
                self.assertEqual(files[0].read_bytes(), b"image")
                write.assert_called_once_with(files[0], b"image")
                add_album.assert_called_once_with(str(path))
            finally:
                gallery_window.app_paths.DATA_DIR = original_dir


if __name__ == "__main__":
    unittest.main()
