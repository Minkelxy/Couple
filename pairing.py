"""配对客户端：配对流程状态机 + 与 relay_server 配对 API 交互。

两种入口（任意一端可发起/接受，只要两端角色对称）：

  1. 发起方：open_host_session()
     - 生成 6 位配对 token（可视无歧义）
     - 调 relay_server POST /api/pairing/declare 告诉服务端：这个 token 绑定我方公钥+昵称
     - 进入 WAITING，每 2s 轮询 GET /api/pairing/poll?token=X&role=host
       对方声明后，服务端回 {partner_pk_b64, partner_nickname, nonce}
     - 进入 SAFETY 阶段：UI 弹 6 位安全码，让用户请对方念，确认后
       调 POST /api/pairing/confirm {token, role=host, safety_confirmed: true, nonce,
       confirm_sig_b64 (签名该 nonce + partner_pk_b64 证明身份)}
     - 保存 partner_pk 到 identity，配对完成。

  2. 接受方：join_guest_session(token: str)
     - 调 relay_server POST /api/pairing/declare {token, role=guest, pk, nickname}
     - 每 2s 轮询：拿到 host_pk_b64 → 进入 SAFETY 阶段显示安全码，确认后
       调 confirm，服务端写 channel_id 绑定，两边完成。

服务端配对存储（内存，重启清空，超过 10 分钟 TTL 自动删）：
  pairing_state: {
    TOKEN: {
      host: {pk_b64, nickname, nonce, confirmed_ts?}
      guest: {pk_b64, nickname, nonce, confirmed_ts?}
      created_at: ts,
      ttl_sec: 600,
    }
  }

只有「双方 confirm」之后，服务端才会建立 channel 绑定：
  channel_state: {
    CHANNEL_ID: { members: [host_pk_b64, guest_pk_b64], created_at }
  }
并允许之后所有 /api/send /api/poll 以 channel_id 作为可信访问凭据。
"""
from __future__ import annotations

import json
import threading
import time
import urllib.parse
import urllib.request
from dataclasses import dataclass
from enum import Enum
from typing import Callable

import identity as idm
from common_utils import log_exception, log_info, log_warning


class PairingPhase(str, Enum):
    INIT = "init"
    WAITING_PARTNER = "waiting_partner"
    SHOW_SAFETY = "show_safety"      # 显示 6 位安全码，等用户点"对方说的一样"
    DONE = "done"
    FAILED = "failed"


@dataclass
class PairingProgress:
    phase: PairingPhase
    token: str | None = None              # 6 位可视 token（用于 UI 展示）
    partner_nickname: str | None = None   # 对方昵称（SHOW_SAFETY 后才有）
    safety_code: str | None = None        # 6 位十进制安全码（SHOW_SAFETY 后才有）
    error_message: str | None = None
    channel_id: str | None = None         # 成功后返回
    partner_pk_b64: str | None = None


ProgressCB = Callable[[PairingProgress], None]


def _post(server: str, path: str, payload: dict) -> dict | None:
    try:
        data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        req = urllib.request.Request(
            server.rstrip("/") + path,
            data=data,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=10) as resp:
            result = json.loads(resp.read().decode("utf-8"))
            if not isinstance(result, dict):
                log_warning("pairing POST %s 返回非对象 JSON", path)
                return None
            return result
    except Exception as e:
        log_exception("pairing POST %s 失败: %s", path, e)
        return None


def _get(server: str, path: str, params: dict) -> dict | None:
    try:
        qs = urllib.parse.urlencode(params)
        url = server.rstrip("/") + path + ("?" + qs if qs else "")
        req = urllib.request.Request(url, method="GET")
        with urllib.request.urlopen(req, timeout=10) as resp:
            result = json.loads(resp.read().decode("utf-8"))
            if not isinstance(result, dict):
                log_warning("pairing GET %s 返回非对象 JSON", path)
                return None
            return result
    except Exception as e:
        log_exception("pairing GET %s 失败: %s", path, e)
        return None


