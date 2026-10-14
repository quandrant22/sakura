"""Живая проверка: python -m desktop.tools.run_action <action> [arg] [--confirmed] [--allow-pid N]

Подключается к локальному API ядра по ui.token и выполняет одно действие напрямую в диспетчере
агента (команда run_action есть только у ядра, запущенного с SAKURA_LIVECHECK=1). Печатает
status и detail; дополнительные поля — только именами (скриншот и тексты окон не печатаются).

Предохранитель (до вызова действия, обойти его через run() нельзя): files.delete и files.move —
только полный путь внутри разрешённых папок (по умолчанию C:\\sakura-tmp\\livecheck), без «..» и
ссылок наружу; process.kill — только pid из --allow-pid.
"""
import argparse
import asyncio
import json
import os
import sys
import uuid

import websockets

from desktop.core.api.server import default_token_path

_HIDDEN = {"screenshot", "text", "image"}
GUARDED = {"files.delete", "files.move", "process.kill"}
DEFAULT_ALLOW_DIR = r"C:\sakura-tmp\livecheck"


class Refused(RuntimeError):
    pass


def _inside(path: str, root: str) -> bool:
    p = os.path.normcase(os.path.realpath(path))
    r = os.path.normcase(os.path.realpath(root)).rstrip("\\/")
    return p == r or p.startswith(r + os.sep)


def guard(action: str, arg: str, allow_dirs, allow_pids) -> str | None:
    """Причина отказа или None."""
    if action not in GUARDED:
        return None
    if action == "process.kill":
        a = (arg or "").strip()
        if not a.isdigit() or int(a) not in set(allow_pids or ()):
            return "process.kill: pid не в списке разрешённых (--allow-pid) — по имени не завершаю"
        return None
    raw = (arg or "").split("|") if action == "files.move" else [arg or ""]
    for path in (x.strip().strip('"') for x in raw):
        if not os.path.isabs(path) or ".." in path.replace("/", "\\").split("\\"):
            return f"{action}: нужен полный путь без «..»"
        if not any(_inside(path, d) for d in allow_dirs):
            return f"{action}: путь вне разрешённых папок ({'; '.join(allow_dirs)})"
    return None


async def run(action: str, arg: str, confirmed: bool, token_file: str, show_text: bool,
              allow_dirs=(DEFAULT_ALLOW_DIR,), allow_pids=()) -> dict:
    refused = guard(action, arg, list(allow_dirs), list(allow_pids))
    if refused:
        return {"ok": True, "result": {"ok": False, "status": "refused_by_runner", "detail": refused}}
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
    ap.add_argument("--allow-dir", action="append", default=None, help="разрешённая папка (по умолчанию livecheck)")
    ap.add_argument("--allow-pid", action="append", type=int, default=[], help="свой pid для process.kill")
    a = ap.parse_args(argv)
    ev = asyncio.run(run(a.action, a.arg, a.confirmed, a.token_file, a.show_text,
                         allow_dirs=a.allow_dir or [DEFAULT_ALLOW_DIR], allow_pids=a.allow_pid))
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
