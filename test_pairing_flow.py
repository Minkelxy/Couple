"""端到端自测：启动 relay_server，模拟 host+guest 完成配对并校验签名链路。
用法：python test_pairing_flow.py   （无输出=成功，非零退出=失败）"""
from __future__ import annotations

import os
import socket
import subprocess
import sys
import tempfile
import time
import threading
import json
from pathlib import Path


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def main() -> int:
    tmp = Path(tempfile.mkdtemp(prefix="couple_pair_test_"))
    server_root = Path(__file__).parent.resolve()
    tmp_root = tmp / "appdata"
    tmp_root.mkdir(parents=True, exist_ok=True)
    base_env = os.environ.copy()
    base_env["HOME"] = str(tmp_root)
    base_env["APPDATA"] = str(tmp_root)

    # 启动 relay_server（从临时目录运行，改 _DB_PATH + Flask port=PORT 环境变量）
    port = _free_port()
    db_path = tmp / "letters.db"
    server_py = tmp / "relay_server_run.py"
    orig = (server_root / "relay_server.py").read_text(encoding="utf-8")
    patched = orig \
        .replace(
            '_DB_PATH = Path(__file__).parent / "letters.db"',
            f'_DB_PATH = Path(r"{db_path}")',
        ) \
        .replace(
            'app.run(host="0.0.0.0", port=5000, debug=False)',
            f'app.run(host="127.0.0.1", port={port}, debug=False)',
        )
    server_py.write_text(patched, encoding="utf-8")
    proc = subprocess.Popen(
        [sys.executable, str(server_py)],
        cwd=str(tmp),
        env=base_env,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.PIPE,
    )
    server_url = f"http://127.0.0.1:{port}"
    try:
        import urllib.request
        for _ in range(80):
            if proc.poll() is not None:
                sys.stderr.write("relay_server died. stderr:\n")
                sys.stderr.write(proc.stderr.read().decode()[:4000])
                return 2
            try:
                with urllib.request.urlopen(server_url + "/health", timeout=1):
                    break
            except Exception:
                time.sleep(0.25)
        else:
            sys.stderr.write("server not up\n"); return 3

        root_a = tmp / "a"; root_a.mkdir()
        root_b = tmp / "b"; root_b.mkdir()
        runner = tmp / "runner.py"
        runner.write_text(
            r"""
import sys, os, json, time
sys.path.insert(0, sys.argv[1])
os.environ["APPDATA"] = sys.argv[2]
os.environ["HOME"] = sys.argv[2]
mode = sys.argv[3]
token = sys.argv[4] if len(sys.argv) > 4 else ""
server_url = sys.argv[5]
import pairing as pr

results = []
def cb(p):
    from pairing import PairingPhase
    phase_s = p.phase.value if isinstance(p.phase, PairingPhase) else str(p.phase)
    d = {
        "phase": phase_s,
        "token": p.token,
        "partner_nickname": p.partner_nickname,
        "safety_code": p.safety_code,
        "error": p.error_message,
        "channel_id": p.channel_id,
        "partner_pk_b64": bool(p.partner_pk_b64),
    }
    results.append(d)
    sys.stdout.write("PROGRESS:" + json.dumps(d, ensure_ascii=False) + "\n")
    sys.stdout.flush()

nick = {"host": "小鹿", "guest": "阿树"}[mode]
try:
    import app_paths
    app_paths.ensure_dirs()
    import identity as idm
    idm.ensure_identity()  # 预生成密钥 & key.key 都落盘
    s = pr.PairingSession(server_url, nick, cb)
    if mode == "host":
        s.start_host()
    else:
        s.start_guest(token)
except Exception as e:
    sys.stderr.write(f"[{mode}] start exc: {e}\n")
    import traceback; traceback.print_exc()
    sys.exit(11)

# 同步执行 120s 内必须结束
deadline = time.time() + 120
last_phase = "init"
confirmed = False
while time.time() < deadline:
    if results:
        last_phase = results[-1]["phase"]
    if last_phase == "show_safety" and not confirmed:
        time.sleep(0.3)  # 等对端先也 show_safety，避免 race
        s.confirm_safety(True)
        confirmed = True
    if last_phase in ("done", "failed"):
        break
    time.sleep(0.2)
""",
            encoding="utf-8",
        )
        collected: dict[str, list] = {"a": [], "b": []}

        def collect(stream, key):
            for line in stream:
                if line.startswith("PROGRESS:"):
                    try:
                        collected[key].append(json.loads(line[len("PROGRESS:"):]))
                    except Exception:
                        pass
        a = subprocess.Popen(
            [sys.executable, str(runner), str(server_root), str(root_a), "host", "", server_url],
            stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
        )
        # 等 host 给出 token
        token = None
        for _ in range(400):
            line = a.stdout.readline()
            if not line and a.poll() is not None:
                break
            if line.startswith("PROGRESS:"):
                d = json.loads(line[len("PROGRESS:"):])
                collected["a"].append(d)
                if d.get("token") and d["phase"] == "waiting_partner":
                    token = d["token"]
                    break
            time.sleep(0.02)
        if not token:
            sys.stderr.write(f"Host no token. A last={collected['a'][-3:] if collected['a'] else None}\n")
            sys.stderr.write("A err=" + (a.stderr.read() or "")[:2000] + "\n")
            return 4

        b = subprocess.Popen(
            [sys.executable, str(runner), str(server_root), str(root_b), "guest", token, server_url],
            stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
        )
        ta = threading.Thread(target=collect, args=(a.stdout, "a"), daemon=True)
        tb = threading.Thread(target=collect, args=(b.stdout, "b"), daemon=True)
        ta.start(); tb.start()
        a.wait(timeout=180); b.wait(timeout=180)
        ta.join(timeout=5); tb.join(timeout=5)

        def is_done(lst): return any(x["phase"] == "done" and x.get("channel_id") for x in lst)
        if not is_done(collected["a"]) or not is_done(collected["b"]):
            sys.stderr.write("A last=" + json.dumps(collected["a"][-5:], ensure_ascii=False) + "\n")
            sys.stderr.write("B last=" + json.dumps(collected["b"][-5:], ensure_ascii=False) + "\n")
            sys.stderr.write("A stderr=" + (a.stderr.read() or "")[:3000] + "\n")
            sys.stderr.write("B stderr=" + (b.stderr.read() or "")[:3000] + "\n")
            return 5
        chan_a = next(x["channel_id"] for x in collected["a"] if x["phase"] == "done")
        chan_b = next(x["channel_id"] for x in collected["b"] if x["phase"] == "done")
        if chan_a != chan_b:
            return 6
        sa = next((x["safety_code"] for x in collected["a"] if x.get("safety_code")), None)
        sb = next((x["safety_code"] for x in collected["b"] if x.get("safety_code")), None)
        if sa != sb:
            return 7
        print("OK channel=", chan_a, "safety=", sa)
        return 0
    finally:
        try:
            proc.terminate()
            proc.wait(timeout=5)
        except Exception:
            try: proc.kill()
            except Exception: pass


if __name__ == "__main__":
    sys.exit(main())
