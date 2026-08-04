"""局域网双机同步：TCP 收发信件。

协议（结构化，避免大图 base64 膨胀）：
  4 字节大端 header_len
  header JSON: {meta, content_len, attachment_len, attachment_ext}
  content 字节（UTF-8 正文）
  attachment 字节（原始图片字节）

传输明文（局域网内）；对方收到后用本地 Fernet key 重新加密落盘。
发送方寄出后会同时本地存一份 + 异步发给对方。
"""
from __future__ import annotations

import json
import socket
import socketserver
import struct
import threading
from datetime import datetime
from pathlib import Path

from PySide6.QtCore import QObject, Signal

from common_utils import MAX_ATTACHMENT_BYTES, log_exception, log_warning

from . import letter_store
from .cloud_sync import CloudSyncClient


DEFAULT_PORT = 52014
# 防御性上限：header JSON 不应过大；正文（文本）也需有界
_MAX_HEADER_BYTES = 64 * 1024
_MAX_CONTENT_BYTES = 1 * 1024 * 1024


def _recv_exact(sock: socket.socket, n: int) -> bytes:
    buf = b""
    while len(buf) < n:
        chunk = sock.recv(min(n - len(buf), 65536))
        if not chunk:
            return b""
        buf += chunk
    return buf


class SyncHub(QObject):
    """同步中枢：启动监听服务 + 异步发送 + 跨线程通知。"""

    letter_received = Signal(str)   # 收到信件 id（socket 线程 emit）
    send_result = Signal(bool, str)  # 发送结果 (ok, message)
    # 非信件类型消息（type, meta, content, attachment, att_ext）
    # type 取值：checkin/map/movie/photo/ping/gomoku_move/gomoku_ctrl 等
    event_received = Signal(str, dict, str, bytes, str)

    def __init__(self, cfg: dict) -> None:
        super().__init__()
        self._cfg = cfg
        self._server: socketserver.ThreadingTCPServer | None = None
        self._thread: threading.Thread | None = None
        self._cloud_timer: threading.Timer | None = None
        self._cloud_last_ts: str = ""
        self._heartbeat_timer: threading.Timer | None = None
        mode = cfg.get("sync_mode", "lan")
        self._cloud_client: CloudSyncClient | None = None
        if mode in ("cloud", "both"):
            server = cfg.get("cloud_server", "").strip()
            pair_code = cfg.get("cloud_pair_code", "").strip()
            if server and pair_code:
                self._cloud_client = CloudSyncClient(server, pair_code)

    # ---------- 服务端 ----------

    def start(self) -> bool:
        started = False
        mode = self._cfg.get("sync_mode", "lan")
        if mode in ("lan", "both") and self._cfg.get("sync_enabled", False):
            port = int(self._cfg.get("sync_port", DEFAULT_PORT))
            handler_cls = _make_handler(self)
            try:
                self._server = socketserver.ThreadingTCPServer(
                    ("0.0.0.0", port), handler_cls
                )
                self._server.daemon_threads = True
            except OSError:
                # 端口被占用
                self.send_result.emit(False, f"监听端口 {port} 被占用")
            else:
                self._thread = threading.Thread(
                    target=self._server.serve_forever, daemon=True
                )
                self._thread.start()
                started = True
        if mode in ("cloud", "both") and self._cloud_client is not None:
            self._cloud_schedule_poll()
            started = True
            # 启动心跳广播（仅云模式有意义，告知对方本机在线）
            self._heartbeat_schedule()
        return started

    def stop(self) -> None:
        if self._heartbeat_timer is not None:
            self._heartbeat_timer.cancel()
            self._heartbeat_timer = None
        if self._cloud_timer is not None:
            self._cloud_timer.cancel()
            self._cloud_timer = None
        if self._server is not None:
            self._server.shutdown()
            self._server = None

    # ---------- 客户端 ----------

    def send_async(
        self,
        meta: dict,
        content: str,
        attachment: bytes | None,
        att_ext: str,
    ) -> None:
        mode = self._cfg.get("sync_mode", "lan")
        if mode in ("lan", "both"):
            host = self._cfg.get("peer_host", "").strip()
            if host:
                port = int(self._cfg.get("peer_port", DEFAULT_PORT))
                t = threading.Thread(
                    target=self._send_blocking,
                    args=(host, port, meta, content, attachment or b"", att_ext),
                    daemon=True,
                )
                t.start()
        if mode in ("cloud", "both") and self._cloud_client is not None:
            t = threading.Thread(
                target=self._cloud_send_blocking,
                args=(meta, content, attachment or b"", att_ext),
                daemon=True,
            )
            t.start()

    def send_event(
        self,
        event_type: str,
        payload: dict,
        attachment: bytes | None = None,
        att_ext: str = "",
    ) -> None:
        """通用事件发送：自动构造 meta={type, **payload, sent_at} 复用 send_async。"""
        meta = {"type": event_type, "sent_at": datetime.now().isoformat(timespec="seconds")}
        meta.update(payload)
        self.send_async(meta, "", attachment, att_ext)

    def _send_blocking(
        self,
        host: str,
        port: int,
        meta: dict,
        content: str,
        attachment: bytes,
        att_ext: str,
    ) -> None:
        try:
            with socket.create_connection((host, port), timeout=4) as s:
                content_b = content.encode("utf-8")
                header = {
                    "meta": meta,
                    "content_len": len(content_b),
                    "attachment_len": len(attachment),
                    "attachment_ext": att_ext,
                }
                header_b = json.dumps(header, ensure_ascii=False).encode("utf-8")
                s.sendall(struct.pack(">I", len(header_b)) + header_b)
                s.sendall(content_b)
                if attachment:
                    s.sendall(attachment)
            self.send_result.emit(True, f"已同步到 {host}")
        except OSError as e:
            self.send_result.emit(False, f"同步失败：{e}")

    def _cloud_send_blocking(
        self,
        meta: dict,
        content: str,
        attachment: bytes,
        att_ext: str,
    ) -> None:
        if self._cloud_client is None:
            return
        ok = self._cloud_client.send_letter(meta, content, attachment, att_ext)
        if ok:
            self.send_result.emit(True, "已通过云中转寄出")
        else:
            self.send_result.emit(False, "云同步失败")

    # ---------- 云轮询 ----------

    def _cloud_schedule_poll(self) -> None:
        interval = int(self._cfg.get("cloud_poll_interval_sec", 30))
        self._cloud_timer = threading.Timer(interval, self._cloud_poll_loop)
        self._cloud_timer.daemon = True
        self._cloud_timer.start()

    def _cloud_poll_loop(self) -> None:
        if self._cloud_client is None:
            return
        letters, server_ts = self._cloud_client.poll_letters(self._cloud_last_ts)
        if server_ts:
            self._cloud_last_ts = server_ts
        for letter in letters:
            self.on_received(
                letter.get("meta", {}),
                letter.get("content", ""),
                letter.get("attachment", b""),
                letter.get("attachment_ext", ""),
            )
        self._cloud_schedule_poll()

    # ---------- 心跳广播 ----------

    def _heartbeat_schedule(self) -> None:
        """每 30 秒向对方广播一次 heartbeat ping，告知本机在线。"""
        self._heartbeat_timer = threading.Timer(30, self._heartbeat_loop)
        self._heartbeat_timer.daemon = True
        self._heartbeat_timer.start()

    def _heartbeat_loop(self) -> None:
        # 发送心跳事件（不带附件、无正文）
        self.send_event("ping", {"kind": "heartbeat"})
        self._heartbeat_schedule()

    # ---------- 收信 ----------

    def on_received(
        self,
        meta: dict,
        content: str,
        attachment: bytes,
        att_ext: str,
    ) -> None:
        """被 handler 在 socket 线程调用：按 meta.type 路由。

        - 无 type 或 type=="letter"：走原 letter 流程（letter_store + letter_received）
        - 其他 type：emit event_received 信号，由 launcher 路由器分发到各模块
        """
        msg_type = meta.get("type", "letter")
        if msg_type != "letter":
            self.event_received.emit(msg_type, meta, content, attachment or b"", att_ext)
            return
        try:
            deliver_at = datetime.fromisoformat(meta["deliver_at"])
        except (KeyError, ValueError):
            deliver_at = datetime.now()
        new_meta = letter_store.write_letter(
            author=meta.get("author", "?"),
            recipient=meta.get("recipient", "?"),
            title=meta.get("title", "(无标题)"),
            content=content,
            deliver_at=deliver_at,
            attachment_bytes=attachment or None,
            attachment_ext=att_ext,
        )
        self.letter_received.emit(new_meta["id"])


