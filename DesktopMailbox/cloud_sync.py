"""云中转同步客户端：通过 HTTP 中转服务器收发信件。

服务器需提供两个接口：
  POST /api/send   — 发送一封信
  GET  /api/poll   — 增量拉取新信件

所有方法均不抛异常，失败返回 False 或空值。
"""
from __future__ import annotations

import base64
import json
import urllib.parse
import urllib.request


class CloudSyncClient:
    def __init__(self, server: str, pair_code: str) -> None:
        self._server = server.rstrip("/")
        self._pair_code = pair_code

    def send_letter(
        self,
        meta: dict,
        content: str,
        attachment: bytes,
        att_ext: str,
    ) -> bool:
        """向 {server}/api/send POST JSON。

        请求体: {pair_code, meta, content_base64, attachment_base64, attachment_ext}
        失败返回 False，不抛异常。
        """
        try:
            payload = {
                "pair_code": self._pair_code,
                "meta": meta,
                "content_base64": base64.b64encode(
                    content.encode("utf-8")
                ).decode("ascii"),
                "attachment_base64": base64.b64encode(
                    attachment
                ).decode("ascii"),
                "attachment_ext": att_ext,
            }
            data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
            req = urllib.request.Request(
                f"{self._server}/api/send",
                data=data,
                headers={"Content-Type": "application/json"},
                method="POST",
            )
            with urllib.request.urlopen(req, timeout=10) as resp:
                resp.read()
            return True
        except Exception:
            return False

    def poll_letters(self, since_ts: str = "") -> tuple[list[dict], str]:
        """向 {server}/api/poll?pair_code={code}&since={ts} GET。

        返回 (letters, server_ts)。
        letters 每项: {meta: dict, content: str, attachment: bytes, attachment_ext: str}
        失败返回 ([], "")，不抛异常。
        """
        try:
            params = urllib.parse.urlencode({
                "pair_code": self._pair_code,
                "since": since_ts,
            })
            url = f"{self._server}/api/poll?{params}"
            req = urllib.request.Request(url, method="GET")
            with urllib.request.urlopen(req, timeout=10) as resp:
                raw = resp.read()
            data = json.loads(raw.decode("utf-8"))
            server_ts = data.get("server_ts", "")
            letters = []
            for item in data.get("letters", []):
                letters.append({
                    "meta": item.get("meta", {}),
                    "content": base64.b64decode(
                        item.get("content_base64", "")
                    ).decode("utf-8"),
                    "attachment": base64.b64decode(
                        item.get("attachment_base64", "")
                    ),
                    "attachment_ext": item.get("attachment_ext", ""),
                })
            return letters, server_ts
        except Exception:
            return [], ""
