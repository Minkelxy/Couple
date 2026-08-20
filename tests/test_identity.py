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

    def test_invalid_partner_records_are_treated_as_unpaired(self):
        my_key = Ed25519PrivateKey.generate()
        my_pk = my_key.public_key().public_bytes_raw()

        with tempfile.TemporaryDirectory() as tmp:
            original_path = identity._PARTNER_JSON
            original_store = identity._PARTNER_STORE
            identity._PARTNER_JSON = Path(tmp) / "partner.json"
            identity._PARTNER_STORE = AtomicJsonStore(identity._PARTNER_JSON, {})
            try:
                with patch.object(identity, "ensure_identity", return_value=(my_pk, my_key)):
                    for invalid in (["not-an-object"], {"pk_b64": []}, {"pk_b64": "bad"}):
                        identity._PARTNER_STORE.save(invalid)
                        status = identity.get_status()
                        self.assertFalse(status.paired)
            finally:
                identity._PARTNER_JSON = original_path
                identity._PARTNER_STORE = original_store

    def test_cached_private_key_must_match_public_key_file(self):
        cached_key = Ed25519PrivateKey.generate()
        restored_key = Ed25519PrivateKey.generate()

        with tempfile.TemporaryDirectory() as tmp:
            original_sk = identity._MY_SK_ENC
            original_pk = identity._MY_PK_JSON
            original_store = identity._MY_PK_STORE
            original_cached_sk = identity._cached_sk
            original_cached_status = identity._cached_status
            identity._MY_SK_ENC = Path(tmp) / "my_sk.enc"
            identity._MY_PK_JSON = Path(tmp) / "my_pk.json"
            identity._MY_PK_STORE = AtomicJsonStore(identity._MY_PK_JSON, {})
            identity._MY_SK_ENC.write_bytes(b"encrypted")
            identity._MY_PK_STORE.save({
                "pk_b64": identity._b64e(restored_key.public_key().public_bytes_raw()),
            })
            identity._cached_sk = cached_key
            try:
                with patch.object(
                    identity,
                    "_fernet_dec",
                    return_value=restored_key.private_bytes_raw(),
                ):
                    public_key, private_key = identity.ensure_identity()

                self.assertEqual(public_key, restored_key.public_key().public_bytes_raw())
                self.assertEqual(
                    private_key.public_key().public_bytes_raw(),
                    restored_key.public_key().public_bytes_raw(),
                )
            finally:
                identity._MY_SK_ENC = original_sk
                identity._MY_PK_JSON = original_pk
                identity._MY_PK_STORE = original_store
                identity._cached_sk = original_cached_sk
                identity._cached_status = original_cached_status


if __name__ == "__main__":
    unittest.main()
