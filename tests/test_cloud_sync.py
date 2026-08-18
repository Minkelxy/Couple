import base64
import json
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from DesktopMailbox.cloud_sync import CloudSyncClient


class _Response:
    def __init__(self, body: bytes):
        self.body = body

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def read(self):
        return self.body


class CloudSyncParsingTests(unittest.TestCase):
    def setUp(self):
        self.client = CloudSyncClient("https://relay.invalid", "pair-code")

    def test_invalid_attachment_base64_is_rejected(self):
        item = {
            "meta": {},
            "content_base64": base64.b64encode(b"hello").decode(),
            "attachment_base64": "not base64!",
        }
        self.assertIsNone(self.client._parse_one_inbound(item))

    def test_invalid_content_base64_is_rejected(self):
        item = {"meta": {}, "content_base64": "not base64!", "attachment_base64": ""}
        self.assertIsNone(self.client._parse_one_inbound(item))

    def test_valid_legacy_payload_is_decoded(self):
        item = {
            "meta": {"type": "letter"},
            "content_base64": base64.b64encode(b"hello").decode(),
            "attachment_base64": base64.b64encode(b"bytes").decode(),
            "attachment_ext": ".bin",
        }
        with patch(
            "DesktopMailbox.cloud_sync.idm.get_status",
            return_value=SimpleNamespace(paired=False),
        ):
            parsed = self.client._parse_one_inbound(item)

        self.assertEqual(parsed["content"], "hello")
        self.assertEqual(parsed["attachment"], b"bytes")

    def test_poll_drops_invalid_server_cursor_without_dropping_letters(self):
        payload = {
            "server_ts": "not-a-timestamp",
            "letters": [{
                "meta": {"type": "letter"},
                "content_base64": base64.b64encode(b"hello").decode(),
                "attachment_base64": "",
            }],
        }
        with patch(
            "DesktopMailbox.cloud_sync.urllib.request.urlopen",
            return_value=_Response(json.dumps(payload).encode("utf-8")),
        ), patch.object(self.client, "_build_poll_url", return_value="https://relay.invalid/poll"), \
                patch("DesktopMailbox.cloud_sync.idm.get_status", return_value=SimpleNamespace(paired=False)):
            letters, server_ts = self.client.poll_letters()

        self.assertEqual(server_ts, "")
        self.assertEqual(len(letters), 1)


if __name__ == "__main__":
    unittest.main()
