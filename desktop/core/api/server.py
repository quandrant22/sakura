"""desktop.core.api.server — локальный WebSocket API ядра для интерфейса и оверлея.

Протокол — desktop/docs/PROTOCOL.md, раздел «Ядро ↔ интерфейс»:
- слушает только 127.0.0.1; порт и токен пишутся в файл (ui.token, JSON),
  доступ к файлу — только текущему пользователю;
- первое сообщение клиента — hello с токеном, иначе закрытие 4401 через 5 с;
- Origin из белого списка (Electron file://, dev-сервер Vite, без Origin —
  оверлей на Python), иначе закрытие 4403;
- события ядра рассылаются всем клиентам; команды с request_id получают reply.
"""
import asyncio
import json
import logging
import os
import secrets
from collections.abc import Awaitable, Callable

import websockets

log = logging.getLogger("sakura.api")

CLOSE_UNAUTHORIZED = 4401
CLOSE_FORBIDDEN_ORIGIN = 4403
HELLO_TIMEOUT = 5.0
ALLOWED_ORIGINS = frozenset({"file://", "http://localhost:5173", "http://127.0.0.1:5173"})

Handler = Callable[[dict], Awaitable[object]]


class ApiError(Exception):
    """Ошибка команды: уходит клиенту как reply.error {code, message}."""

    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code
        self.message = message


def default_token_path() -> str:
    base = os.getenv("LOCALAPPDATA") or os.path.expanduser("~")
    return os.path.join(base, "Sakura", "ui.token")


class LocalApiServer:
    def __init__(self, token: str | None = None, token_path: str | None = None,
                 restrict: Callable[[str], None] | None = None,
                 snapshot: Callable[[], list[dict]] | None = None):
        self.token = token or secrets.token_urlsafe(32)
        self.token_path = token_path
        self._restrict = restrict
        self._snapshot = snapshot or (lambda: [])
        self._handlers: dict[str, Handler] = {}
        self._clients: set = set()
        self._server = None
        self._loop: asyncio.AbstractEventLoop | None = None
        self.port: int | None = None

    # ── регистрация команд ─────────────────────────────────────────
    def command(self, kind: str, handler: Handler) -> None:
        self._handlers[kind] = handler

    # ── события ────────────────────────────────────────────────────
    async def broadcast(self, event: dict) -> None:
        data = json.dumps(event, ensure_ascii=False)
        for ws in list(self._clients):
            try:
                await ws.send(data)
            except websockets.ConnectionClosed:
                self._clients.discard(ws)

    def emit_threadsafe(self, event: dict) -> None:
        """Отправить событие из любого потока (подписчик EventBus)."""
        if self._loop is None or self._loop.is_closed():
            return
        asyncio.run_coroutine_threadsafe(self.broadcast(event), self._loop)

    # ── соединение ─────────────────────────────────────────────────
    @staticmethod
    def origin_allowed(origin: str | None) -> bool:
        return origin is None or origin in ALLOWED_ORIGINS

    async def _handler(self, ws):
        origin = ws.request.headers.get("Origin") if ws.request else None
        if not self.origin_allowed(origin):
            log.warning("[api] отклонён Origin %r", origin)
            await ws.close(CLOSE_FORBIDDEN_ORIGIN, "origin")
            return
        try:
            hello = json.loads(await asyncio.wait_for(ws.recv(), HELLO_TIMEOUT))
        except (asyncio.TimeoutError, ValueError, websockets.ConnectionClosed):
            await ws.close(CLOSE_UNAUTHORIZED, "no hello")
            return
        if hello.get("type") != "hello" or not secrets.compare_digest(
                str(hello.get("token", "")), self.token):
            await ws.close(CLOSE_UNAUTHORIZED, "unauthorized")
            return
        self._clients.add(ws)
        log.info("[api] клиент подключён: %s", hello.get("client", "?"))
        try:
            for ev in self._snapshot():
                await ws.send(json.dumps(ev, ensure_ascii=False))
            async for raw in ws:
                if isinstance(raw, bytes):
                    continue
                try:
                    msg = json.loads(raw)
                except ValueError:
                    continue
                asyncio.ensure_future(self._dispatch(ws, msg))
        except websockets.ConnectionClosed:
            pass
        finally:
            self._clients.discard(ws)

    async def _dispatch(self, ws, msg: dict):
        rid = msg.get("request_id")
        handler = self._handlers.get(msg.get("type"))
        if handler is None:
            reply = {"type": "reply", "request_id": rid, "ok": False,
                     "error": {"code": "unknown_command", "message": str(msg.get("type"))}}
        else:
            try:
                result = await handler(msg)
                reply = {"type": "reply", "request_id": rid, "ok": True}
                if result is not None:
                    reply["result"] = result
            except ApiError as e:
                reply = {"type": "reply", "request_id": rid, "ok": False,
                         "error": {"code": e.code, "message": e.message}}
            except Exception as e:  # noqa: BLE001 — ошибка команды не должна ронять API
                log.exception("[api] команда %s", msg.get("type"))
                reply = {"type": "reply", "request_id": rid, "ok": False,
                         "error": {"code": "internal", "message": str(e)}}
        try:
            await ws.send(json.dumps(reply, ensure_ascii=False))
        except websockets.ConnectionClosed:
            pass

    # ── запуск ─────────────────────────────────────────────────────
    async def start(self, port: int = 0):
        self._loop = asyncio.get_running_loop()
        self._server = await websockets.serve(self._handler, "127.0.0.1", port, max_size=2 ** 22)
        self.port = next(iter(self._server.sockets)).getsockname()[1]
        if self.token_path:
            self._write_token_file()
        log.info("[api] слушаю ws://127.0.0.1:%s", self.port)
        return self._server

    def _write_token_file(self):
        os.makedirs(os.path.dirname(self.token_path), exist_ok=True)
        with open(self.token_path, "w", encoding="utf-8") as f:
            json.dump({"port": self.port, "token": self.token}, f)
        if self._restrict:
            try:
                self._restrict(self.token_path)
            except Exception as e:  # noqa: BLE001
                log.warning("[api] не удалось ограничить права на файл токена: %s", e)

    async def stop(self):
        if self._server:
            self._server.close()
            await self._server.wait_closed()
