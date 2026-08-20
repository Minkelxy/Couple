import tempfile
import unittest
from datetime import datetime
from pathlib import Path
from unittest.mock import patch

from DesktopMailbox import letter_store
from common_utils import AtomicJsonStore


class LetterStorePersistenceTests(unittest.TestCase):
    def test_message_id_makes_repeated_delivery_idempotent(self):
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
                ):
                    first = letter_store.write_letter(
                        author="A",
                        recipient="B",
                        title="Title",
                        content="Content",
                        deliver_at=datetime.now(),
                        message_id="message-1",
                    )
                    second = letter_store.write_letter(
                        author="A",
                        recipient="B",
                        title="Title",
                        content="Content",
                        deliver_at=datetime.now(),
                        message_id="message-1",
                    )

                self.assertEqual(second["id"], first["id"])
                self.assertEqual(len(letter_store._load_meta()), 1)
            finally:
                letter_store._LETTERS_DIR = original_dir
                letter_store._META_STORE = original_store

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

    def test_queries_ignore_malformed_metadata_records(self):
        with tempfile.TemporaryDirectory() as tmp:
            original_store = letter_store._META_STORE
            letter_store._META_STORE = AtomicJsonStore(Path(tmp) / "mailbox.json", [])
            valid_id = "a" * 12
            try:
                letter_store._META_STORE.save([
                    {
                        "id": valid_id,
                        "deliver_at": datetime.now().isoformat(timespec="minutes"),
                        "created_at": "not-a-date",
                        "read": False,
                        "title": "valid",
                    },
                    {"id": "bad", "deliver_at": "not-a-date", "read": False},
                    {"id": "../escape", "deliver_at": "2026-01-01T00:00", "read": False},
                    {"id": "b" * 12, "deliver_at": "2099-01-01T00:00", "read": "yes"},
                ])

                listed = letter_store.list_letters()
                self.assertEqual([item["id"] for item in listed], [valid_id])
                self.assertEqual(listed[0]["created_at"], listed[0]["deliver_at"] + ":00")
                self.assertEqual(
                    [item["id"] for item in letter_store.list_due_unread()], [valid_id]
                )
                letter_store.mark_read(valid_id)
                letter_store.delete_letter(valid_id)
                self.assertEqual(letter_store.list_letters(), [])
            finally:
                letter_store._META_STORE = original_store

    def test_metadata_failure_cleans_up_newly_written_files(self):
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
                    letter_store, "_save_meta", side_effect=OSError("read-only")
                ):
                    with self.assertRaises(OSError):
                        letter_store.write_letter(
                            author="A",
                            recipient="B",
                            title="Title",
                            content="Content",
                            deliver_at=datetime.now(),
                            attachment_bytes=b"attachment",
                            attachment_ext=".bin",
                        )
                self.assertEqual(list(letter_store._LETTERS_DIR.iterdir()), [])
            finally:
                letter_store._LETTERS_DIR = original_dir
                letter_store._META_STORE = original_store


if __name__ == "__main__":
    unittest.main()
