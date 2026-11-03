"""Проверка живого ядра: python -m desktop.tools.core_check [--wait 60] [--token-file PATH]

Подключается к локальному API ядра по ui.token (как интерфейс), читает снимок состояния и
ждёт, пока ядро загрузится и сервер будет на связи — то есть пока в интерфейсе пропадёт
«Нет связи». Печатает одну строку JSON без секретов:
  {"core": true, "core_ready": true, "server": "online", "proto": 1}
Код выхода 0 — ядро отвечает, оно готово и сервер онлайн; 1 — нет (с причиной в JSON).
"""
import argparse
import asyncio
import json
import sys
import time

import websockets

from desktop.core.api.server import default_token_path


async def check(token_file: str, wait: float) -> dict:
    result = {"core": False, "core_ready": False, "server": "unknown", "proto": None}
    deadline = time.monotonic() + wait
    while True:
        try:
            with open(token_file, encoding="utf-8") as f:
                conn = json.load(f)
            async with websockets.connect(f"ws://127.0.0.1:{int(conn['port'])}", open_timeout=3) as ws:
                await ws.send(json.dumps({"type": "hello", "token": conn["token"], "client": "check"}))
                result["core"] = True
                # Снимок приходит сразу; дальше ядро само шлёт connection/settings при изменениях.
                while True:
                    left = deadline - time.monotonic()
                    try:
                        ev = json.loads(await asyncio.wait_for(ws.recv(), timeout=max(left, 0.5)))
                    except asyncio.TimeoutError:
                        return result
                    if ev.get("type") == "connection":
                        result["server"], result["proto"] = ev.get("server"), ev.get("proto")
                    elif ev.get("type") == "settings":
                        result["core_ready"] = bool((ev.get("settings") or {}).get("core_ready"))
                    if (result["core_ready"] and result["server"] == "online") or left <= 0:
                        return result
        except (OSError, ValueError, KeyError, websockets.WebSocketException) as e:
            result["error"] = type(e).__name__
        if time.monotonic() >= deadline:
            return result
        await asyncio.sleep(1)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="desktop.tools.core_check")
    ap.add_argument("--wait", type=float, default=0, help="сколько секунд ждать готовности")
    ap.add_argument("--token-file", default=default_token_path())
    args = ap.parse_args(argv)
    r = asyncio.run(check(args.token_file, args.wait))
    print(json.dumps(r, ensure_ascii=False))
    return 0 if r["core"] and r["core_ready"] and r["server"] == "online" else 1


if __name__ == "__main__":
    sys.exit(main())
