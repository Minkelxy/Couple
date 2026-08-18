import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

import identity
from common_utils import AtomicJsonStore


class IdentityPersistenceTests(unittest.TestCase):
    def test_save_partner_uses_atomic_json_store(self):
        my_key = Ed25519PrivateKey.generate()
        partner_key = Ed25519PrivateKey.generate()
        my_pk = my_key.public_key().public_bytes_raw()
        partner_pk = partner_key.public_key().public_bytes_raw()

        with tempfile.TemporaryDirectory() as tmp:
            original_path = identity._PARTNER_JSON
            original_store = identity._PARTNER_STORE
            identity._PARTNER_JSON = Path(tmp) / "partner.json"
            identity._PARTNER_STORE = AtomicJsonStore(identity._PARTNER_JSON, {})
            try:
                with patch.object(identity, "ensure_identity", return_value=(my_pk, my_key)):
                    status = identity.save_partner(identity._b64e(partner_pk), "Partner")

                self.assertTrue(status.paired)
                self.assertEqual(identity._PARTNER_STORE.load()["nickname"], "Partner")
            finally:
                identity._PARTNER_JSON = original_path
                identity._PARTNER_STORE = original_store


if __name__ == "__main__":
    unittest.main()
