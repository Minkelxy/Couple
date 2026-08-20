"""局域网双机同步：TCP 收发信件。

协议（结构化，避免大图 base64 膨胀）：
  4 字节大端 header_len
  header JSON: {meta, content_len, attachment_len, attachment_ext}
  content 字节（UTF-8 正文）
  attachment 字节（原始图片字节）

鉴权：
  - 旧版：无鉴权，只靠知道 peer_ip
  - 新版（若本机已完成配对向导）：meta 必须带 pk_fp + sig_b64，签名由 identity.sign_message 生成
    接收端 hub.on_received 用 identity.verify_message 做强制校验，不通过直接丢弃连接 + 不 emit 任何信号，
    解决公共 WiFi 下"任何人知道 IP 就能塞消息"的问题。

发送方寄出后会同时本地存一份 + 异步发给对方（LAN 和/或 Cloud）。
"""
from __future__ import annotations

import collections
import base64
import binascii
import hashlib
import json
import socket
import socketserver
import struct
import threading
import uuid
from datetime import datetime
from pathlib import Path

from PySide6.QtCore import QObject, Signal, Slot

import app_paths
import identity as idm
from common_utils import (
    AtomicJsonStore,
    MAX_ATTACHMENT_BYTES,
    atomic_write_bytes,
    log_exception,
    log_info,
    log_warning,
)

from . import letter_store
from .cloud_sync import CloudSyncClient
from .outbox import OutboxStore


