import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from MovieBoard import scraper


class _Response:
    def __init__(self, chunks):
        self._chunks = iter(chunks)

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def read(self, size):
        return next(self._chunks, b"")


class MovieScraperTests(unittest.TestCase):
    def test_download_poster_writes_cache_atomically(self):
        with tempfile.TemporaryDirectory() as tmp:
            original_dir = scraper.app_paths.MOVIES_DIR
            scraper.app_paths.MOVIES_DIR = Path(tmp)
            try:
                with patch.object(
                    scraper.urllib.request,
                    "urlopen",
                    return_value=_Response([b"poster"]),
                ), patch.object(
                    scraper,
                    "atomic_write_bytes",
                    wraps=scraper.atomic_write_bytes,
                ) as write:
                    result = scraper.download_poster("https://example.test/p", "42")

                path = Path(result)
                self.assertEqual(path.read_bytes(), b"poster")
                write.assert_called_once_with(path, b"poster")
            finally:
                scraper.app_paths.MOVIES_DIR = original_dir

    def test_oversized_poster_does_not_replace_existing_cache(self):
        with tempfile.TemporaryDirectory() as tmp:
            original_dir = scraper.app_paths.MOVIES_DIR
            scraper.app_paths.MOVIES_DIR = Path(tmp)
            path = Path(tmp) / "posters" / "42.jpg"
            path.parent.mkdir(parents=True)
            path.write_bytes(b"old poster")
            try:
                with patch.object(
                    scraper.urllib.request,
                    "urlopen",
                    return_value=_Response([b"x" * (scraper.MAX_ATTACHMENT_BYTES + 1)]),
                ):
                    self.assertIsNone(
                        scraper.download_poster("https://example.test/p", "42")
                    )
                self.assertEqual(path.read_bytes(), b"old poster")
            finally:
                scraper.app_paths.MOVIES_DIR = original_dir


if __name__ == "__main__":
    unittest.main()
