"""desktop/tools/mock_server.py — мок серверной части Сакуры (протокол v2).

Реализует сообщения из desktop/docs/PROTOCOL.md («Сервер ↔ ядро») на фикстурах
desktop/tools/fixtures/*.json. Состояние живёт в памяти процесса и сбрасывается
при перезапуске.

Режимы (--mode):
  normal  — всё поддерживается;
  legacy  — сервер без proto 2: на запросы v2 отвечает error/unsupported;
  offline — после регистрации молчит на запросы v2 (клиент ловит таймаут).

Запуск:  python -m desktop.tools.mock_server --port 8765 --token mock-token
"""
import argparse
import asyncio
import copy
import itertools
import json
import logging
import time
from pathlib import Path

import websockets

log = logging.getLogger("sakura.mock")

FIXTURES = Path(__file__).resolve().parent / "fixtures"
PROTO = 2
CLOSE_UNAUTHORIZED = 4401

V2_REQUESTS = {
    "history_request", "devices_request", "status_request",
    "scenarios_list", "scenario_get", "scenario_save", "scenario_delete",
    "scenario_run", "scenario_from_text",
    "memory_list", "memory_search", "memory_update", "memory_delete",
    "profile_get", "profile_set",
}


def load_fixtures(path: Path = FIXTURES) -> dict:
    data = {}
    for name in ("history", "devices", "status", "scenarios", "memory", "profile"):
        data[name] = json.loads((path / f"{name}.json").read_text(encoding="utf-8"))
    return data


