import json
import threading
import unittest
from unittest.mock import patch

import pairing


class _Response:
    def __init__(self, body: bytes):
        self.body = body

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def read(self):
        return self.body


class PairingTransportTests(unittest.TestCase):
    def test_confirm_rejection_is_reported_immediately(self):
        progress = []
        session = pairing.PairingSession.__new__(pairing.PairingSession)
        session._server = "https://relay.invalid"
        session._token = "ABC234"
        session._role = "host"
        session._stop = threading.Event()
        session._cb = progress.append

        with patch.object(session, "_confirm_payload", return_value={"token": "ABC234"}), \
                patch.object(
                    pairing,
                    "_post",
                    return_value={"ok": False, "message": "nonce 不匹配"},
                ), patch.object(pairing, "_get") as get:
            session._confirm_loop()

        self.assertEqual(progress[0].phase, pairing.PairingPhase.FAILED)
        self.assertEqual(progress[0].error_message, "nonce 不匹配")
        get.assert_not_called()

    def test_post_and_get_reject_non_object_json(self):
        with patch.object(
            pairing.urllib.request,
            "urlopen",
            return_value=_Response(json.dumps(["invalid"]).encode("utf-8")),
        ):
            self.assertIsNone(pairing._post("https://relay.invalid", "/post", {}))
            self.assertIsNone(pairing._get("https://relay.invalid", "/get", {}))

    def test_post_and_get_return_object_json(self):
        with patch.object(
            pairing.urllib.request,
            "urlopen",
            return_value=_Response(b'{"ok": true}'),
        ):
            self.assertEqual(
                pairing._post("https://relay.invalid", "/post", {}),
                {"ok": True},
            )
            self.assertEqual(
                pairing._get("https://relay.invalid", "/get", {}),
                {"ok": True},
            )

    def test_declare_retries_transport_timeout_once(self):
        session = pairing.PairingSession.__new__(pairing.PairingSession)
        session._server = "https://relay.invalid"
        session._nickname = "A"
        session._stop = threading.Event()
        session._role = "host"
        session._nonce_host = None
        status = type("Status", (), {"my_pk_b64": "public-key"})()
        with patch.object(pairing.idm, "get_status", return_value=status), \
                patch.object(
                    pairing,
                    "_post",
                    side_effect=[None, {"ok": True, "nonce": "nonce-1"}],
                ) as post, patch.object(pairing, "_DECLARE_RETRY_DELAY_SEC", 0):
            ok, nonce = session._declare("host", "ABC234")

        self.assertTrue(ok)
        self.assertEqual(nonce, "nonce-1")
        self.assertEqual(session._nonce_host, "nonce-1")
        self.assertEqual(post.call_count, 2)


if __name__ == "__main__":
    unittest.main()
