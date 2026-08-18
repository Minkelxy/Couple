import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import relay_server


class RelayPollingTests(unittest.TestCase):
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


if __name__ == "__main__":
    unittest.main()
