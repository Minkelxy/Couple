import tempfile
import unittest
from pathlib import Path

from DesktopMailbox import crypto


class CryptoKeyPersistenceTests(unittest.TestCase):
    def test_key_creation_is_atomic_and_reused(self):
        with tempfile.TemporaryDirectory() as tmp:
            original_path = crypto._KEY_PATH
            original_fernet = crypto._fernet
            crypto._KEY_PATH = Path(tmp) / "key.key"
            crypto._fernet = None
            try:
                first = crypto._load_or_create_key()
                second = crypto._load_or_create_key()

                self.assertEqual(first, second)
                self.assertEqual(crypto._KEY_PATH.read_bytes(), first)
            finally:
                crypto._KEY_PATH = original_path
                crypto._fernet = original_fernet


if __name__ == "__main__":
    unittest.main()
