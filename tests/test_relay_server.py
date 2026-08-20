import base64
import json
from concurrent.futures import ThreadPoolExecutor
import hashlib
import sqlite3
import tempfile
import time
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import Mock, patch

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

        fake_conn = Mock()
        fake_conn.execute.return_value.fetchone.return_value = ("database disk image is malformed",)
        with patch.object(relay_server, "_db_session") as db_session:
            db_session.return_value.__enter__.return_value = fake_conn
            corrupt = client.get("/health")
        self.assertEqual(corrupt.status_code, 503)
        self.assertEqual(corrupt.get_json()["db"], "corrupt")

    def test_database_indexes_cover_cursor_and_cleanup_queries(self):
        with tempfile.TemporaryDirectory() as tmp:
            original_db_path = relay_server._DB_PATH
            relay_server._DB_PATH = Path(tmp) / "letters.db"
            try:
                relay_server._init_db()
                with relay_server._db_session() as conn:
                    indexes = {
                        row["name"]
                        for row in conn.execute(
                            "SELECT name FROM sqlite_master "
                            "WHERE type = 'index' AND tbl_name = 'letters'"
                        ).fetchall()
                    }
                self.assertIn("idx_pair_id", indexes)
                self.assertIn("idx_letters_created", indexes)
            finally:
                relay_server._DB_PATH = original_db_path

    def test_cleanup_once_removes_only_expired_letters(self):
        with tempfile.TemporaryDirectory() as tmp:
            original_db_path = relay_server._DB_PATH
            relay_server._DB_PATH = Path(tmp) / "letters.db"
            try:
                relay_server._init_db()
                old = (datetime.now(timezone.utc) - timedelta(days=31)).replace(
                    tzinfo=None
                ).isoformat(timespec="microseconds")
                current = datetime.now(timezone.utc).replace(tzinfo=None).isoformat(
                    timespec="microseconds"
                )
                with relay_server._db_session() as conn:
                    for created_at in (old, current):
                        conn.execute(
                            "INSERT INTO letters(pair_code, message_id, meta, "
                            "content_b64, attach_b64, attach_ext, created_at) "
                            "VALUES (?, ?, ?, ?, ?, ?, ?)",
                            ("cleanup-test", None, "{}", "", "", "", created_at),
                        )
                    conn.commit()

                deleted = relay_server.cleanup_once(
                    now=datetime.now(timezone.utc).replace(tzinfo=None)
                )

                self.assertEqual(deleted, 1)
                with relay_server._db_session() as conn:
                    rows = conn.execute(
                        "SELECT created_at FROM letters ORDER BY id"
                    ).fetchall()
                self.assertEqual(len(rows), 1)
                self.assertEqual(rows[0]["created_at"], current)
            finally:
                relay_server._DB_PATH = original_db_path

    def test_poll_response_is_bounded_and_cursor_continues(self):
        with tempfile.TemporaryDirectory() as tmp:
            original_db_path = relay_server._DB_PATH
            original_limit = relay_server._POLL_RESPONSE_MAX_BYTES
            relay_server._DB_PATH = Path(tmp) / "letters.db"
            relay_server._POLL_RESPONSE_MAX_BYTES = 450
            try:
                relay_server._init_db()
                with relay_server._db_session() as conn:
                    for content in ("first", "second"):
                        conn.execute(
                            "INSERT INTO letters(pair_code, message_id, meta, "
                            "content_b64, attach_b64, attach_ext, created_at) "
                            "VALUES (?, ?, ?, ?, ?, ?, ?)",
                            (
                                "bounded-poll",
                                content,
                                json.dumps({"type": "letter"}),
                                base64.b64encode(content.encode()).decode(),
                                "",
                                "",
                                relay_server._now_iso(),
                            ),
                        )
                    conn.commit()

                client = relay_server.app.test_client()
                first = client.get("/api/poll?pair_code=bounded-poll")
                first_payload = first.get_json()
                self.assertEqual(first.status_code, 200)
                self.assertTrue(first_payload["has_more"])
                self.assertEqual(len(first_payload["letters"]), 1)

                second = client.get(
                    f"/api/poll?pair_code=bounded-poll&cursor={first_payload['server_cursor']}"
                )
                self.assertEqual(second.status_code, 200)
                self.assertEqual(len(second.get_json()["letters"]), 1)
                self.assertEqual(
                    base64.b64decode(second.get_json()["letters"][0]["content_base64"]),
                    b"second",
                )
            finally:
                relay_server._DB_PATH = original_db_path
                relay_server._POLL_RESPONSE_MAX_BYTES = original_limit

    def test_index_does_not_expose_database_statistics(self):
        response = relay_server.app.test_client().get("/")

        self.assertEqual(response.status_code, 200)
        payload = response.get_json()
        self.assertEqual(payload["service"], "CoupleSuite 云中转 (公钥身份版本)")
        self.assertNotIn("total_letters", payload)
        self.assertNotIn("paired_channels", payload)
        self.assertEqual(response.headers["Cache-Control"], "no-store")
        self.assertEqual(response.headers["X-Content-Type-Options"], "nosniff")

    def test_malformed_channel_members_are_not_used_for_authentication(self):
        with tempfile.TemporaryDirectory() as tmp:
            original_db_path = relay_server._DB_PATH
            relay_server._DB_PATH = Path(tmp) / "letters.db"
            try:
                relay_server._init_db()
                relay_server._save_channel("bad-channel", "not-a-key", "also-bad")

                self.assertIsNone(relay_server._channel_members("bad-channel"))
                self.assertIsNone(
                    relay_server._channel_resolve_pk("bad-channel", "unknown")
                )
            finally:
                relay_server._DB_PATH = original_db_path

    def test_malformed_pairing_member_is_reported_as_expired(self):
        with tempfile.TemporaryDirectory() as tmp:
            original_db_path = relay_server._DB_PATH
            relay_server._DB_PATH = Path(tmp) / "letters.db"
            try:
                relay_server._init_db()
                with relay_server._db_session() as conn:
                    conn.execute(
                        "INSERT INTO pairing_sessions(token, created_at) VALUES (?, ?)",
                        ("BAD234", time.time()),
                    )
                    conn.execute(
                        "INSERT INTO pairing_members "
                        "(token, role, created_at, pk_b64, nickname, nonce, confirmed) "
                        "VALUES (?, ?, ?, ?, ?, ?, ?)",
                        ("BAD234", "host", time.time(), "bad", "host", "nonce", 0),
                    )
                    conn.commit()

                response = relay_server.app.test_client().get(
                    "/api/pairing/poll?token=BAD234&role=host&step=wait_partner"
                )
                self.assertEqual(response.status_code, 410)
                self.assertTrue(response.get_json()["fatal"])
            finally:
                relay_server._DB_PATH = original_db_path

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

    def test_pairing_declare_confirm_builds_channel(self):
        with tempfile.TemporaryDirectory() as tmp:
            original_db_path = relay_server._DB_PATH
            original_legacy = relay_server.app.config["ALLOW_LEGACY_PAIR_CODE"]
            relay_server._DB_PATH = Path(tmp) / "letters.db"
            relay_server.app.config["ALLOW_LEGACY_PAIR_CODE"] = False
            try:
                relay_server._init_db()
                client = relay_server.app.test_client()
                token = "ABC234"
                host_key = Ed25519PrivateKey.generate()
                guest_key = Ed25519PrivateKey.generate()
                host_pk = relay_server._b64e(host_key.public_key().public_bytes_raw())
                guest_pk = relay_server._b64e(guest_key.public_key().public_bytes_raw())

                host_declared = client.post(
                    "/api/pairing/declare",
                    json={"token": token, "role": "host", "pk_b64": host_pk, "nickname": "A"},
                ).get_json()
                guest_declared = client.post(
                    "/api/pairing/declare",
                    json={"token": token, "role": "guest", "pk_b64": guest_pk, "nickname": "B"},
                ).get_json()
                self.assertTrue(host_declared["ok"])
                self.assertTrue(guest_declared["ok"])

                for role, key, nonce, partner_pk in (
                    ("host", host_key, host_declared["nonce"], guest_pk),
                    ("guest", guest_key, guest_declared["nonce"], host_pk),
                ):
                    signature = key.sign(
                        f"{role}|{token}|{nonce}|{partner_pk}".encode()
                    )
                    response = client.post(
                        "/api/pairing/confirm",
                        json={
                            "token": token,
                            "role": role,
                            "my_nonce": nonce,
                            "sig_b64": relay_server._b64e(signature),
                            "safety_confirmed": True,
                        },
                    )
                    self.assertEqual(response.status_code, 200)

                completed = client.get(
                    "/api/pairing/poll",
                    query_string={"token": token, "role": "host", "step": "both_confirmed"},
                )
                payload = completed.get_json()
                self.assertEqual(completed.status_code, 200)
                self.assertTrue(payload["both_confirmed"])
                self.assertEqual(
                    payload["channel_id"],
                    hashlib.sha256(
                        min(host_key.public_key().public_bytes_raw(), guest_key.public_key().public_bytes_raw())
                        + max(host_key.public_key().public_bytes_raw(), guest_key.public_key().public_bytes_raw())
                    ).hexdigest()[:24],
                )
                repeated = client.get(
                    "/api/pairing/poll",
                    query_string={"token": token, "role": "guest", "step": "both_confirmed"},
                )
                self.assertEqual(repeated.status_code, 200)
                self.assertEqual(repeated.get_json()["channel_id"], payload["channel_id"])
            finally:
                relay_server._DB_PATH = original_db_path
                relay_server.app.config["ALLOW_LEGACY_PAIR_CODE"] = original_legacy

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

    def test_pairing_declare_retry_preserves_nonce_and_confirmation(self):
        with tempfile.TemporaryDirectory() as tmp:
            original_db_path = relay_server._DB_PATH
            relay_server._DB_PATH = Path(tmp) / "letters.db"
            try:
                relay_server._init_db()
                key = Ed25519PrivateKey.generate()
                pk = relay_server._b64e(key.public_key().public_bytes_raw())
                first_nonce, conflict = relay_server._declare_pairing(
                    "ABC234", "host", pk, "A"
                )
                self.assertIsNotNone(first_nonce)
                self.assertFalse(conflict)
                with relay_server._db_session() as conn:
                    conn.execute(
                        "UPDATE pairing_members SET confirmed = 1 "
                        "WHERE token = ? AND role = ?",
                        ("ABC234", "host"),
                    )
                    conn.commit()

                second_nonce, conflict = relay_server._declare_pairing(
                    "ABC234", "host", pk, "A renamed"
                )
                self.assertEqual(second_nonce, first_nonce)
                self.assertFalse(conflict)
                state = relay_server._load_pairing("ABC234")
                self.assertTrue(state["host"]["confirmed"])
                self.assertEqual(state["host"]["nickname"], "A renamed")
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

    def test_poll_reports_and_advances_past_corrupt_stored_row(self):
        with tempfile.TemporaryDirectory() as tmp:
            original_db_path = relay_server._DB_PATH
            relay_server._DB_PATH = Path(tmp) / "letters.db"
            try:
                relay_server._init_db()
                with relay_server._db_session() as conn:
                    conn.execute(
                        "INSERT INTO letters "
                        "(pair_code, message_id, meta, content_b64, attach_b64, attach_ext, created_at) "
                        "VALUES (?, ?, ?, ?, ?, ?, ?)",
                        ("corrupt-test", "bad-1", "{broken", "bad", "", "", relay_server._now_iso()),
                    )
                    conn.commit()
                    row_id = conn.execute("SELECT last_insert_rowid()").fetchone()[0]

                response = relay_server.app.test_client().get(
                    "/api/poll",
                    query_string={"pair_code": "corrupt-test", "cursor": "0"},
                )
                payload = response.get_json()
                self.assertEqual(response.status_code, 200)
                self.assertEqual(payload["letters"], [])
                self.assertEqual(payload["skipped_ids"], [row_id])
                self.assertEqual(payload["server_cursor"], str(row_id))
            finally:
                relay_server._DB_PATH = original_db_path

    def test_channel_poll_skips_stored_row_with_invalid_signature(self):
        with tempfile.TemporaryDirectory() as tmp:
            original_db_path = relay_server._DB_PATH
            relay_server._DB_PATH = Path(tmp) / "letters.db"
            try:
                relay_server._init_db()
                sender_key = Ed25519PrivateKey.generate()
                receiver_key = Ed25519PrivateKey.generate()
                sender_pk = relay_server._b64e(sender_key.public_key().public_bytes_raw())
                receiver_pk = relay_server._b64e(receiver_key.public_key().public_bytes_raw())
                channel_id = "channel-corrupt-signature"
                relay_server._save_channel(channel_id, sender_pk, receiver_pk)
                content_b64 = "aGVsbG8="
                meta = {"type": "letter", "pk_fp": relay_server._pk_fp(
                    sender_key.public_key().public_bytes_raw()
                ), "sig_b64": "tampered"}
                with relay_server._db_session() as conn:
                    conn.execute(
                        "INSERT INTO letters "
                        "(pair_code, message_id, meta, content_b64, attach_b64, attach_ext, created_at) "
                        "VALUES (?, ?, ?, ?, ?, ?, ?)",
                        (channel_id, "bad-signature", json.dumps(meta), content_b64, "", "", relay_server._now_iso()),
                    )
                    conn.commit()

                receiver_fp = relay_server._pk_fp(receiver_key.public_key().public_bytes_raw())
                auth = receiver_key.sign(
                    f"poll_auth|{channel_id}|{receiver_fp}|0".encode("utf-8")
                )
                response = relay_server.app.test_client().get(
                    "/api/poll",
                    query_string={
                        "channel_id": channel_id,
                        "pk_fp": receiver_fp,
                        "sig_b64": relay_server._b64e(auth),
                        "cursor": "0",
                    },
                )
                payload = response.get_json()
                self.assertEqual(response.status_code, 200)
                self.assertEqual(payload["letters"], [])
                self.assertEqual(payload["skipped_ids"], [1])
                self.assertEqual(payload["server_cursor"], "1")
            finally:
                relay_server._DB_PATH = original_db_path

    def test_cursor_beyond_restored_database_replays_bucket(self):
        client = relay_server.app.test_client()
        response = client.post(
            "/api/send",
            json={
                "pair_code": "restore-test",
                "meta": {"type": "letter", "message_id": "restore-message"},
                "content_base64": "cmVzdG9yZQ==",
                "attachment_base64": "",
                "attachment_ext": "",
            },
        )
        self.assertEqual(response.status_code, 200)

        replay = client.get(
            "/api/poll",
            query_string={"pair_code": "restore-test", "cursor": "999999"},
        )
        self.assertEqual(replay.status_code, 200)
        payload = replay.get_json()
        self.assertTrue(payload["cursor_reset"])
        self.assertEqual([item["meta"]["message_id"] for item in payload["letters"]], [
            "restore-message",
        ])


if __name__ == "__main__":
    unittest.main()
