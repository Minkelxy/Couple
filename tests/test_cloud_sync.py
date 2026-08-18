import base64
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from DesktopMailbox.cloud_sync import CloudSyncClient


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


if __name__ == "__main__":
    unittest.main()
