import socket
import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch

from DesktopMailbox.sync import SyncHub, _recv_exact


class SyncTransportTests(unittest.TestCase):
    def test_cloud_cursor_does_not_advance_when_batch_processing_fails(self):
        hub = SimpleNamespace(
            _stopped=False,
            _cloud_client=SimpleNamespace(
                poll_letters=Mock(return_value=([{"meta": {}}], "new-cursor")),
            ),
            _cloud_last_ts="old-cursor",
            on_received=Mock(side_effect=RuntimeError("processing failed")),
            _save_cursor=Mock(),
            _cloud_schedule_poll=Mock(),
        )

        with patch("DesktopMailbox.sync.log_exception"):
            SyncHub._cloud_poll_loop(hub)

        self.assertEqual(hub._cloud_last_ts, "old-cursor")
        hub._save_cursor.assert_not_called()
        hub._cloud_schedule_poll.assert_called_once()

    def test_recv_exact_returns_none_for_truncated_payload(self):
        reader, writer = socket.socketpair()
        try:
            writer.sendall(b"abc")
            writer.close()
            self.assertIsNone(_recv_exact(reader, 4))
        finally:
            reader.close()

    def test_recv_exact_preserves_valid_empty_payload(self):
        reader, writer = socket.socketpair()
        try:
            self.assertEqual(_recv_exact(reader, 0), b"")
        finally:
            reader.close()
            writer.close()


if __name__ == "__main__":
    unittest.main()
