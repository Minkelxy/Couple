import time
import unittest

from PySide6.QtCore import QCoreApplication, QThread, Qt, Signal

from launcher import _MainThreadSyncBridge


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
        bridge = _MainThreadSyncBridge(
            lambda *_: None,
            lambda *_: None,
            lambda *args: received.append(QThread.currentThread()),
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


if __name__ == "__main__":
    unittest.main()
