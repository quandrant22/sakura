"""Живая проверка: python -m desktop.tools.run_action <action> [arg] [--confirmed]

Подключается к локальному API ядра по ui.token и выполняет одно действие напрямую в диспетчере
агента (команда run_action есть только у ядра, запущенного с SAKURA_LIVECHECK=1). Печатает
status и detail; дополнительные поля — только именами (скриншот и тексты окон не печатаются).
"""
import argparse
import asyncio
import json
import sys
import uuid

import websockets

from desktop.core.api.server import default_token_path

_HIDDEN = {"screenshot", "text", "image"}


async def run(action: str, arg: str, confirmed: bool, token_file: str, show_text: bool) -> dict:
    with open(token_file, encoding="utf-8") as f:
        conn = json.load(f)
    async with websockets.connect(f"ws://127.0.0.1:{int(conn['port'])}", open_timeout=3, max_size=None) as ws:
        await ws.send(json.dumps({"type": "hello", "token": conn["token"], "client": "livecheck"}))
        rid = uuid.uuid4().hex
        await ws.send(json.dumps({"type": "run_action", "request_id": rid, "action": action, "arg": arg,
                                  "confirmed": confirmed}, ensure_ascii=False))
        while True:
            ev = json.loads(await asyncio.wait_for(ws.recv(), timeout=40))
            if ev.get("type") == "reply" and ev.get("request_id") == rid:
                return ev


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="desktop.tools.run_action")
    ap.add_argument("action")
    ap.add_argument("arg", nargs="?", default="")
    ap.add_argument("--confirmed", action="store_true")
    ap.add_argument("--show-text", action="store_true", help="печатать поле text (ui.read)")
    ap.add_argument("--token-file", default=default_token_path())
    a = ap.parse_args(argv)
    ev = asyncio.run(run(a.action, a.arg, a.confirmed, a.token_file, a.show_text))
    if not ev.get("ok"):
        print(json.dumps({"api_error": ev.get("error")}, ensure_ascii=False))
        return 2
    res = ev.get("result") or {}
    out = {"status": res.get("status"), "detail": res.get("detail")}
    for k, v in res.items():
        if k in ("ok", "status", "detail"):
            continue
        out[k] = v if (k not in _HIDDEN or (k == "text" and a.show_text)) else f"<{k}: {len(str(v))} симв.>"
    print(json.dumps(out, ensure_ascii=False))
    return 0 if res.get("ok") else 1


if __name__ == "__main__":
    sys.exit(main())
