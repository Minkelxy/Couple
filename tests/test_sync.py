import socket
import tempfile
import threading
import unittest
from types import SimpleNamespace
from pathlib import Path
from unittest.mock import Mock, patch

from DesktopMailbox.sync import SyncHub, _recv_exact
import identity
from common_utils import AtomicJsonStore


class SyncTransportTests(unittest.TestCase):
    def test_send_async_assigns_message_id_for_events(self):
        hub = SimpleNamespace(
            _my_id="local-id",
            _cfg={"sync_mode": "lan"},
            _cloud_client=None,
        )
        with patch("DesktopMailbox.sync.idm.sign_message", side_effect=lambda meta, *_: meta) as sign_message:
            SyncHub.send_async(hub, {"type": "checkin"}, "", b"", "", silent=True)

        signed_meta = sign_message.call_args[0][0]
        self.assertRegex(signed_meta["message_id"], r"^[0-9a-f]{32}$")

    def test_send_async_preserves_existing_message_id(self):
        hub = SimpleNamespace(
            _my_id="local-id",
            _cfg={"sync_mode": "lan"},
            _cloud_client=None,
        )
        with patch("DesktopMailbox.sync.idm.sign_message", side_effect=lambda meta, *_: meta) as sign_message:
            SyncHub.send_async(
                hub, {"type": "movie", "message_id": "event-1"}, "", b"", "", silent=True
            )

        self.assertEqual(sign_message.call_args[0][0]["message_id"], "event-1")

    def test_stop_closes_lan_server_socket(self):
        server = Mock()
        hub = SimpleNamespace(
            _stopped=False,
            _heartbeat_timer=None,
            _cloud_timer=None,
            _server=server,
            _thread=None,
        )

        SyncHub.stop(hub)

        self.assertTrue(hub._stopped)
        self.assertIsNone(hub._server)
        server.shutdown.assert_called_once_with()
        server.server_close.assert_called_once_with()

    def test_invalid_outbox_attachment_does_not_leave_inflight_marker(self):
        item_id = "message-1"
        hub = SimpleNamespace(
            _outbox=SimpleNamespace(
                due=Mock(return_value=[{
                    "id": item_id,
                    "meta": {},
                    "attachment_b64": "not-base64",
                }]),
                remove=Mock(side_effect=OSError("disk full")),
            ),
            _outbox_lock=threading.Lock(),
            _outbox_inflight=set(),
        )

        with patch("DesktopMailbox.sync.log_exception"):
            SyncHub._start_cloud_outbox_item(hub, item_id)

        self.assertNotIn(item_id, hub._outbox_inflight)

    def test_invalid_outbox_shape_is_removed(self):
        item_id = "message-1"
        hub = SimpleNamespace(
            _outbox=SimpleNamespace(
                due=Mock(return_value=[{
                    "id": item_id,
                    "meta": [],
                    "content": "hello",
                    "attachment_b64": "",
                    "attachment_ext": "",
                }]),
                remove=Mock(),
            ),
            _outbox_lock=threading.Lock(),
            _outbox_inflight=set(),
        )

        SyncHub._start_cloud_outbox_item(hub, item_id)

        hub._outbox.remove.assert_called_once_with(item_id)
        self.assertNotIn(item_id, hub._outbox_inflight)

    def test_cloud_outbox_inflight_is_cleared_when_persist_fails(self):
        item_id = "message-1"
        hub = SimpleNamespace(
            _cloud_client=SimpleNamespace(send_letter=Mock(return_value=True)),
            _outbox=SimpleNamespace(
                remove=Mock(side_effect=OSError("disk full")),
                retry=Mock(),
            ),
            _outbox_lock=threading.Lock(),
            _outbox_inflight={item_id},
            send_result=Mock(),
        )

        with patch("DesktopMailbox.sync.log_exception"):
            SyncHub._cloud_send_blocking(
                hub, {}, "hello", b"", "", item_id=item_id
            )

        self.assertNotIn(item_id, hub._outbox_inflight)
        hub.send_result.emit.assert_called_once_with(True, "已通过云中转寄出")

    def test_on_received_drops_non_string_event_type(self):
        hub = SimpleNamespace(
            _my_id="local-id",
            event_received=Mock(),
        )
        with patch.object(
            identity,
            "get_status",
            return_value=SimpleNamespace(paired=False),
        ):
            SyncHub.on_received(hub, {"type": ["invalid"]}, "", b"", "")

        hub.event_received.emit.assert_not_called()

    def test_on_received_recovers_from_non_string_delivery_time(self):
        hub = SimpleNamespace(
            _my_id="local-id",
            letter_received=Mock(),
        )
        with patch.object(
            identity,
            "get_status",
            return_value=SimpleNamespace(paired=False),
        ), patch(
            "DesktopMailbox.sync.letter_store.write_letter",
            return_value={"id": "letter-1"},
        ) as write_letter:
            SyncHub.on_received(
                hub,
                {"type": "letter", "deliver_at": None},
                "hello",
                b"",
                "",
            )

        write_letter.assert_called_once()
        hub.letter_received.emit.assert_called_once_with("letter-1")

    def test_cloud_cursor_is_persisted_atomically(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = AtomicJsonStore(Path(tmp) / "cursor.json", {})
            hub = SimpleNamespace(
                _cursor_store=store,
                _cursor_lock=threading.Lock(),
                _cloud_last_ts="cursor",
                _cursor_key="relay-key",
            )

            SyncHub._save_cursor(hub)

            self.assertEqual(
                store.get("cursors")["relay-key"]["server_ts"], "cursor"
            )

    def test_cloud_cursor_isolated_by_namespace(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = AtomicJsonStore(Path(tmp) / "cursor.json", {
                "version": 2,
                "cursors": {
                    "relay-a": {"cursor": 12, "server_ts": "12"},
                    "relay-b": {"cursor": 34, "server_ts": "34"},
                },
            })
            hub = SimpleNamespace(_cursor_store=store, _cursor_key="relay-b")

            self.assertEqual(SyncHub._load_cursor(hub), "34")

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

    def test_paired_channel_starts_cloud_without_legacy_pair_code(self):
        from DesktopMailbox import sync as sync_module

        paired = SimpleNamespace(paired=True, channel_id="channel-1")
        with patch.object(sync_module.idm, "get_status", return_value=paired), \
                patch.object(sync_module, "CloudSyncClient") as cloud_client:
            hub = SyncHub({
                "sync_mode": "cloud",
                "cloud_server": "https://relay.example",
                "cloud_pair_code": "",
            })

        cloud_client.assert_called_once_with(
            "https://relay.example", "", sig_dedup_fn=hub._check_and_record_sig
        )

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
