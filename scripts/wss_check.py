"""Проверка wss:// Сакуры (docs/wss.md) — с любой машины.

    WS_SECRET=… python scripts/wss_check.py wss://sakura.example.org/ --device laptop
    python scripts/wss_check.py wss://sakura.example.org/ --closed 31.76.80.5:8765

1. TLS: версия, издатель сертификата (ждём Let's Encrypt), срок.
2. register с proto 2 → registered (токен из WS_SECRET, не печатается).
3. ping через цепочку.
--closed host:port — убедиться, что старый ws:// снаружи закрыт.
--cafile — свой корень (стенд с tls internal).
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import socket
import ssl
import sys
import time
from urllib.parse import urlparse


async def check_wss(url: str, device: str, cafile: str | None) -> bool:
    import websockets
    ctx = ssl.create_default_context(cafile=cafile)
    t0 = time.monotonic()
    async with websockets.connect(url, ssl=ctx, open_timeout=10) as ws:
        tls = ws.transport.get_extra_info("ssl_object")
        cert = tls.getpeercert()
        issuer = dict(x[0] for x in cert.get("issuer", ()))
        print(f"TLS {tls.version()}, издатель: {issuer.get('organizationName', '?')} "
              f"/ {issuer.get('commonName', '?')}, до {cert.get('notAfter')}")
        token = os.getenv("WS_SECRET", "")
        if not token:
            print("WS_SECRET не задан — регистрацию пропускаю")
            return True
        await ws.send(json.dumps({"type": "register", "device_id": device,
                                  "token": token, "proto": 2}))
        while True:
            m = json.loads(await asyncio.wait_for(ws.recv(), 10))
            if m.get("type") == "registered":
                print(f"registered: proto={m.get('proto')} master={m.get('master')}")
                break
        pong = await ws.ping()
        t = time.monotonic()
        await pong
        print(f"ping {(time.monotonic() - t) * 1000:.0f} мс, всего {time.monotonic() - t0:.2f} с")
    return True


def check_closed(hostport: str) -> bool:
    host, port = hostport.rsplit(":", 1)
    try:
        with socket.create_connection((host, int(port)), timeout=5):
            print(f"✗ {hostport} ОТКРЫТ снаружи")
            return False
    except OSError as e:
        print(f"✓ {hostport} закрыт ({type(e).__name__})")
        return True


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("url")
    ap.add_argument("--device", default="laptop")
    ap.add_argument("--cafile")
    ap.add_argument("--closed", help="host:port, который должен быть закрыт снаружи")
    a = ap.parse_args()
    if urlparse(a.url).scheme != "wss":
        print("нужен wss://")
        return 2
    ok = asyncio.run(check_wss(a.url, a.device, a.cafile))
    if a.closed:
        ok = check_closed(a.closed) and ok
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
