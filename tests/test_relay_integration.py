import base64
import tempfile
import threading
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from werkzeug.serving import make_server

import relay_server
from DesktopMailbox.cloud_sync import CloudSyncClient


class RelayHttpIntegrationTests(unittest.TestCase):
    def test_channel_client_round_trip_without_legacy_pair_code(self):
        with tempfile.TemporaryDirectory() as tmp:
            original_db_path = relay_server._DB_PATH
            original_legacy = relay_server.app.config["ALLOW_LEGACY_PAIR_CODE"]
            relay_server._DB_PATH = Path(tmp) / "letters.db"
            relay_server.app.config["ALLOW_LEGACY_PAIR_CODE"] = False
            relay_server._init_db()
            first_key = Ed25519PrivateKey.generate()
            second_key = Ed25519PrivateKey.generate()
            first_pk = relay_server._b64e(
                first_key.public_key().public_bytes_raw()
            )
            second_pk = relay_server._b64e(
                second_key.public_key().public_bytes_raw()
            )
            channel_id = "channel-integration"
            relay_server._save_channel(channel_id, first_pk, second_pk)
            server = make_server("127.0.0.1", 0, relay_server.app)
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            try:
                base_url = f"http://127.0.0.1:{server.server_port}"
                sender = CloudSyncClient(base_url, "")
                receiver = CloudSyncClient(base_url, "")
                sender_status = SimpleNamespace(
                    paired=True, channel_id=channel_id,
                    my_pk_b64=first_pk, partner_pk_b64=second_pk,
                )
                receiver_status = SimpleNamespace(
                    paired=True, channel_id=channel_id,
                    my_pk_b64=second_pk, partner_pk_b64=first_pk,
                )
                with patch(
                    "DesktopMailbox.cloud_sync.idm.get_status",
                    return_value=sender_status,
                ), patch(
                    "DesktopMailbox.cloud_sync.idm.ensure_identity",
                    return_value=(first_key.public_key().public_bytes_raw(), first_key),
                ):
                    self.assertTrue(sender.send_letter({}, "channel hello", b"", ""))
                    self.assertTrue(sender.send_letter(
                        {"type": "ping", "kind": "heartbeat"}, "", b"", ""
                    ))
                with patch(
                    "DesktopMailbox.cloud_sync.idm.get_status",
                    return_value=receiver_status,
                ), patch(
                    "DesktopMailbox.cloud_sync.idm.ensure_identity",
                    return_value=(second_key.public_key().public_bytes_raw(), second_key),
                ):
                    letters, cursor = receiver.poll_letters()
                self.assertEqual(
                    [item["content"] for item in letters], ["channel hello", ""]
                )
                self.assertEqual(letters[1]["meta"]["kind"], "heartbeat")
                self.assertTrue(cursor.isdigit())
                with relay_server._db_session() as conn:
                    self.assertEqual(
                        conn.execute("SELECT COUNT(*) FROM letters").fetchone()[0],
                        1,
                    )
            finally:
                server.shutdown()
                thread.join(timeout=5)
                relay_server._DB_PATH = original_db_path
                relay_server.app.config["ALLOW_LEGACY_PAIR_CODE"] = original_legacy

    def test_cloud_client_round_trip_and_restart_cursor(self):
        with tempfile.TemporaryDirectory() as tmp:
            original_db_path = relay_server._DB_PATH
            original_legacy = relay_server.app.config["ALLOW_LEGACY_PAIR_CODE"]
            relay_server._DB_PATH = Path(tmp) / "letters.db"
            relay_server.app.config["ALLOW_LEGACY_PAIR_CODE"] = True
            relay_server._init_db()
            server = make_server("127.0.0.1", 0, relay_server.app)
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            try:
                base_url = f"http://127.0.0.1:{server.server_port}"
                sender = CloudSyncClient(base_url, "integration-pair")
                send_payload = {
                    "pair_code": "integration-pair",
                    "meta": {"type": "letter"},
                    "content_base64": base64.b64encode(b"hello").decode("ascii"),
                    "attachment_base64": "",
                    "attachment_ext": "",
                }
                with patch(
                    "DesktopMailbox.cloud_sync.idm.get_status",
                    return_value=SimpleNamespace(paired=False),
                ):
                    with patch.object(sender, "_build_send_payload", return_value=send_payload):
                        self.assertTrue(sender.send_letter({"type": "letter"}, "hello", b"", ""))

                    receiver = CloudSyncClient(base_url, "integration-pair")
                    letters, cursor = receiver.poll_letters()
                self.assertEqual([letter["content"] for letter in letters], ["hello"])
                self.assertTrue(cursor.isdigit())
            finally:
                server.shutdown()
                thread.join(timeout=5)

            # A fresh HTTP server over the same SQLite file must resume from the cursor.
            server = make_server("127.0.0.1", 0, relay_server.app)
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            try:
                base_url = f"http://127.0.0.1:{server.server_port}"
                sender = CloudSyncClient(base_url, "integration-pair")
                send_payload = {
                    "pair_code": "integration-pair",
                    "meta": {"type": "letter"},
                    "content_base64": base64.b64encode(b"world").decode("ascii"),
                    "attachment_base64": "",
                    "attachment_ext": "",
                }
                with patch(
                    "DesktopMailbox.cloud_sync.idm.get_status",
                    return_value=SimpleNamespace(paired=False),
                ):
                    with patch.object(sender, "_build_send_payload", return_value=send_payload):
                        self.assertTrue(sender.send_letter({"type": "letter"}, "world", b"", ""))
                    receiver = CloudSyncClient(base_url, "integration-pair")
                    letters, next_cursor = receiver.poll_letters(cursor)
                self.assertEqual([letter["content"] for letter in letters], ["world"])
                self.assertGreater(int(next_cursor), int(cursor))
            finally:
                server.shutdown()
                thread.join(timeout=5)
                relay_server._DB_PATH = original_db_path
                relay_server.app.config["ALLOW_LEGACY_PAIR_CODE"] = original_legacy


if __name__ == "__main__":
    unittest.main()