DEFAULT_PORT = 52014
# 防御性上限：header JSON 不应过大；正文（文本）也需有界
_MAX_HEADER_BYTES = 64 * 1024
_MAX_CONTENT_BYTES = 1 * 1024 * 1024
_MAX_ATTACHMENT_EXT_BYTES = 32
_MAX_EVENT_TYPE_BYTES = 64
_MAX_ATTACHMENT_B64_LEN = 4 * ((MAX_ATTACHMENT_BYTES + 2) // 3)


class SyncSignalBridge(QObject):
    """Marshal SyncHub callbacks from worker threads into the GUI thread."""

    def __init__(
        self,
        on_send_result,
        on_letter_received,
        on_event_received,
        on_event_done=None,
    ) -> None:
        super().__init__()
        self._on_send_result = on_send_result
        self._on_letter_received = on_letter_received
        self._on_event_received = on_event_received
        self._on_event_done = on_event_done

    @Slot(bool, str)
    def send_result(self, ok: bool, message: str) -> None:
        self._on_send_result(ok, message)

    @Slot(str)
    def letter_received(self, letter_id: str) -> None:
        self._on_letter_received(letter_id)

    @Slot(str, dict, str, bytes, str)
    def event_received(
        self,
        event_type: str,
        meta: dict,
        content: str,
        attachment: bytes,
        attachment_ext: str,
    ) -> None:
        ok = True
        try:
            self._on_event_received(
                event_type, meta, content, attachment, attachment_ext
            )
        except Exception:
            ok = False
        if self._on_event_done is not None:
            self._on_event_done(meta, ok)


def _cursor_namespace(cfg: dict, mode: str) -> str:
    server = cfg.get("cloud_server", "")
    server = server.strip().rstrip("/") if isinstance(server, str) else ""
    pair_code = cfg.get("cloud_pair_code", "")
    pair_code = pair_code.strip() if isinstance(pair_code, str) else ""
    scope = f"pair:{pair_code}" if pair_code else "unpaired"
    if mode in ("cloud", "both") and server:
        status = idm.get_status()
        if status.paired and status.channel_id:
            scope = f"channel:{status.channel_id}"
    material = f"{server}\0{scope}".encode("utf-8")
    return hashlib.sha256(material).hexdigest()


def _ensure_uuid(cfg_dir: Path) -> str:
    """读取或生成本机 sender_id（UUID，用于 legacy 模式下云同步自收信去重）。"""
    path = cfg_dir / "sender_id.txt"
    if path.exists():
        try:
            txt = path.read_text(encoding="utf-8").strip()
            if txt:
                return txt
        except OSError:
            pass
    import uuid
    uid = uuid.uuid4().hex[:16]
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        atomic_write_bytes(path, uid.encode("ascii"))
    except OSError:
        pass
    return uid


def _recv_exact(sock: socket.socket, n: int) -> bytes | None:
    buf = b""
    while len(buf) < n:
        chunk = sock.recv(min(n - len(buf), 65536))
        if not chunk:
            return None
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
        self._heartbeat_timer: threading.Timer | None = None
        # stop() 后阻止轮询/心跳重新调度，避免退出后残留网络请求
        self._stopped = False
        # 云同步：本机 sender_id 用于自收信去重；游标持久化避免重启重复投递
        self._my_id: str = _ensure_uuid(app_paths.CONFIG_DIR)
        self._cursor_path: Path = app_paths.DATA_DIR / "cloud_cursor.json"
        self._cursor_store = AtomicJsonStore(self._cursor_path, {})
        mode = cfg.get("sync_mode", "lan")
        self._cursor_key = _cursor_namespace(cfg, mode)
        self._cloud_last_ts: str = self._load_cursor()
        self._cursor_lock = threading.Lock()
        self._outbox = OutboxStore(app_paths.DATA_DIR / "cloud_outbox.json")
        self._outbox_lock = threading.Lock()
        self._outbox_inflight: set[str] = set()
        self._message_seen_store = AtomicJsonStore(
            app_paths.DATA_DIR / "sync_message_ids.json", []
        )
        self._message_seen_lock = threading.Lock()
        self._message_seen_lru_max = 2048
        self._seen_message_ids: collections.OrderedDict[str, None] = collections.OrderedDict()
        self._pending_message_ids: set[str] = set()
        self._dispatch_result_lock = threading.Lock()
        self._dispatch_results: dict[str, bool] = {}
        stored_message_ids = self._message_seen_store.load()
        if isinstance(stored_message_ids, list):
            for message_id in stored_message_ids[-self._message_seen_lru_max:]:
                if isinstance(message_id, str) and message_id:
                    self._seen_message_ids[message_id] = None
        # 接收端签名 LRU 去重：容量 1024，线程安全（on_received 在 socket 线程与云轮询线程中可能并发）
        # 基于 meta.sig_b64 去重，防止同一签名消息被重复落盘/触发事件
        self._seen_sigs: collections.OrderedDict[str, None] = collections.OrderedDict()
        self._sig_lock = threading.Lock()
        self._sig_lru_max = 1024
        self._cloud_client: CloudSyncClient | None = None
        if mode in ("cloud", "both"):
            server = cfg.get("cloud_server", "").strip()
            pair_code = cfg.get("cloud_pair_code", "").strip()
            # New channel pairing does not need the legacy pair code.
            if server and (pair_code or idm.get_status().paired):
                self._cloud_client = CloudSyncClient(
                    server, pair_code
                )

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
            self._flush_cloud_outbox()
            started = True
            # 启动心跳广播（仅云模式有意义，告知对方本机在线）
            self._heartbeat_schedule()
        return started

    # ---------- 云游标持久化 ----------

    def _load_cursor(self) -> str:
        """启动时加载上一次的游标，避免重启重复投递。"""
        data = self._cursor_store.load()
        if not isinstance(data, dict):
            return ""
        record = data
        cursors = data.get("cursors")
        if isinstance(cursors, dict):
            record = cursors.get(self._cursor_key, {})
        cursor = record.get("cursor") if isinstance(record, dict) else None
        if isinstance(cursor, int) and cursor >= 0:
            return str(cursor)
        if isinstance(cursor, str) and cursor.isdigit():
            return cursor
        ts = record.get("server_ts", "") if isinstance(record, dict) else ""
        return ts if isinstance(ts, str) else ""

    def _save_cursor(self) -> None:
        """游标更新后落盘。多线程调用有锁。"""
        try:
            with self._cursor_lock:
                data = self._cursor_store.load()
                if not isinstance(data, dict):
                    data = {}
                cursors = data.get("cursors")
                if not isinstance(cursors, dict):
                    cursors = {}
                    # Migrate the pre-namespace top-level record once.
                    if "cursor" in data or "server_ts" in data:
                        cursors[self._cursor_key] = {
                            "cursor": data.get("cursor"),
                            "server_ts": data.get("server_ts", ""),
                        }
                cursors[self._cursor_key] = {
                    "server_ts": self._cloud_last_ts,
                    "cursor": (int(self._cloud_last_ts)
                               if self._cloud_last_ts.isdigit() else None),
                }
                self._cursor_store.save({"version": 2, "cursors": cursors})
        except OSError:
            pass

    def stop(self) -> None:
        self._stopped = True
        if self._heartbeat_timer is not None:
            self._heartbeat_timer.cancel()
            self._heartbeat_timer = None
        if self._cloud_timer is not None:
            self._cloud_timer.cancel()
            self._cloud_timer = None
        server = self._server
        self._server = None
        if server is not None:
            server.shutdown()
            server.server_close()
        thread = self._thread
        self._thread = None
        if thread is not None and thread is not threading.current_thread():
            thread.join(timeout=2)

    # ---------- 客户端 ----------

    def send_async(
        self,
        meta: dict,
        content: str,
        attachment: bytes | None,
        att_ext: str,
        silent: bool = False,
    ) -> None:
        # 统一注入 sender_id（send_event 已注入，但 compose_window 直接调 send_async 需补）
        if not isinstance(meta, dict):
            meta = {}
        if "sender_id" not in meta:
            meta["sender_id"] = self._my_id
        message_id = meta.get("message_id")
        if not isinstance(message_id, str) or not message_id:
            meta["message_id"] = uuid.uuid4().hex
        # 新版身份：发送前给消息做 Ed25519 签名（未配对也生成签名：legacy 接收方忽略即可，未来迁移平滑）
        att = attachment or b""
        signed_meta = idm.sign_message(dict(meta), content, att, att_ext)
        if signed_meta is meta:
            # sign_message 内部出错兜底（理论不会），就用原 meta
            pass
        else:
            meta = signed_meta
        mode = self._cfg.get("sync_mode", "lan")
        if mode in ("lan", "both"):
            host = self._cfg.get("peer_host", "").strip()
            if host:
                port = int(self._cfg.get("peer_port", DEFAULT_PORT))
                t = threading.Thread(
                    target=self._send_blocking,
                    args=(host, port, meta, content, att, att_ext, silent),
                    daemon=True,
                )
                t.start()
        if mode in ("cloud", "both") and self._cloud_client is not None:
            try:
                item_id = self._outbox.enqueue(meta, content, att, att_ext)
                self._start_cloud_outbox_item(item_id, silent=silent)
            except Exception:
                # The local letter is already durable; a failed outbox write
                # must not bubble into the UI thread or lose that local copy.
                log_exception("云 outbox 入队失败")
                if not silent:
                    self.send_result.emit(False, "云同步失败：本地发送队列无法写入")

    def send_event(
        self,
        event_type: str,
        payload: dict,
        attachment: bytes | None = None,
        att_ext: str = "",
        silent: bool = False,
    ) -> None:
        """通用事件发送：自动构造 meta={type, **payload, sent_at} 复用 send_async。

        注入 sender_id（本机 UUID），云同步自收信时可去重（不把自己发出的信再次落盘）。
        silent=True 时不 emit send_result（心跳等后台事件失败不应弹通知）。
        """
        meta = {
            "type": event_type,
            "sent_at": datetime.now().isoformat(timespec="seconds"),
            "sender_id": self._my_id,
        }
        meta.update(payload)
        self.send_async(meta, "", attachment, att_ext, silent=silent)

    def _send_blocking(
        self,
        host: str,
        port: int,
        meta: dict,
        content: str,
        attachment: bytes,
        att_ext: str,
        silent: bool = False,
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
            if not silent:
                self.send_result.emit(True, f"已同步到 {host}")
        except OSError as e:
            if not silent:
                self.send_result.emit(False, f"同步失败：{e}")

    def _cloud_send_blocking(
        self,
        meta: dict,
        content: str,
        attachment: bytes,
        att_ext: str,
        silent: bool = False,
        item_id: str | None = None,
    ) -> None:
        if self._cloud_client is None:
            return
        ok = False
        try:
            ok = self._cloud_client.send_letter(meta, content, attachment, att_ext)
        except Exception:
            log_exception("云同步发送线程异常")
        finally:
            if item_id is not None:
                try:
                    if ok:
                        self._outbox.remove(item_id)
                    else:
                        self._outbox.retry(item_id)
                except Exception:
                    # Keep the item for a later flush; a successful send is
                    # still safe to repeat because relay deduplicates message_id.
                    log_exception("云 outbox 状态持久化失败: %s", item_id)
                finally:
                    with self._outbox_lock:
                        self._outbox_inflight.discard(item_id)
        if not silent:
            if ok:
                self.send_result.emit(True, "已通过云中转寄出")
            else:
                self.send_result.emit(False, "云同步失败")

    def _start_cloud_outbox_item(self, item_id: str, silent: bool = True) -> None:
        with self._outbox_lock:
            if item_id in self._outbox_inflight:
                return
            self._outbox_inflight.add(item_id)
        started = False
        try:
            item = next((x for x in self._outbox.due() if x.get("id") == item_id), None)
            if item is None:
                return
            try:
                attachment_b64 = item.get("attachment_b64", "")
                if not isinstance(attachment_b64, str) or len(attachment_b64) > _MAX_ATTACHMENT_B64_LEN:
                    raise ValueError("attachment too large or invalid")
                attachment = base64.b64decode(attachment_b64, validate=True)
            except (binascii.Error, ValueError, TypeError):
                self._outbox.remove(item_id)
                return
            meta = item.get("meta")
            content = item.get("content", "")
            att_ext = item.get("attachment_ext", "")
            if not isinstance(meta, dict) or not isinstance(content, str) \
                    or not isinstance(att_ext, str):
                log_warning("丢弃格式损坏的云 outbox 项: %s", item_id)
                self._outbox.remove(item_id)
                return
            if len(content.encode("utf-8")) > _MAX_CONTENT_BYTES \
                    or len(att_ext) > _MAX_ATTACHMENT_EXT_BYTES:
                log_warning("丢弃超限的云 outbox 项: %s", item_id)
                self._outbox.remove(item_id)
                return
            threading.Thread(
                target=self._cloud_send_blocking,
                args=(meta, content, attachment, att_ext, silent, item_id),
                daemon=True,
            ).start()
            started = True
        except Exception:
            log_exception("启动云 outbox 项失败: %s", item_id)
        finally:
            if not started:
                with self._outbox_lock:
                    self._outbox_inflight.discard(item_id)

    def _flush_cloud_outbox(self) -> None:
        for item in self._outbox.due():
            self._start_cloud_outbox_item(item["id"])

    # ---------- 云轮询 ----------

    def _cloud_schedule_poll(self) -> None:
        interval = int(self._cfg.get("cloud_poll_interval_sec", 30))
        self._cloud_timer = threading.Timer(interval, self._cloud_poll_loop)
        self._cloud_timer.daemon = True
        self._cloud_timer.start()

    def _cloud_poll_loop(self) -> None:
        if self._stopped or self._cloud_client is None:
            return
        try:
            letters, server_ts = self._cloud_client.poll_letters(self._cloud_last_ts)
            if server_ts:
                # 仅更新内存游标，延迟落盘：必须等所有信件处理完才保存，
                # 否则中途崩溃会因游标已前进导致本批信件永久丢失。
                if not isinstance(server_ts, str):
                    log_warning("云轮询游标格式非法，保留旧游标")
                    server_ts = ""
            for letter in letters:
                try:
                    self.on_received(
                        letter.get("meta", {}),
                        letter.get("content", ""),
                        letter.get("attachment", b""),
                        letter.get("attachment_ext", ""),
                    )
                except Exception:
                    meta = letter.get("meta", {})
                    if isinstance(meta, dict):
                        self._forget_sig(meta.get("sig_b64", ""))
                    raise
            # 所有信件处理完毕后再落盘游标，保证下次轮询不会跳过本批信件；
            # 若 letters 为空但 server_ts 前进，也需保存游标。
            if server_ts:
                self._cloud_last_ts = server_ts
                self._save_cursor()
            self._flush_cloud_outbox()
        except Exception:
            log_exception("云轮询异常")
        finally:
            # 即使处理某封信时出错，也要继续调度下一次，避免云同步永久停止
            if not self._stopped:
                self._cloud_schedule_poll()

    # ---------- 心跳广播 ----------

    def _heartbeat_schedule(self) -> None:
        """每 30 秒向对方广播一次 heartbeat ping，告知本机在线。"""
        self._heartbeat_timer = threading.Timer(30, self._heartbeat_loop)
        self._heartbeat_timer.daemon = True
        self._heartbeat_timer.start()

    def _heartbeat_loop(self) -> None:
        if self._stopped:
            return
        # 发送心跳事件（不带附件、无正文）；静默发送，失败不弹通知
        self.send_event("ping", {"kind": "heartbeat"}, silent=True)
        self._heartbeat_schedule()

    # ---------- 收信 ----------

    def _check_and_record_sig(self, sig_b64: str) -> bool:
        """签名 LRU 去重：首次见到返回 True 并记入 LRU，重复返回 False。

        线程安全：on_received 在 socket 线程与云轮询线程中可能并发调用。
        容量上限 1024，超出时按 LRU 弹出最久未见的签名。
        空 sig_b64 不走 LRU（未配对模式无签名消息不应互相误杀），直接返回 True。
        """
        if not sig_b64:
            return True
        with self._sig_lock:
            if sig_b64 in self._seen_sigs:
                # 命中：移到末尾标记为最近使用（LRU），返回 False 表示重复
                self._seen_sigs.move_to_end(sig_b64)
                return False
            self._seen_sigs[sig_b64] = None
            if len(self._seen_sigs) > self._sig_lru_max:
                self._seen_sigs.popitem(last=False)  # 弹出最旧
            return True

    def _forget_sig(self, sig_b64: str) -> None:
        if not sig_b64:
            return
        with self._sig_lock:
            self._seen_sigs.pop(sig_b64, None)

    def record_event_dispatch(self, meta: dict, ok: bool) -> None:
        message_id = meta.get("message_id") if isinstance(meta, dict) else None
        if not isinstance(message_id, str) or not message_id:
            return
        with self._dispatch_result_lock:
            self._dispatch_results[message_id] = bool(ok)

    def _take_event_dispatch_result(self, message_id: str) -> bool | None:
        if not isinstance(message_id, str) or not message_id:
            return None
        with self._dispatch_result_lock:
            return self._dispatch_results.pop(message_id, None)

    def _check_and_record_message_id(self, message_id: str, persist: bool = True) -> bool:
        """Deduplicate non-letter events across LAN/cloud and client restarts."""
        if not isinstance(message_id, str) or not message_id or len(message_id) > 128:
            return True
        should_persist = False
        with self._message_seen_lock:
            if message_id in self._seen_message_ids:
                self._seen_message_ids.move_to_end(message_id)
                return False
            self._seen_message_ids[message_id] = None
            if len(self._seen_message_ids) > self._message_seen_lru_max:
                self._seen_message_ids.popitem(last=False)
            if not persist:
                self._pending_message_ids.add(message_id)
            should_persist = persist
        if should_persist:
            self._persist_message_ids()
        return True

    def _persist_message_ids(self) -> None:
        try:
            with self._message_seen_lock:
                items = [
                    message_id for message_id in self._seen_message_ids
                    if message_id not in self._pending_message_ids
                ]
            self._message_seen_store.save(items)
        except OSError:
            log_warning("同步事件去重表写入失败，当前进程内仍会去重")

    def _forget_message_id(self, message_id: str) -> None:
        with self._message_seen_lock:
            self._seen_message_ids.pop(message_id, None)
            self._pending_message_ids.discard(message_id)
        self._persist_message_ids()

    def _commit_message_id(self, message_id: str) -> None:
        with self._message_seen_lock:
            self._pending_message_ids.discard(message_id)
        self._persist_message_ids()

    def on_received(
        self,
        meta: dict,
        content: str,
        attachment: bytes,
        att_ext: str,
    ) -> None:
        """被 handler 在 socket 线程调用：按 meta.type 路由。

        新版身份前置校验（优先级最高）：
          1. 若我本地已配对（partner_pk 存在），对方消息必须带合法 Ed25519 签名 + 验签通过；
             不通过直接丢弃。解决公共 WiFi 邻居连进来乱塞消息的问题。
          2. 新版身份还顺带做一次"自收信去重"（pk_fp == 我自己的 pk_fp），所以 uuid self._my_id
             去重仅在未配对时生效（legacy 兜底）。

        路由：
          - 无 type 或 type=="letter"：走原 letter 流程（letter_store + letter_received）
          - 其他 type：emit event_received 信号，由 launcher 路由器分发到各模块
        """
        # 防御：meta 来自网络输入，非 dict 时直接丢弃，避免 .get() 抛 AttributeError
        if not isinstance(meta, dict):
            log_warning("收到非 dict 的 meta，已丢弃: %r", type(meta).__name__)
            return

        status = idm.get_status()
        if status.paired:
            # 1. 自收信（局域网也会自收吗？一般不会，不过统一按签名去重更稳）
            my_pk_bytes, _ = idm.ensure_identity()
            my_fp = idm._pk_fp(my_pk_bytes)  # type: ignore[attr-defined]
            if meta.get("pk_fp") == my_fp:
                return
            # 2. 签名校验：必须是 partner 发的
            if not idm.verify_message(meta, content, attachment or b"", att_ext or ""):
                log_warning(
                    "收到局域网消息但身份验签失败（可能是非对方的人连上了端口），已丢弃。"
                    "meta=%s",
                    {k: v for k, v in meta.items() if k != "sig_b64"},
                )
                return
            log_info("局域网消息签名验证通过，type=%s", meta.get("type", "letter"))
        else:
            # 未配对：legacy 模式仍用 UUID sender_id 做自收信去重
            sender = meta.get("sender_id")
            if sender and sender == self._my_id:
                return

        # 签名 LRU 去重：仅当 meta 含 sig_b64 时才查 LRU。
        # 未配对模式无签名消息跳过 LRU（避免空 sig_b64 互相误杀），由 message_id 幂等兜底。
        sig_b64 = meta.get("sig_b64", "")
        if sig_b64:
            if not self._check_and_record_sig(sig_b64):
                log_info(
                    "收到重复签名消息，已丢弃（LRU 去重）: type=%s",
                    meta.get("type", "letter"),
                )
                return

        msg_type = meta.get("type", "letter")
        if not isinstance(msg_type, str) or len(msg_type) > _MAX_EVENT_TYPE_BYTES:
            log_warning("收到非法同步事件类型，已丢弃: %r", msg_type)
            return
        if msg_type != "letter":
            message_id = meta.get("message_id", "")
            if not self._check_and_record_message_id(message_id, persist=False):
                log_info("收到重复同步事件，已丢弃: message_id=%s", meta.get("message_id"))
                return
            try:
                self.event_received.emit(msg_type, meta, content, attachment or b"", att_ext)
            except Exception:
                self._forget_message_id(message_id)
                forget_sig = getattr(self, "_forget_sig", None)
                if forget_sig is not None:
                    forget_sig(sig_b64)
                raise
            dispatch_result = self._take_event_dispatch_result(message_id)
            if dispatch_result is False:
                self._forget_message_id(message_id)
                self._forget_sig(sig_b64)
                raise OSError("同步事件主线程处理失败")
            self._commit_message_id(message_id)
            return
        try:
            deliver_at = datetime.fromisoformat(meta["deliver_at"])
        except (KeyError, TypeError, ValueError):
            deliver_at = datetime.now()
        try:
            new_meta = letter_store.write_letter(
                author=meta.get("author", "?"),
                recipient=meta.get("recipient", "?"),
                title=meta.get("title", "(无标题)"),
                content=content,
                deliver_at=deliver_at,
                attachment_bytes=attachment or None,
                attachment_ext=att_ext,
                message_id=meta.get("message_id"),
            )
            self.letter_received.emit(new_meta["id"])
        except Exception:
            forget_sig = getattr(self, "_forget_sig", None)
            if forget_sig is not None:
                forget_sig(sig_b64)
            raise


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
                if not isinstance(header, dict):
                    log_warning("同步 header 不是对象，关闭连接")
                    return
                meta = header["meta"]
                if not isinstance(meta, dict):
                    log_warning("同步 meta 不是对象，关闭连接")
                    return
                content_len = int(header.get("content_len", 0))
                att_len = int(header.get("attachment_len", 0))
                att_ext = header.get("attachment_ext", "")
                if not isinstance(att_ext, str) or len(att_ext) > _MAX_ATTACHMENT_EXT_BYTES:
                    log_warning("同步附件扩展名非法，关闭连接")
                    return
                # 防御：限制正文与附件大小，防止恶意/异常大包 OOM
                if content_len < 0 or content_len > _MAX_CONTENT_BYTES:
                    log_warning("拒绝超大正文（%d 字节），关闭连接", content_len)
                    return
                if att_len < 0 or att_len > MAX_ATTACHMENT_BYTES:
                    log_warning("拒绝超大附件（%d 字节），关闭连接", att_len)
                    return
                content_b = _recv_exact(self.request, content_len)
                if content_b is None:
                    log_warning("同步正文未接收完整，丢弃连接")
                    return
                content = content_b.decode("utf-8")
                att = b""
                if att_len:
                    att = _recv_exact(self.request, att_len)
                    if att is None:
                        log_warning("同步附件未接收完整，丢弃连接")
                        return
                hub.on_received(
                    meta, content, att, att_ext
                )
            except Exception:
                # 单次连接失败不影响服务端，但记录便于排查
                log_exception("同步连接处理异常")

    return _Handler