class MockServer:
    def __init__(self, token: str = "mock-token", mode: str = "normal",
                 masters: tuple[str, ...] = ("mostech", "pc"),
                 fixtures: dict | None = None, step_delay: float = 0.05):
        assert mode in ("normal", "legacy", "offline")
        self.token = token
        self.mode = mode
        self.masters = set(masters)
        self.state = copy.deepcopy(fixtures if fixtures is not None else load_fixtures())
        self.step_delay = step_delay
        self.clients: dict = {}          # ws -> device_id
        self.received: list[dict] = []   # всё, что прислали клиенты (для тестов)
        self._ids = itertools.count(1)

    # ── отправка ───────────────────────────────────────────────────
    @staticmethod
    async def _send(ws, obj: dict):
        await ws.send(json.dumps(obj, ensure_ascii=False))

    async def broadcast(self, obj: dict):
        for ws in list(self.clients):
            try:
                await self._send(ws, obj)
            except Exception:
                self.clients.pop(ws, None)

    def _err(self, req: dict, code: str, message: str) -> dict:
        return {"type": "error", "request_id": req.get("request_id"),
                "code": code, "message": message}

    # ── соединение ─────────────────────────────────────────────────
    async def handler(self, ws):
        try:
            first = json.loads(await asyncio.wait_for(ws.recv(), timeout=10))
        except Exception:
            await ws.close(CLOSE_UNAUTHORIZED, "no register")
            return
        if first.get("type") != "register" or first.get("token") != self.token:
            await ws.close(CLOSE_UNAUTHORIZED, "unauthorized")
            return
        device = first.get("device_id") or "unknown"
        self.received.append(first)
        self.clients[ws] = device
        await self._send(ws, {
            "type": "registered", "device_id": device,
            "proto": PROTO if self.mode != "legacy" else 1,
            "master": device in self.masters,
        })
        try:
            async for raw in ws:
                if isinstance(raw, bytes):
                    continue
                try:
                    msg = json.loads(raw)
                except ValueError:
                    continue
                self.received.append(msg)
                await self.dispatch(ws, device, msg)
        except websockets.ConnectionClosed:
            pass
        finally:
            self.clients.pop(ws, None)

    async def dispatch(self, ws, device: str, msg: dict):
        kind = msg.get("type")
        if kind == "voice_command":
            await self._voice_command(ws, device, msg)
            return
        if kind not in V2_REQUESTS:
            return  # ping, command_result, apps_list и пр. — только записываем
        if msg.get("token") not in (None, self.token):
            await self._send(ws, self._err(msg, "unauthorized", "неверный токен"))
            return
        if self.mode == "legacy":
            await self._send(ws, self._err(msg, "unsupported", f"{kind}: сервер не поддерживает proto 2"))
            return
        if self.mode == "offline":
            return
        if device not in self.masters:
            await self._send(ws, self._err(msg, "not_master", f"{kind}: только для master-устройств"))
            return
        try:
            reply = await getattr(self, "_" + kind)(ws, msg)
        except KeyError as e:
            reply = self._err(msg, "bad_request", f"нет поля {e}")
        if reply is not None:
            reply.setdefault("request_id", msg.get("request_id"))
            await self._send(ws, reply)

    # ── голос/текст ────────────────────────────────────────────────
    def _add_message(self, role: str, text: str, channel: str, device: str) -> dict:
        m = {"id": f"m{int(time.time() * 1000)}-{next(self._ids)}", "ts": time.time(),
             "role": role, "text": text, "channel": channel, "device": device}
        self.state["history"]["messages"].append(m)
        return m

    async def _voice_command(self, ws, device: str, msg: dict):
        text = (msg.get("text") or "").strip()
        if not text:
            return
        channel = msg.get("channel", "voice")
        user = self._add_message("user", text, channel, device)
        await self.broadcast({"type": "chat_message", "message": user})
        answer = f"Мок: услышала «{text}»."
        await self._send(ws, {"type": "reply", "text": answer})
        bot = self._add_message("assistant", answer, channel, device)
        await self.broadcast({"type": "chat_message", "message": bot})

    # ── история, устройства, статус ────────────────────────────────
    async def _history_request(self, ws, msg):
        limit = int(msg.get("limit") or 50)
        before = msg.get("before_ts")
        items = [m for m in self.state["history"]["messages"]
                 if before is None or m["ts"] < before]
        return {"type": "history", "messages": items[-limit:]}

    async def _devices_request(self, ws, msg):
        return {"type": "devices", "devices": self.state["devices"]["devices"]}

    async def _status_request(self, ws, msg):
        return {"type": "status", **self.state["status"]}

    # ── сценарии ───────────────────────────────────────────────────
    def _scenarios(self) -> list:
        return self.state["scenarios"]["scenarios"]

    def _find_scenario(self, sid):
        return next((s for s in self._scenarios() if s["id"] == sid), None)

    async def _scenarios_list(self, ws, msg):
        return {"type": "scenarios", "scenarios": self._scenarios()}

    async def _scenario_get(self, ws, msg):
        s = self._find_scenario(msg["id"])
        if s is None:
            return self._err(msg, "not_found", "сценарий не найден")
        return {"type": "scenario", "scenario": s}

    async def _scenario_save(self, ws, msg):
        s = dict(msg["scenario"])
        if not s.get("name"):
            return self._err(msg, "bad_request", "у сценария нет названия")
        old = self._find_scenario(s.get("id"))
        if old is None:
            s["id"] = s.get("id") or f"s{next(self._ids)}"
            s.setdefault("enabled", True)
            self._scenarios().append(s)
        else:
            old.update(s)
            s = old
        return {"type": "scenario", "scenario": s}

    async def _scenario_delete(self, ws, msg):
        s = self._find_scenario(msg["id"])
        if s is None:
            return self._err(msg, "not_found", "сценарий не найден")
        self._scenarios().remove(s)
        return {"type": "scenarios", "scenarios": self._scenarios()}

    async def _scenario_run(self, ws, msg):
        s = self._find_scenario(msg["id"])
        if s is None:
            return self._err(msg, "not_found", "сценарий не найден")
        run_id = f"r{next(self._ids)}"
        await self._send(ws, {"type": "scenario_run_started", "request_id": msg.get("request_id"),
                              "run_id": run_id, "id": s["id"]})
        for i, act in enumerate(s.get("actions", [])):
            await asyncio.sleep(self.step_delay)
            await self._send(ws, {"type": "scenario_event", "run_id": run_id, "step": i,
                                  "status": "ok", "detail": act.get("type", "")})
        await self._send(ws, {"type": "scenario_event", "run_id": run_id,
                              "step": len(s.get("actions", [])), "status": "done", "detail": ""})
        return None

    async def _scenario_from_text(self, ws, msg):
        text = msg["text"].strip()
        if not text:
            return self._err(msg, "bad_request", "пустая фраза")
        scenario = {"id": None, "name": text[:40], "enabled": True,
                    "conditions": [{"type": "phrase", "value": text}],
                    "actions": [{"type": "notify", "value": text}]}
        return {"type": "scenario_preview", "scenario": scenario,
                "warnings": ["мок: сценарий собран по шаблону"]}

    # ── память ─────────────────────────────────────────────────────
    def _memory(self) -> list:
        return self.state["memory"]["items"]

    def _memory_reply(self, items, total=None) -> dict:
        cats: dict[str, int] = {}
        for it in self._memory():
            cats[it["category"]] = cats.get(it["category"], 0) + 1
        return {"type": "memory_items", "items": items,
                "total": len(items) if total is None else total, "counts": cats}

    async def _memory_list(self, ws, msg):
        cat = msg.get("category")
        off, lim = int(msg.get("offset") or 0), int(msg.get("limit") or 50)
        items = [m for m in self._memory() if not cat or m["category"] == cat]
        return self._memory_reply(items[off:off + lim], total=len(items))

    async def _memory_search(self, ws, msg):
        q = msg["q"].lower()
        lim = int(msg.get("limit") or 20)
        return self._memory_reply([m for m in self._memory() if q in m["text"].lower()][:lim])

    async def _memory_update(self, ws, msg):
        item = next((m for m in self._memory() if m["id"] == msg["id"]), None)
        if item is None:
            return self._err(msg, "not_found", "запись не найдена")
        item["text"] = msg["text"]
        return self._memory_reply([item])

    async def _memory_delete(self, ws, msg):
        item = next((m for m in self._memory() if m["id"] == msg["id"]), None)
        if item is None:
            return self._err(msg, "not_found", "запись не найдена")
        self._memory().remove(item)
        return self._memory_reply([])

    # ── профиль ────────────────────────────────────────────────────
    async def _profile_get(self, ws, msg):
        return {"type": "profile", "profile": self.state["profile"]}

    async def _profile_set(self, ws, msg):
        allowed = ("name", "address_as", "quiet_hours", "voice", "tone", "notifications")
        for k in allowed:
            if k in msg:
                self.state["profile"][k] = msg[k]
        return {"type": "profile", "profile": self.state["profile"]}

    # ── запуск ─────────────────────────────────────────────────────
    async def serve(self, host: str = "127.0.0.1", port: int = 8765):
        return await websockets.serve(self.handler, host, port, max_size=None)


async def _main(args):
    srv = MockServer(token=args.token, mode=args.mode)
    server = await srv.serve(args.host, args.port)
    log.info("mock server ws://%s:%s mode=%s", args.host, args.port, args.mode)
    async with server:
        await asyncio.Future()


def main(argv=None):
    ap = argparse.ArgumentParser(prog="mock_server")
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--port", type=int, default=8765)
    ap.add_argument("--token", default="mock-token")
    ap.add_argument("--mode", default="normal", choices=["normal", "legacy", "offline"])
    args = ap.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s")
    asyncio.run(_main(args))


if __name__ == "__main__":
    main()
