import base64
from concurrent.futures import ThreadPoolExecutor
import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

import relay_server


class RelayPollingTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls._legacy_setting = relay_server.app.config["ALLOW_LEGACY_PAIR_CODE"]
        relay_server.app.config["ALLOW_LEGACY_PAIR_CODE"] = True

    @classmethod
    def tearDownClass(cls):
        relay_server.app.config["ALLOW_LEGACY_PAIR_CODE"] = cls._legacy_setting

    def test_legacy_pair_code_is_disabled_by_default(self):
        relay_server.app.config["ALLOW_LEGACY_PAIR_CODE"] = False
        try:
            response = relay_server.app.test_client().get(
                "/api/poll?pair_code=test-pair"
            )
            self.assertEqual(response.status_code, 410)
        finally:
            relay_server.app.config["ALLOW_LEGACY_PAIR_CODE"] = True

    def test_health_reports_database_readiness(self):
        client = relay_server.app.test_client()

        healthy = client.get("/health")
        self.assertEqual(healthy.status_code, 200)
        self.assertEqual(healthy.get_json()["db"], "ok")

        with patch.object(
            relay_server,
            "_get_db",
            side_effect=sqlite3.OperationalError("database unavailable"),
        ):
            unhealthy = client.get("/health")
        self.assertEqual(unhealthy.status_code, 503)
        self.assertFalse(unhealthy.get_json()["ok"])

    def test_pairing_endpoints_reject_non_object_json(self):
        client = relay_server.app.test_client()

        declared = client.post("/api/pairing/declare", json=["invalid"])
        confirmed = client.post("/api/pairing/confirm", json="invalid")

        self.assertEqual(declared.status_code, 400)
        self.assertEqual(confirmed.status_code, 400)

    def test_pairing_endpoints_reject_wrong_field_types(self):
        client = relay_server.app.test_client()

        declared = client.post(
            "/api/pairing/declare",
            json={"token": [], "role": "host", "pk_b64": "", "nickname": ""},
        )
        confirmed = client.post(
            "/api/pairing/confirm",
            json={
                "token": "ABC234",
                "role": "host",
                "my_nonce": "nonce",
                "sig_b64": "sig",
                "safety_confirmed": "true",
            },
        )

        self.assertEqual(declared.status_code, 400)
        self.assertEqual(confirmed.status_code, 400)

    def test_pairing_state_survives_process_memory_reset(self):
        with tempfile.TemporaryDirectory() as tmp:
            original_db_path = relay_server._DB_PATH
            original_pairing = relay_server._PAIRING.copy()
            relay_server._DB_PATH = Path(tmp) / "letters.db"
            relay_server._PAIRING.clear()
            try:
                relay_server._init_db()
                public_key = Ed25519PrivateKey.generate().public_key().public_bytes_raw()
                pk_b64 = base64.urlsafe_b64encode(public_key).rstrip(b"=").decode("ascii")
                client = relay_server.app.test_client()

                declared = client.post(
                    "/api/pairing/declare",
                    json={
                        "token": "ABC234",
                        "role": "host",
                        "pk_b64": pk_b64,
                        "nickname": "Windows A",
                    },
                )
                self.assertEqual(declared.status_code, 200)

                relay_server._PAIRING.clear()
                polled = client.get(
                    "/api/pairing/poll",
                    query_string={
                        "token": "ABC234",
                        "role": "host",
                        "step": "wait_partner",
                    },
                )
                self.assertEqual(polled.status_code, 200)
                self.assertFalse(polled.get_json()["partner_ready"])
            finally:
                relay_server._DB_PATH = original_db_path
                relay_server._PAIRING.clear()
                relay_server._PAIRING.update(original_pairing)

    def test_pairing_role_claim_is_atomic_across_threads(self):
        with tempfile.TemporaryDirectory() as tmp:
            original_db_path = relay_server._DB_PATH
            relay_server._DB_PATH = Path(tmp) / "letters.db"
            try:
                relay_server._init_db()
                keys = [Ed25519PrivateKey.generate() for _ in range(6)]
                public_keys = [
                    base64.urlsafe_b64encode(
                        key.public_key().public_bytes_raw()
                    ).rstrip(b"=").decode("ascii")
                    for key in keys
                ]
                with ThreadPoolExecutor(max_workers=6) as pool:
                    results = list(pool.map(
                        lambda pk: relay_server._declare_pairing(
                            "ABC234", "host", pk, "client"
                        ),
                        public_keys,
                    ))
                self.assertEqual(sum(1 for nonce, conflict in results if nonce), 1)
                self.assertEqual(sum(1 for nonce, conflict in results if conflict), 5)
            finally:
                relay_server._DB_PATH = original_db_path

    def test_send_rejects_non_string_bucket_fields(self):
        client = relay_server.app.test_client()

        response = client.post(
            "/api/send",
            json={
                "pair_code": [],
                "meta": {},
                "content_base64": "",
                "attachment_base64": "",
                "attachment_ext": "",
            },
        )

        self.assertEqual(response.status_code, 400)

    def test_send_rejects_non_object_meta(self):
        client = relay_server.app.test_client()

        response = client.post(
            "/api/send",
            json={
                "pair_code": "test-pair",
                "meta": [],
                "content_base64": "",
                "attachment_base64": "",
                "attachment_ext": "",
            },
        )

        self.assertEqual(response.status_code, 400)

    def test_send_rejects_invalid_base64_payload(self):
        client = relay_server.app.test_client()

        response = client.post(
            "/api/send",
            json={
                "pair_code": "test-pair",
                "meta": {},
                "content_base64": "not-base64",
                "attachment_base64": "",
                "attachment_ext": "",
            },
        )

        self.assertEqual(response.status_code, 400)

    def test_retried_message_id_is_stored_only_once(self):
        with tempfile.TemporaryDirectory() as tmp:
            original_db_path = relay_server._DB_PATH
            relay_server._DB_PATH = Path(tmp) / "letters.db"
            try:
                relay_server._init_db()
                client = relay_server.app.test_client()
                payload = {
                    "pair_code": "retry-test",
                    "meta": {"type": "letter", "message_id": "message-1"},
                    "content_base64": "aGVsbG8=",
                    "attachment_base64": "",
                    "attachment_ext": "",
                }
                self.assertEqual(client.post("/api/send", json=payload).status_code, 200)
                self.assertEqual(client.post("/api/send", json=payload).status_code, 200)
                polled = client.get("/api/poll?pair_code=retry-test")
                self.assertEqual(polled.status_code, 200)
                self.assertEqual(len(polled.get_json()["letters"]), 1)
            finally:
                relay_server._DB_PATH = original_db_path

    def test_messages_created_after_empty_poll_are_not_skipped(self):
        with tempfile.TemporaryDirectory() as tmp:
            original_db_path = relay_server._DB_PATH
            relay_server._DB_PATH = Path(tmp) / "letters.db"
            try:
                relay_server._init_db()
                client = relay_server.app.test_client()

                with patch.object(
                    relay_server,
                    "_now_iso",
                    return_value="2026-08-18T10:00:00.000000",
                ):
                    empty = client.get("/api/poll?pair_code=test-pair")

                self.assertEqual(empty.status_code, 200)
                cursor = empty.get_json()["server_ts"]

                with patch.object(
                    relay_server,
                    "_now_iso",
                    return_value="2026-08-18T10:01:30.000000",
                ):
                    sent = client.post(
                        "/api/send",
                        json={
                            "pair_code": "test-pair",
                            "meta": {"type": "letter"},
                            "content_base64": "aGVsbG8=",
                            "attachment_base64": "",
                            "attachment_ext": "",
                        },
                    )

                self.assertEqual(sent.status_code, 200)
                with patch.object(
                    relay_server,
                    "_now_iso",
                    return_value="2026-08-18T10:02:00.000000",
                ):
                    received = client.get(
                        "/api/poll",
                        query_string={"pair_code": "test-pair", "since": cursor},
                    )
                self.assertEqual(received.status_code, 200)
                self.assertEqual(len(received.get_json()["letters"]), 1)
            finally:
                relay_server._DB_PATH = original_db_path

    def test_cursor_paginates_more_than_one_batch_without_skipping(self):
        with tempfile.TemporaryDirectory() as tmp:
            original_db_path = relay_server._DB_PATH
            relay_server._DB_PATH = Path(tmp) / "letters.db"
            try:
                relay_server._init_db()
                client = relay_server.app.test_client()
                for index in range(1001):
                    response = client.post(
                        "/api/send",
                        json={
                            "pair_code": "batch-test",
                            "meta": {"type": "letter", "index": index},
                            "content_base64": "aA==",
                            "attachment_base64": "",
                            "attachment_ext": "",
                        },
                    )
                    self.assertEqual(response.status_code, 200)

                cursor = "0"
                indexes = []
                while True:
                    response = client.get(
                        "/api/poll",
                        query_string={"pair_code": "batch-test", "cursor": cursor},
                    )
                    self.assertEqual(response.status_code, 200)
                    payload = response.get_json()
                    indexes.extend(item["meta"]["index"] for item in payload["letters"])
                    next_cursor = payload["server_cursor"]
                    if next_cursor == cursor and not payload.get("has_more"):
                        break
                    cursor = next_cursor

                self.assertEqual(indexes, list(range(1001)))
            finally:
                relay_server._DB_PATH = original_db_path


if __name__ == "__main__":
    unittest.main()