def _make_handler(hub: SyncHub):
    class _Handler(socketserver.BaseRequestHandler):
        def handle(self) -> None:
            try:
                hdr_len_b = _recv_exact(self.request, 4)
                if not hdr_len_b:
                    return
                n = struct.unpack(">I", hdr_len_b)[0]
                # 防御：限制 header 大小，避免恶意超大 header 撑爆内存
                if n <= 0 or n > _MAX_HEADER_BYTES:
                    log_warning("拒绝超大同步 header（%d 字节），关闭连接", n)
                    return
                hdr_b = _recv_exact(self.request, n)
                if not hdr_b:
                    return
                header = json.loads(hdr_b.decode("utf-8"))
                meta = header["meta"]
                content_len = int(header.get("content_len", 0))
                att_len = int(header.get("attachment_len", 0))
                # 防御：限制正文与附件大小，防止恶意/异常大包 OOM
                if content_len < 0 or content_len > _MAX_CONTENT_BYTES:
                    log_warning("拒绝超大正文（%d 字节），关闭连接", content_len)
                    return
                if att_len < 0 or att_len > MAX_ATTACHMENT_BYTES:
                    log_warning("拒绝超大附件（%d 字节），关闭连接", att_len)
                    return
                content_b = _recv_exact(self.request, content_len)
                content = content_b.decode("utf-8")
                att = b""
                if att_len:
                    att = _recv_exact(self.request, att_len)
                hub.on_received(
                    meta, content, att, header.get("attachment_ext", "")
                )
            except Exception:
                # 单次连接失败不影响服务端，但记录便于排查
                log_exception("同步连接处理异常")

    return _Handler
