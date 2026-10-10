"""desktop.core.server_link — запросы протокола v2 поверх существующего WebSocket агента.

Agent держит соединение с VPS (как раньше); ServerLink добавляет:
- proto: 2 в регистрации (Agent._payload) и разбор ответа registered;
- запросы с request_id и ожиданием ответа (таймаут 10 с);
- ошибки offline (нет соединения), unsupported (сервер v1), timeout;
- пуши сервера (chat_message, device_update, status, scenario_event) → on_push.

Сервер v1 не присылает registered: если за V1_GRACE секунд после подключения
ответа нет, считаем proto = 1 и на запросы сразу отвечаем unsupported.
"""
import asyncio
import itertools
import logging
import time
from collections.abc import Awaitable, Callable

from desktop.core.api.server import ApiError

log = logging.getLogger("sakura.server_link")

PROTO = 2
REQUEST_TIMEOUT = 10.0
V1_GRACE = 3.0
PUSH_TYPES = frozenset({"chat_message", "device_update", "status", "scenario_event",
                        "scenario_run_started"})


class ServerLink:
    def __init__(self, auth: Callable[[], dict] | None = None,
                 on_push: Callable[[dict], None] | None = None,
                 on_state: Callable[[dict], None] | None = None,
                 timeout: float = REQUEST_TIMEOUT, v1_grace: float = V1_GRACE):
        self._auth = auth or (lambda: {})
        self._on_push = on_push or (lambda ev: None)
        self._on_state = on_state or (lambda ev: None)
        self.timeout = timeout
        self.v1_grace = v1_grace
        self._send: Callable[[dict], Awaitable[None]] | None = None
        self._pending: dict[str, asyncio.Future] = {}
        self._ids = itertools.count(1)
        self._connected_at = 0.0
        self.proto: int | None = None
        self.master: bool | None = None

    # ── состояние соединения ───────────────────────────────────────
    @property
    def online(self) -> bool:
        return self._send is not None

    def state_event(self) -> dict:
        return {"type": "connection", "server": "online" if self.online else "offline",
                "proto": self.proto}

    def on_connected(self, send: Callable[[dict], Awaitable[None]]) -> None:
        self._send = send
        self._connected_at = time.monotonic()
        self.proto = None
        self.master = None
        self._on_state(self.state_event())

    def on_disconnected(self) -> None:
        self._send = None
        for fut in self._pending.values():
            if not fut.done():
                fut.set_exception(ApiError("offline", "нет связи с сервером"))
        self._pending.clear()
        self._on_state(self.state_event())

    def _effective_proto(self) -> int | None:
        if self.proto is None and self.online and time.monotonic() - self._connected_at >= self.v1_grace:
            self.proto = 1
            log.info("[server] нет ответа registered — сервер без proto 2")
            self._on_state(self.state_event())
        return self.proto

    # ── входящие ───────────────────────────────────────────────────
    def handle(self, data: dict) -> bool:
        """Разобрать сообщение сервера. True — сообщение принадлежит ServerLink."""
        kind = data.get("type")
        if kind == "registered":
            self.proto = int(data.get("proto") or 1)
            self.master = data.get("master")
            log.info("[server] registered proto=%s master=%s", self.proto, self.master)
            self._on_state(self.state_event())
            return True
        rid = data.get("request_id")
        if rid is not None and rid in self._pending:
            fut = self._pending.pop(rid)
            if not fut.done():
                if kind == "error":
                    fut.set_exception(ApiError(data.get("code") or "error", data.get("message") or ""))
                else:
                    fut.set_result(data)
            return True
        if kind in PUSH_TYPES:
            self._on_push(data)
            return True
        if kind == "error" and rid is not None:
            return True  # ответ на запрос, который уже истёк
        return False

    # ── запросы ────────────────────────────────────────────────────
    async def request(self, message: dict) -> dict:
        if not self.online:
            raise ApiError("offline", "нет связи с сервером")
        if (self._effective_proto() or PROTO) < PROTO:
            raise ApiError("unsupported", "сервер не поддерживает")
        rid = f"q{next(self._ids)}"
        msg = {**message, **self._auth(), "request_id": rid}
        fut = asyncio.get_running_loop().create_future()
        self._pending[rid] = fut
        try:
            await self._send(msg)
            return await asyncio.wait_for(fut, self.timeout)
        except asyncio.TimeoutError:
            raise ApiError("timeout", f"{message.get('type')}: нет ответа за {self.timeout:.0f} с") from None
        finally:
            self._pending.pop(rid, None)
