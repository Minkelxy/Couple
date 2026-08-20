import json
import socket
import socketserver
import struct
import tempfile
import threading
import unittest
import collections
from types import MethodType, SimpleNamespace
from pathlib import Path
from unittest.mock import MagicMock, Mock, patch

from DesktopMailbox.sync import SyncHub, _LAN_ACK_OK, _LAN_ACK_REJECTED, _make_handler, _recv_exact
from DailyCheckin import checkin_window
import identity
from common_utils import AtomicJsonStore


class SyncTransportTests(unittest.TestCase):
    def test_message_id_deduplication_is_bounded_and_persisted(self):
        hub = SimpleNamespace(
            _message_seen_store=Mock(),
            _message_seen_lock=threading.Lock(),
            _seen_message_ids=collections.OrderedDict(),
            _pending_message_ids=set(),
            _message_seen_lru_max=2,
        )
        hub._persist_message_ids = MethodType(SyncHub._persist_message_ids, hub)

        self.assertTrue(SyncHub._check_and_record_message_id(hub, "event-1"))
        self.assertTrue(SyncHub._check_and_record_message_id(hub, "event-2"))
        self.assertFalse(SyncHub._check_and_record_message_id(hub, "event-1"))
        self.assertTrue(SyncHub._check_and_record_message_id(hub, "event-3"))
        self.assertNotIn("event-2", hub._seen_message_ids)
        hub._message_seen_store.save.assert_called()

    def test_event_id_is_not_persisted_when_event_handler_fails(self):
        hub = SimpleNamespace(
            _my_id="local-id",
            _message_seen_store=Mock(),
            _message_seen_lock=threading.Lock(),
            _seen_message_ids=collections.OrderedDict(),
            _pending_message_ids=set(),
            _message_seen_lru_max=2,
            event_received=SimpleNamespace(
                emit=Mock(side_effect=RuntimeError("handler failed"))
            ),
        )
        hub._check_and_record_message_id = MethodType(
            SyncHub._check_and_record_message_id, hub
        )
        hub._persist_message_ids = MethodType(SyncHub._persist_message_ids, hub)
        hub._forget_message_id = MethodType(SyncHub._forget_message_id, hub)
        hub._commit_message_id = MethodType(SyncHub._commit_message_id, hub)
        with patch.object(identity, "get_status", return_value=SimpleNamespace(paired=False)):
            with self.assertRaises(RuntimeError):
                SyncHub.on_received(
                    hub,
                    {"type": "checkin", "message_id": "event-failed"},
                    "",
                    b"",
                    "",
                )

        self.assertNotIn("event-failed", hub._seen_message_ids)
        hub._message_seen_store.save.assert_called_once_with([])

    def test_committing_one_event_does_not_persist_other_pending_event(self):
        hub = SimpleNamespace(
            _message_seen_store=Mock(),
            _message_seen_lock=threading.Lock(),
            _seen_message_ids=collections.OrderedDict(),
            _pending_message_ids=set(),
            _message_seen_lru_max=4,
        )
        hub._persist_message_ids = MethodType(SyncHub._persist_message_ids, hub)
        hub._commit_message_id = MethodType(SyncHub._commit_message_id, hub)

        self.assertTrue(SyncHub._check_and_record_message_id(hub, "event-a", persist=False))
        self.assertTrue(SyncHub._check_and_record_message_id(hub, "event-b", persist=False))
        SyncHub._commit_message_id(hub, "event-a")

        hub._message_seen_store.save.assert_called_once_with(["event-a"])

    def test_send_async_reports_outbox_write_failure_without_raising(self):
        hub = SimpleNamespace(
            _my_id="local-id",
            _cfg={"sync_mode": "cloud"},
            _cloud_client=Mock(),
            _outbox=Mock(),
            send_result=Mock(),
        )
        hub._outbox.enqueue.side_effect = OSError("disk full")
        with patch("DesktopMailbox.sync.idm.sign_message", side_effect=lambda meta, *_: meta), \
                patch("DesktopMailbox.sync.log_exception"):
            SyncHub.send_async(hub, {"type": "checkin"}, "", b"", "", silent=False)

        hub.send_result.emit.assert_called_once_with(False, "云同步失败：本地发送队列无法写入")

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
            _lifecycle_lock=threading.RLock(),
            _started=True,
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

    def test_lan_receiver_acknowledges_processed_payload(self):
        hub = SimpleNamespace(on_received=Mock())
        server = socketserver.ThreadingTCPServer(
            ("127.0.0.1", 0), _make_handler(hub)
        )
        server.daemon_threads = True
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            with socket.create_connection(server.server_address, timeout=2) as client:
                header = json.dumps({
                    "meta": {"type": "letter"},
                    "content_len": 0,
                    "attachment_len": 0,
                    "attachment_ext": "",
                }).encode("utf-8")
                client.sendall(struct.pack(">I", len(header)) + header)
                self.assertEqual(client.recv(1), _LAN_ACK_OK)
            hub.on_received.assert_called_once_with(
                {"type": "letter"}, "", b"", ""
            )
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=2)

    def test_lan_receiver_rejects_processing_failure(self):
        hub = SimpleNamespace(on_received=Mock(side_effect=OSError("disk full")))
        server = socketserver.ThreadingTCPServer(
            ("127.0.0.1", 0), _make_handler(hub)
        )
        server.daemon_threads = True
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            with socket.create_connection(server.server_address, timeout=2) as client:
                header = json.dumps({
                    "meta": {"type": "letter"},
                    "content_len": 0,
                    "attachment_len": 0,
                    "attachment_ext": "",
                }).encode("utf-8")
                client.sendall(struct.pack(">I", len(header)) + header)
                self.assertEqual(client.recv(1), _LAN_ACK_REJECTED)
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=2)

    def test_lan_sender_waits_for_processing_ack(self):
        connection = MagicMock()
        sock = connection.__enter__.return_value
        sock.recv.return_value = _LAN_ACK_OK
        hub = SimpleNamespace(send_result=Mock())
        with patch(
            "DesktopMailbox.sync.socket.create_connection",
            return_value=connection,
        ):
            SyncHub._send_blocking(
                hub, "127.0.0.1", 52014, {"type": "letter"}, "hello", b"", ""
            )

        sock.recv.assert_called_once_with(1)
        hub.send_result.emit.assert_called_once_with(True, "已同步到 127.0.0.1")

    def test_start_is_idempotent_and_restartable_after_stop(self):
        hub = SimpleNamespace(
            _lifecycle_lock=threading.RLock(),
            _started=False,
            _stopped=True,
            _cfg={"sync_mode": "cloud"},
            _cloud_client=object(),
            _server=None,
            _thread=None,
            _cloud_timer=None,
            _heartbeat_timer=None,
            _cloud_schedule_poll=Mock(),
            _flush_cloud_outbox=Mock(),
            _heartbeat_schedule=Mock(),
        )
        self.assertTrue(SyncHub.start(hub))
        self.assertTrue(SyncHub.start(hub))
        self.assertEqual(hub._cloud_schedule_poll.call_count, 1)
        self.assertEqual(hub._flush_cloud_outbox.call_count, 1)
        self.assertEqual(hub._heartbeat_schedule.call_count, 1)

        SyncHub.stop(hub)
        self.assertTrue(SyncHub.start(hub))

        self.assertEqual(hub._cloud_schedule_poll.call_count, 2)
        self.assertEqual(hub._flush_cloud_outbox.call_count, 2)
        self.assertEqual(hub._heartbeat_schedule.call_count, 2)

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

    def test_outbox_does_not_start_more_than_four_cloud_sends(self):
        item_id = "message-5"
        hub = SimpleNamespace(
            _outbox=SimpleNamespace(due=Mock(return_value=[{
                "id": item_id,
                "meta": {},
                "content": "hello",
                "attachment_b64": "",
                "attachment_ext": "",
            }])),
            _outbox_lock=threading.Lock(),
            _outbox_inflight={"message-1", "message-2", "message-3", "message-4"},
        )

        with patch("DesktopMailbox.sync.threading.Thread") as thread:
            SyncHub._start_cloud_outbox_item(hub, item_id)

        thread.assert_not_called()
        self.assertNotIn(item_id, hub._outbox_inflight)

    def test_oversized_outbox_attachment_is_removed_before_decode(self):
        item_id = "message-large"
        hub = SimpleNamespace(
            _outbox=SimpleNamespace(
                due=Mock(return_value=[{
                    "id": item_id,
                    "meta": {},
                    "attachment_b64": "A" * (4 * ((50 * 1024 * 1024 + 2) // 3) + 1),
                }]),
                remove=Mock(),
            ),
            _outbox_lock=threading.Lock(),
            _outbox_inflight=set(),
        )

        SyncHub._start_cloud_outbox_item(hub, item_id)

        hub._outbox.remove.assert_called_once_with(item_id)
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

    def test_on_received_returns_rejected_for_invalid_signature(self):
        hub = SimpleNamespace(_my_id="local-id")
        with patch.object(
            identity,
            "get_status",
            return_value=SimpleNamespace(paired=True),
        ), patch.object(
            identity,
            "ensure_identity",
            return_value=(b"local-public-key", object()),
        ), patch.object(
            identity,
            "_pk_fp",
            return_value="local-fingerprint",
        ), patch.object(identity, "verify_message", return_value=False):
            self.assertFalse(SyncHub.on_received(
                hub,
                {"type": "letter", "pk_fp": "partner-fingerprint"},
                "hello",
                b"",
                "",
            ))

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

    def test_lan_storage_failure_releases_signature_for_retry(self):
        hub = SimpleNamespace(
            _my_id="local-id",
            _sig_lock=threading.Lock(),
            _seen_sigs=collections.OrderedDict(),
            _sig_lru_max=16,
            _dispatch_result_lock=threading.Lock(),
            _dispatch_results={},
            letter_received=Mock(),
        )
        hub._check_and_record_sig = MethodType(SyncHub._check_and_record_sig, hub)
        hub._forget_sig = MethodType(SyncHub._forget_sig, hub)
        hub.record_event_dispatch = MethodType(SyncHub.record_event_dispatch, hub)
        hub._take_event_dispatch_result = MethodType(
            SyncHub._take_event_dispatch_result, hub
        )
        meta = {"type": "letter", "sig_b64": "sig-lan-retry"}

        with patch.object(
            identity,
            "get_status",
            return_value=SimpleNamespace(paired=True),
        ), patch.object(
            identity,
            "ensure_identity",
            return_value=(b"local-public-key", object()),
        ), patch.object(
            identity,
            "_pk_fp",
            return_value="other-fingerprint",
        ), patch.object(
            identity,
            "verify_message",
            return_value=True,
        ), patch(
            "DesktopMailbox.sync.letter_store.write_letter",
            side_effect=[OSError("disk full"), {"id": "letter-1"}],
        ):
            with self.assertRaises(OSError):
                SyncHub.on_received(hub, meta, "hello", b"", "")
            SyncHub.on_received(hub, meta, "hello", b"", "")

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

    def test_ui_dispatch_timeout_releases_retry_state(self):
        hub = SimpleNamespace(
            _my_id="local-id",
            _dispatch_ack_enabled=True,
            _dispatch_result_lock=threading.Lock(),
            _dispatch_results={},
            _dispatch_waiters={},
            _message_seen_store=Mock(),
            _message_seen_lock=threading.Lock(),
            _seen_message_ids=collections.OrderedDict(),
            _pending_message_ids=set(),
            _message_seen_lru_max=16,
            _sig_lock=threading.Lock(),
            _seen_sigs=collections.OrderedDict(),
            _sig_lru_max=16,
            event_received=Mock(),
        )
        for name in (
            "_check_and_record_message_id",
            "_persist_message_ids",
            "_forget_message_id",
            "_commit_message_id",
            "_register_event_dispatch",
            "_take_event_dispatch_result",
            "_forget_sig",
        ):
            setattr(hub, name, MethodType(getattr(SyncHub, name), hub))

        from DesktopMailbox import sync as sync_module

        with patch.object(
            identity, "get_status", return_value=SimpleNamespace(paired=False)
        ), patch.object(sync_module, "_EVENT_DISPATCH_TIMEOUT_SEC", 0.01):
            with self.assertRaises(TimeoutError):
                SyncHub.on_received(
                    hub,
                    {"type": "checkin", "message_id": "timeout-1"},
                    "",
                    b"",
                    "",
                )

        self.assertEqual(hub._dispatch_waiters, {})
        self.assertEqual(hub._dispatch_results, {})
        self.assertNotIn("timeout-1", hub._seen_message_ids)

    def test_cloud_storage_failure_retries_real_partner_event(self):
        def dispatch(_event_type, meta, content, attachment, att_ext):
            checkin_window.handle_partner_event(meta, content, attachment, att_ext)

        hub = SimpleNamespace(
            _my_id="local-id",
            _stopped=False,
            _cloud_client=SimpleNamespace(
                poll_letters=Mock(side_effect=[
                    ([{
                        "meta": {
                            "type": "checkin",
                            "message_id": "checkin-retry",
                            "sig_b64": "sig-retry",
                            "date": "2026-02-20",
                            "mood": 5,
                        },
                        "content": "",
                        "attachment": b"",
                        "attachment_ext": "",
                    }], "new-cursor"),
                    ([{
                        "meta": {
                            "type": "checkin",
                            "message_id": "checkin-retry",
                            "sig_b64": "sig-retry",
                            "date": "2026-02-20",
                            "mood": 5,
                        },
                        "content": "",
                        "attachment": b"",
                        "attachment_ext": "",
                    }], "new-cursor"),
                ]),
            ),
            _cloud_last_ts="old-cursor",
            _save_cursor=Mock(),
            _cloud_schedule_poll=Mock(),
            _flush_cloud_outbox=Mock(),
            _sig_lock=threading.Lock(),
            _seen_sigs=collections.OrderedDict(),
            _sig_lru_max=16,
            _message_seen_store=Mock(),
            _message_seen_lock=threading.Lock(),
            _seen_message_ids=collections.OrderedDict(),
            _pending_message_ids=set(),
            _message_seen_lru_max=16,
            event_received=SimpleNamespace(emit=dispatch),
        )
        hub._check_and_record_message_id = MethodType(
            SyncHub._check_and_record_message_id, hub
        )
        hub._persist_message_ids = MethodType(SyncHub._persist_message_ids, hub)
        hub._forget_message_id = MethodType(SyncHub._forget_message_id, hub)
        hub._commit_message_id = MethodType(SyncHub._commit_message_id, hub)
        hub._check_and_record_sig = MethodType(SyncHub._check_and_record_sig, hub)
        hub._forget_sig = MethodType(SyncHub._forget_sig, hub)
        hub._dispatch_result_lock = threading.Lock()
        hub._dispatch_results = {}
        hub._dispatch_waiters = {}
        hub.record_event_dispatch = MethodType(SyncHub.record_event_dispatch, hub)
        hub._take_event_dispatch_result = MethodType(
            SyncHub._take_event_dispatch_result, hub
        )
        hub.on_received = MethodType(SyncHub.on_received, hub)

        with patch.object(identity, "get_status", return_value=SimpleNamespace(paired=False)), \
                patch.object(
                    checkin_window.store,
                    "add_partner_record",
                    side_effect=[OSError("disk full"), None],
                ), patch("DesktopMailbox.sync.log_exception"):
            SyncHub._cloud_poll_loop(hub)
            SyncHub._cloud_poll_loop(hub)

        self.assertEqual(hub._cloud_last_ts, "new-cursor")
        hub._save_cursor.assert_called_once()
        self.assertIn("checkin-retry", hub._seen_message_ids)
        self.assertEqual(hub._cloud_schedule_poll.call_count, 2)

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
            "https://relay.example", ""
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
