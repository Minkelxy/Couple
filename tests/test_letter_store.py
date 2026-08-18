import tempfile
import unittest
from datetime import datetime
from pathlib import Path
from unittest.mock import patch

from DesktopMailbox import letter_store
from common_utils import AtomicJsonStore


class LetterStorePersistenceTests(unittest.TestCase):
    def test_write_letter_atomically_persists_metadata_and_encrypted_files(self):
        with tempfile.TemporaryDirectory() as tmp:
            original_dir = letter_store._LETTERS_DIR
            original_store = letter_store._META_STORE
            letter_store._LETTERS_DIR = Path(tmp) / "letters"
            letter_store._META_STORE = AtomicJsonStore(Path(tmp) / "mailbox.json", [])
            try:
                with patch.object(
                    letter_store.crypto,
                    "encrypt",
                    side_effect=lambda data: b"enc:" + data,
                ), patch.object(
                    letter_store.crypto,
                    "decrypt",
                    side_effect=lambda data: data[4:],
                ):
                    meta = letter_store.write_letter(
                        author="A",
                        recipient="B",
                        title="Title",
                        content="Content",
                        deliver_at=datetime.now(),
                        attachment_bytes=b"attachment",
                        attachment_ext=".bin",
                    )

                    self.assertEqual(letter_store.read_content(meta["id"]), "Content")
                    self.assertEqual(letter_store.read_attachment(meta["id"]), b"attachment")
                    self.assertEqual(len(letter_store._load_meta()), 1)
            finally:
                letter_store._LETTERS_DIR = original_dir
                letter_store._META_STORE = original_store


if __name__ == "__main__":
    unittest.main()
