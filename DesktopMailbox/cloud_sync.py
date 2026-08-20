"""云中转同步客户端：通过 HTTP 中转服务器收发信件。

支持两种认证模式（自动选择）：
  1. 新公钥身份模式（推荐）：已完成配对向导时使用
     - 按 identity.get_status().channel_id 作为 bucket key
     - 每次发送前调用 identity.sign_message() 在 meta 里注入 pk_fp + sig_b64，服务端 Ed25519 验签
     - 每次 poll 用私钥签一段 `poll_auth|channel_id|pk_fp|since`，服务端验签才回数据
  2. legacy pair_code 模式（过渡期）：未配对时保留原行为
     - 用 pair_code 做桶；不做签名，依赖 pair_code 保密性

服务器接口：
  POST /api/send   — 发送一封信
  GET  /api/poll   — 增量拉取新信件
"""
from __future__ import annotations

import base64
import binascii
import json
import urllib.parse
import urllib.request
from datetime import datetime

import identity as idm
from common_utils import MAX_ATTACHMENT_BYTES, log_exception, log_info, log_warning


_MAX_CONTENT_BYTES = 2 * 1024 * 1024
_MAX_ATTACHMENT_B64_LEN = 4 * ((MAX_ATTACHMENT_BYTES + 2) // 3)
_MAX_ATTACHMENT_EXT_BYTES = 32


def _normalize_server_ts(value) -> str:
    if not isinstance(value, str) or not value:
        return ""
    try:
        datetime.fromisoformat(value)
    except ValueError:
        return ""
    return value


def _normalize_cursor(value) -> str:
    if isinstance(value, int) and value >= 0:
        return str(value)
    if isinstance(value, str) and value.isdigit():
        return value
    return ""


def _b64e(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


class CloudSyncClient:
    def __init__(self, server: str, pair_code: str, sig_dedup_fn=None) -> None:
        self._server = server.rstrip("/")
        self._pair_code = pair_code  # legacy 兜底：用户未配对时仍可用
        # 接收端签名 LRU 去重回调：由 SyncHub 注入，云轮询与局域网收信共享同一 LRU
        self._sig_dedup_fn = sig_dedup_fn

    # ---------- 发送 ----------

    def send_letter(
        self,
        meta: dict,
        content: str,
        attachment: bytes,
        att_ext: str,
    ) -> bool:
        """失败返回 False，不抛异常。"""
        try:
            payload = self._build_send_payload(meta, content, attachment or b"", att_ext or "")
            data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
            req = urllib.request.Request(
                f"{self._server}/api/send",
                data=data,
                headers={"Content-Type": "application/json"},
                method="POST",
            )
            with urllib.request.urlopen(req, timeout=10) as resp:
                body = resp.read()
            try:
                result = json.loads(body.decode("utf-8"))
            except (ValueError, UnicodeDecodeError):
                log_warning("云同步发送收到非 JSON 响应，保留 outbox 重试")
                return False
            if not isinstance(result, dict) or result.get("ok") is not True:
                error = result.get("error") if isinstance(result, dict) else "invalid response"
                log_warning("云同步发送被服务端拒绝: %s", error)
                return False
            return True
        except Exception:
            log_exception("云同步发送失败")
            return False

    def _build_send_payload(
        self, meta: dict, content: str, attachment: bytes, att_ext: str
    ) -> dict:
        status = idm.get_status()
        # 统一先对 meta 签名（无论 channel 还是 legacy 模式都签，方便将来完全去掉 legacy）
        signed_meta = idm.sign_message(dict(meta), content, attachment, att_ext)
        content_b64 = base64.b64encode(content.encode("utf-8")).decode("ascii")
        attach_b64 = base64.b64encode(attachment or b"").decode("ascii")
        payload = {
            "meta": signed_meta,
            "content_base64": content_b64,
            "attachment_base64": attach_b64,
            "attachment_ext": att_ext,
        }
        if status.paired and status.channel_id and self._server:
            payload["channel_id"] = status.channel_id
            log_info("send via channel_id=%s", status.channel_id)
        else:
            if not self._pair_code:
                raise RuntimeError("未配对，且配置里没有 legacy pair_code 可用。请先在设置里完成配对向导。")
            payload["pair_code"] = self._pair_code
        return payload

    # ---------- 拉取 ----------

    def poll_letters(self, since_ts: str = "") -> tuple[list[dict], str]:
        """返回 (letters, server_ts)。失败返回 ([], "")。"""
        try:
            url = self._build_poll_url(since_ts or "")
            req = urllib.request.Request(url, method="GET")
            with urllib.request.urlopen(req, timeout=10) as resp:
                raw = resp.read()
            data = json.loads(raw.decode("utf-8"))
            server_cursor = _normalize_cursor(data.get("server_cursor"))
            server_ts = server_cursor or _normalize_server_ts(data.get("server_ts", ""))
            letters: list[dict] = []
            for item in data.get("letters", []):
                try:
                    parsed = self._parse_one_inbound(item)
                    if parsed is None:
                        continue  # 被身份校验丢弃
                    letters.append(parsed)
                except Exception:
                    log_exception("云中转坏信件解析失败，已跳过")
                    continue
            return letters, server_ts
        except Exception:
            log_exception("云同步轮询失败")
            return [], ""

    def _build_poll_url(self, since_ts: str) -> str:
        status = idm.get_status()
        params: dict[str, str] = {}
        if since_ts.isdigit():
            params["cursor"] = since_ts
        else:
            params["since"] = since_ts
        if status.paired and status.channel_id and self._server:
            params["channel_id"] = status.channel_id
            my_pk_bytes, sk = idm.ensure_identity()
            pk_fp = idm._pk_fp(my_pk_bytes)  # type: ignore[attr-defined]
            plain = f"poll_auth|{status.channel_id}|{pk_fp}|{since_ts}".encode("utf-8")
            params["pk_fp"] = pk_fp
            params["sig_b64"] = _b64e(sk.sign(plain))
        else:
            if not self._pair_code:
                raise RuntimeError("未配对，且配置里没有 legacy pair_code 可用。请先在设置里完成配对向导。")
            params["pair_code"] = self._pair_code
        qs = urllib.parse.urlencode(params)
        return f"{self._server}/api/poll?{qs}"

    def _parse_one_inbound(self, item: dict) -> dict | None:
        if not isinstance(item, dict):
            return None
        att_b64 = item.get("attachment_base64", "") or ""
        if not isinstance(att_b64, str):
            return None
        if len(att_b64) > _MAX_ATTACHMENT_B64_LEN:
            log_warning("云中转信件附件过大（base64 %d 字节），已丢弃", len(att_b64))
            return None
        try:
            att = base64.b64decode(att_b64, validate=True)
        except (binascii.Error, ValueError):
            return None
        if len(att) > MAX_ATTACHMENT_BYTES:
            return None
        content_b64 = item.get("content_base64", "") or ""
        if not isinstance(content_b64, str):
            return None
        if len(content_b64) > 4 * ((_MAX_CONTENT_BYTES + 2) // 3):
            return None
        try:
            content = base64.b64decode(content_b64, validate=True).decode("utf-8")
        except (binascii.Error, UnicodeDecodeError, ValueError):
            return None
        meta = item.get("meta", {})
        if not isinstance(meta, dict):
            return None
        att_ext = item.get("attachment_ext", "") or ""
        if not isinstance(att_ext, str) or len(att_ext) > _MAX_ATTACHMENT_EXT_BYTES:
            return None
        # 身份校验：如果本地已经配对 partner_pk，必须验；否则可能是 legacy 自发自收+uuid 去重过滤
        status = idm.get_status()
        if status.paired:
            # 自收信：pk_fp 是我自己的（配对模式下也会被 relay 收到）
            my_pk_bytes, _sk = idm.ensure_identity()
            my_fp = idm._pk_fp(my_pk_bytes)  # type: ignore[attr-defined]
            if meta.get("pk_fp") == my_fp:
                return None  # 自己发的，跳过
            if not idm.verify_message(meta, content, att, att_ext):
                log_warning("云中转收到的信件验签失败，丢弃。meta=%s", {
                    k: v for k, v in meta.items() if k != "sig_b64"
                })
                return None
            # 签名 LRU 去重：复用 SyncHub 的 LRU，与局域网收信共享同一去重表
            # 仅当注入了去重回调且 meta 含 sig_b64 时才查 LRU
            if self._sig_dedup_fn is not None:
                sig_b64 = meta.get("sig_b64", "")
                if sig_b64 and not self._sig_dedup_fn(sig_b64):
                    log_info(
                        "云中转信件重复签名，已丢弃（LRU 去重）: type=%s",
                        meta.get("type", "letter"),
                    )
                    return None
        return {
            "meta": meta,
            "content": content,
            "attachment": att,
            "attachment_ext": att_ext,
        }
