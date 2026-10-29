"""Тестовый сервер securechannel для тестов транспорта агента (не тест).

Текстовое первое сообщение — старый протокол (JSON с token), кадр SK —
настоящий securechannel.server.accept. Всё полученное записывается.
"""

import asyncio
import json

import websockets
from core import transport

transport._ensure_securechannel_path()

from fake_secure_store import FakeSecureStore

from securechannel.handshake import generate_keypair
from securechannel.keys import ServerKeys
from securechannel.pairing import PairingManager
from securechannel.registry import DeviceRegistry
from securechannel.server import SecureContext, accept

TOKEN = "tkn-secret"
FAIL_TIMEOUT = 0.3          # дедлайн рукопожатия сервера в тестах (вместо 5 с)


class Server:
    """Сервер: текст — старый протокол, кадр SK — securechannel.server.accept."""

    def __init__(self, tmp_path, *, legacy_close=None, noise_close=None):
        d = str(tmp_path / "secure")
        self.ctx = SecureContext(keys=ServerKeys.load_or_create(d),
                                 registry=DeviceRegistry.open(d),
                                 pairing=PairingManager(), timeout=FAIL_TIMEOUT)
        self.legacy_close = legacy_close      # код закрытия на первый текст
        self.noise_close = noise_close        # код закрытия после register по Noise
        self.first_kinds: list[str] = []      # "text" | "binary" — по соединениям
        self.texts: list[dict] = []           # всё, что пришло старым протоколом
        self.received: list[dict] = []        # всё, что пришло внутри Noise
        self.sessions = 0
        self.on_session = None                # async (conn) перед закрытием
        self.url = None

    def pair(self, hint="laptop"):
        priv, pub = generate_keypair()
        dev = self.ctx.registry.add(pub, name="тест", id_hint=hint)
        return FakeSecureStore.paired(dev["id"], priv, pub, self.ctx.keys.current[1],
                                      server_url=self.url or "")

    def stranger(self):
        """Ключи есть, но сервер их не знает — IK не пройдёт (4408)."""
        priv, pub = generate_keypair()
        return FakeSecureStore.paired("laptop", priv, pub, self.ctx.keys.current[1])

    async def handler(self, ws):
        try:
            first = await ws.recv()
        except websockets.ConnectionClosed:
            return
        if isinstance(first, str):
            self.first_kinds.append("text")
            self.texts.append(json.loads(first))
            if self.legacy_close:
                await ws.close(self.legacy_close, "closed by test")
                return
            await ws.send(json.dumps({"type": "registered"}))
            async for m in ws:
                self.texts.append(json.loads(m))
                await ws.send(json.dumps({"type": "echo", "msg": json.loads(m)}))
            return
        self.first_kinds.append("binary")
        conn = await accept(ws, bytes(first), self.ctx)
        if conn is None:
            return
        self.sessions += 1
        async for m in conn:
            msg = json.loads(m)
            self.received.append(msg)
            if self.noise_close:
                if self.on_session:
                    await self.on_session(conn)
                await ws.close(self.noise_close, "closed by test")
                return
            await conn.send(json.dumps({"type": "echo", "msg": msg}))

    async def __aenter__(self):
        self._srv = await websockets.serve(self.handler, "127.0.0.1", 0, max_size=None,
                                           ping_interval=None)
        self.url = f"ws://127.0.0.1:{self._srv.sockets[0].getsockname()[1]}"
        return self

    async def __aexit__(self, *exc):
        self._srv.close()
        await self._srv.wait_closed()


def run(coro_fn, timeout=20):
    async def _go():
        return await asyncio.wait_for(coro_fn(), timeout)
    return asyncio.run(_go())


async def recv_json(conn, timeout=3.0):
    return json.loads(await asyncio.wait_for(conn.recv(), timeout))