class PairingSession:
    """配对会话：每个向导实例一个。通过回调通知 UI 更新。"""

    def __init__(self, server: str, nickname: str, cb: ProgressCB) -> None:
        if not server:
            raise ValueError("未设置云中转服务器地址，无法走配对流程。请在设置-同步-云中转里填写服务器 URL。")
        self._server = server.rstrip("/")
        self._nickname = nickname or "我"
        self._cb = cb
        self._thread: threading.Thread | None = None
        self._stop = threading.Event()
        self._role: str | None = None   # "host" / "guest"
        self._token: str | None = None
        self._nonce_host: str | None = None
        self._nonce_guest: str | None = None

    # ---------- 公共入口 ----------

    def start_host(self) -> None:
        """发起方：生成 token → 声明 → 等对方。"""
        self._role = "host"
        self._token = idm.generate_pairing_token()
        self._emit(PairingProgress(PairingPhase.WAITING_PARTNER, token=self._token))
        self._thread = threading.Thread(target=self._run_host, daemon=True)
        self._thread.start()

    def start_guest(self, token: str) -> None:
        """接受方：输入 token → 声明 → 等 host。"""
        token = token.strip().upper()
        if not token or len(token) != 6:
            self._emit(PairingProgress(
                PairingPhase.FAILED,
                error_message="配对码格式错误：请输入 6 位字母数字（不含 I/L/0/O）",
            ))
            return
        self._role = "guest"
        self._token = token
        self._emit(PairingProgress(PairingPhase.WAITING_PARTNER, token=self._token))
        self._thread = threading.Thread(target=self._run_guest, daemon=True)
        self._thread.start()

    def cancel(self) -> None:
        self._stop.set()

    def confirm_safety(self, matched: bool) -> None:
        """用户在 UI 上点了"对方报的数字和我屏幕一样（是/否）"。"""
        if matched:
            self._thread = threading.Thread(target=self._confirm_loop, daemon=True)
            self._thread.start()
        else:
            self._emit(PairingProgress(
                PairingPhase.FAILED,
                error_message="安全码不匹配，可能是中间人攻击，请通过其他安全渠道重新核对后再试。",
            ))
            self._stop.set()

    # ---------- 内部流程 ----------

    def _emit(self, p: PairingProgress) -> None:
        try:
            self._cb(p)
        except Exception:
            log_exception("pairing progress cb 抛异常")

    def _declare(self, role: str, token: str) -> tuple[bool, str]:
        my_pk_b64 = idm.get_status().my_pk_b64
        resp = _post(self._server, "/api/pairing/declare", {
            "token": token,
            "role": role,
            "pk_b64": my_pk_b64,
            "nickname": self._nickname,
        })
        if not resp or not resp.get("ok"):
            msg = (resp or {}).get("message") or "服务器返回错误"
            return False, msg
        nonce = resp.get("nonce") or ""
        if role == "host":
            self._nonce_host = nonce
        else:
            self._nonce_guest = nonce
        log_info("pairing declare role=%s token=%s ok", role, token)
        return True, nonce

    def _wait_for_partner(self, role: str) -> tuple[bool, dict | None]:
        """轮询 partner 已经声明。返回 (ok, partner_declare)。"""
        deadline = time.time() + 600  # 10 分钟 TTL
        while time.time() < deadline and not self._stop.is_set():
            resp = _get(self._server, "/api/pairing/poll", {
                "token": self._token,
                "role": role,
                "step": "wait_partner",
            })
            if resp and resp.get("ok") and resp.get("partner_ready"):
                partner = resp.get("partner") or {}
                log_info("partner ready: %s", partner)
                return True, partner
            if resp and resp.get("message"):
                # 服务端提示过期/不存在
                return False, resp
            time.sleep(2)
        return False, {"message": "等待超时（10 分钟），请重新发起配对。"}

    def _run_host(self) -> None:
        ok, _msg = self._declare("host", self._token)  # type: ignore[arg-type]
        if not ok:
            self._emit(PairingProgress(
                PairingPhase.FAILED, token=self._token, error_message=_msg,
            ))
            return
        ok, partner = self._wait_for_partner("host")
        if not ok:
            self._emit(PairingProgress(
                PairingPhase.FAILED, token=self._token,
                error_message=(partner or {}).get("message") or "等待对方失败",
            ))
            return
        self._enter_safety(partner)

    def _run_guest(self) -> None:
        ok, _msg = self._declare("guest", self._token)  # type: ignore[arg-type]
        if not ok:
            self._emit(PairingProgress(
                PairingPhase.FAILED, token=self._token, error_message=_msg,
            ))
            return
        ok, partner = self._wait_for_partner("guest")
        if not ok:
            self._emit(PairingProgress(
                PairingPhase.FAILED, token=self._token,
                error_message=(partner or {}).get("message") or "等待发起方失败",
            ))
            return
        self._enter_safety(partner)

    def _enter_safety(self, partner_declare: dict) -> None:
        pk_b64 = partner_declare.get("pk_b64")
        nickname = partner_declare.get("nickname") or "对方"
        if not pk_b64:
            self._emit(PairingProgress(PairingPhase.FAILED, error_message="对方公钥缺失"))
            return
        try:
            safety = idm.safety_code_for_pending(pk_b64)
        except Exception as e:
            log_exception("safety_code_for_pending 失败")
            self._emit(PairingProgress(PairingPhase.FAILED, error_message=str(e)))
            return
        self._pending_partner_pk_b64 = pk_b64
        self._pending_partner_nickname = nickname
        self._emit(PairingProgress(
            PairingPhase.SHOW_SAFETY,
            token=self._token,
            partner_nickname=nickname,
            safety_code=safety,
        ))

    def _confirm_payload(self) -> dict:
        """签名 nonce + partner_pk，用于服务端确认这个角色真的是当初 declare 那个人。"""
        pk, sk = idm.ensure_identity()
        # 签名原文：role + "|" + token + "|" + nonce_mine + "|" + partner_pk_b64
        my_nonce = self._nonce_host if self._role == "host" else self._nonce_guest
        plain = (
            f"{self._role}|{self._token}|{my_nonce or ''}|"
            f"{getattr(self, '_pending_partner_pk_b64', '') or ''}"
        ).encode("utf-8")
        sig = sk.sign(plain)
        return {
            "token": self._token,
            "role": self._role,
            "safety_confirmed": True,
            "my_nonce": my_nonce,
            "sig_b64": idm._b64e(sig),  # type: ignore[attr-defined]
        }

    def _confirm_loop(self) -> None:
        # 先 POST confirm（我方这一半），再轮询等对方也 confirm
        _post(self._server, "/api/pairing/confirm", self._confirm_payload())
        deadline = time.time() + 120  # 120s 留给用户念数字
        while time.time() < deadline and not self._stop.is_set():
            resp = _get(self._server, "/api/pairing/poll", {
                "token": self._token,
                "role": self._role,
                "step": "both_confirmed",
            })
            if resp and resp.get("ok") and resp.get("both_confirmed"):
                self._finish_success()
                return
            if resp and resp.get("message") and resp.get("fatal"):
                # 服务器端把配对记录移除了：
                #  - 要么 TTL 到期（失败）
                #  - 要么双方都 confirm 了，token 已经被 pop（成功，只是对端先拿到了）
                msg = resp.get("message") or ""
                pk_b64 = getattr(self, "_pending_partner_pk_b64", None)
                if pk_b64 and (
                    "不存在" in msg and "已过期" in msg  # "配对记录不存在（可能已过期）"就是 410
                    or "不存在或已过期" in msg
                ):
                    # 已拿到对方公钥，说明之前握手已经走通；走到 fatal 410 通常是对端先拿了 both_confirmed
                    # 导致服务器把 token 删了；此时本地直接 save_partner 视为成功
                    self._finish_success()
                    return
                self._emit(PairingProgress(PairingPhase.FAILED, error_message=msg))
                return
            time.sleep(2)
        # 超时：对方没在 120s 内点"一致"
        self._emit(PairingProgress(
            PairingPhase.FAILED,
            error_message="对方未在 120 秒内确认安全码，配对已取消。",
        ))

    def _finish_success(self) -> None:
        pk_b64 = getattr(self, "_pending_partner_pk_b64", None)
        nickname = getattr(self, "_pending_partner_nickname", "对方")
        if not pk_b64:
            self._emit(PairingProgress(
                PairingPhase.FAILED, error_message="缺少对方公钥，无法完成配对",
            ))
            return
        try:
            status = idm.save_partner(pk_b64, nickname)
            self._emit(PairingProgress(
                PairingPhase.DONE,
                token=self._token,
                partner_nickname=nickname,
                safety_code=status.safety_code,
                channel_id=status.channel_id,
                partner_pk_b64=pk_b64,
            ))
            log_info("pairing 成功，channel=%s", status.channel_id)
        except Exception as e:
            log_exception("save_partner 失败")
            self._emit(PairingProgress(
                PairingPhase.FAILED, error_message=f"保存对方信息失败：{e}",
            ))
