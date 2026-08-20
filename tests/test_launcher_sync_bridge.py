import time
import unittest

from PySide6.QtCore import QCoreApplication, QThread, Qt, Signal

from DesktopMailbox.sync import SyncSignalBridge


class _Worker(QThread):
    event = Signal(str, dict, str, bytes, str)

    def run(self):
        self.event.emit("ping", {"kind": "heartbeat"}, "", b"", "")


class LauncherSyncBridgeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QCoreApplication.instance() or QCoreApplication([])

    def test_worker_signal_is_delivered_on_main_thread(self):
        main_thread = QThread.currentThread()
        received = []
        completed = []
        bridge = SyncSignalBridge(
            lambda *_: None,
            lambda *_: None,
            lambda *args: received.append(QThread.currentThread()),
            lambda meta, ok: completed.append((meta, ok)),
        )
        worker = _Worker()
        worker.event.connect(bridge.event_received, Qt.ConnectionType.QueuedConnection)
        worker.start()

        deadline = time.monotonic() + 2
        while not received and time.monotonic() < deadline:
            self.app.processEvents()
            time.sleep(0.005)
        worker.wait(2000)

        self.assertEqual(len(received), 1)
        self.assertIs(received[0], main_thread)
        self.assertEqual(completed, [({"kind": "heartbeat"}, True)])

    def test_event_handler_failure_is_reported_to_sync_thread(self):
        completed = []
        bridge = SyncSignalBridge(
            lambda *_: None,
            lambda *_: None,
            lambda *_: (_ for _ in ()).throw(OSError("disk full")),
            lambda meta, ok: completed.append((meta, ok)),
        )

        bridge.event_received("checkin", {"message_id": "retry-1"}, "", b"", "")

        self.assertEqual(completed, [({"message_id": "retry-1"}, False)])


if __name__ == "__main__":
    unittest.main()
