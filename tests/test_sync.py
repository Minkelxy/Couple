import socket
import unittest

from DesktopMailbox.sync import _recv_exact


class SyncTransportTests(unittest.TestCase):
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
