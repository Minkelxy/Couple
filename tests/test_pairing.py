import json
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


if __name__ == "__main__":
    unittest.main()
