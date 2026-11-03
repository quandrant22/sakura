"""tests/test_agent_transport_loop.py — цикл подключения agent.run() поверх
core/transport.py: коды закрытия 4408/4409/4412/4413, режим required,
статус канала. Сервер — настоящий securechannel.server.accept на 127.0.0.1.
"""

import asyncio
import json
import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest
from core import agent as agent_module
from core import transport
from core.outbox import Outbox

transport._ensure_securechannel_path()
pytest.importorskip("noise")

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fake_secure_store import FakeSecureStore
from noise_test_server import Server, run

# ── цикл агента: коды закрытия ───────────────────────────────────────


class _Stop(Exception):
    pass


class RecBus:
    def __init__(self):
        self.events = []

    def emit(self, event, **data):
        self.events.append((event, data))


@pytest.fixture
def agent_env(monkeypatch, tmp_path):
    """Агент без UI, слуха, расширения и сканов; сон и ожидание ключей — записываются."""
    from core import presence
    sleeps, waits = [], []

    class FakeAsyncio:
        def __getattr__(self, name):
            return getattr(asyncio, name)

        @staticmethod
        async def sleep(delay, *a, **k):
            sleeps.append(delay)
            if len(sleeps) >= 2:
                raise _Stop
            await asyncio.sleep(0)

    async def wait_for_keys(*a, **k):
        waits.append(True)
        raise _Stop

    monkeypatch.setattr(agent_module, "asyncio", FakeAsyncio())
    monkeypatch.setattr(transport, "wait_for_keys", wait_for_keys)
    monkeypatch.setattr(agent_module, "spawn", lambda coro, name=None: coro.close())
    monkeypatch.setattr(agent_module, "_EXTENSION_SERVER", str(tmp_path / "missing.py"))
    monkeypatch.setattr(agent_module, "init_index", lambda: None)
    monkeypatch.setattr(agent_module, "scan_apps", list)
    monkeypatch.setattr(presence, "prime_system_info", lambda: None)
    monkeypatch.setattr(agent_module.Agent, "_payload",
                        lambda self, kind: {"type": kind, "device_id": "laptop"})
    monkeypatch.setattr(agent_module.config, "AGENT_SECURE", "prefer")
    monkeypatch.setattr(agent_module.config, "RECONNECT_SEC", 3)

    def make(store):
        monkeypatch.setattr(transport, "_default_store", lambda: store)
        a = agent_module.Agent.__new__(agent_module.Agent)
        a.bus, a.hearing, a._outbox = RecBus(), MagicMock(), Outbox()
        a._ws = a._loop = None
        return a

    return SimpleNamespace(make=make, sleeps=sleeps, waits=waits, monkeypatch=monkeypatch)


def statuses(agent):
    return [d for e, d in agent.bus.events if e == "secure_status"]


def test_agent_4408_backoff_and_retry_noise_only(tmp_path, agent_env):
    async def sc():
        async with Server(tmp_path) as srv:
            a = agent_env.make(srv.stranger())
            agent_env.monkeypatch.setattr(agent_module.config, "VPS_WS_URL", srv.url)
            with pytest.raises(_Stop):
                await a.run()
            await asyncio.sleep(0.05)
            return srv, a
    srv, a = run(sc)
    assert agent_env.sleeps == [3, 6]                 # backoff и повтор
    assert srv.first_kinds == ["binary", "binary"]    # и снова только Noise
    assert srv.texts == []
    assert ("connection", {"online": True}) not in a.bus.events
    assert not any(s["secure"] for s in statuses(a))


def test_agent_4409_reconnects(tmp_path, agent_env):
    async def sc():
        async with Server(tmp_path, noise_close=4409) as srv:
            a = agent_env.make(srv.pair())
            agent_env.monkeypatch.setattr(agent_module.config, "VPS_WS_URL", srv.url)
            with pytest.raises(_Stop):
                await a.run()
            return srv, a
    srv, a = run(sc)
    assert agent_env.sleeps == [3, 3]       # сеанс был — backoff сброшен
    assert srv.sessions == 2 and srv.texts == []
    assert [r["type"] for r in srv.received] == ["register", "register"]
    assert statuses(a)[0] == {"secure": True, "text": agent_module.STATUS_SECURE}


def test_agent_4412_waits_for_keys_without_reconnect(tmp_path, agent_env):
    async def sc():
        async with Server(tmp_path, legacy_close=4412) as srv:
            a = agent_env.make(FakeSecureStore())
            agent_env.monkeypatch.setattr(agent_module.config, "VPS_WS_URL", srv.url)
            with pytest.raises(_Stop):
                await a.run()
            return srv, a
    srv, a = run(sc)
    assert agent_env.waits == [True] and agent_env.sleeps == []   # не переподключается
    assert srv.first_kinds == ["text"]
    assert statuses(a)[-1] == {"secure": False, "text": agent_module.STATUS_SERVER_REQUIRES}
    alerts = [d["text"] for e, d in a.bus.events if e == "agent_alert"]
    assert alerts == ["Сервер требует защищённый канал — выполните спаривание"]


def test_agent_required_without_keys_not_paired(tmp_path, agent_env):
    agent_env.monkeypatch.setattr(agent_module.config, "AGENT_SECURE", "required")

    async def sc():
        async with Server(tmp_path) as srv:
            a = agent_env.make(FakeSecureStore())
            agent_env.monkeypatch.setattr(agent_module.config, "VPS_WS_URL", srv.url)
            with pytest.raises(_Stop):
                await a.run()
            await asyncio.sleep(0.05)
            return srv, a
    srv, a = run(sc)
    assert srv.first_kinds == [] and agent_env.waits == [True]
    assert statuses(a) == [{"secure": False, "text": agent_module.STATUS_NOT_PAIRED}]


def test_agent_4413_clears_outbox_and_backs_off(tmp_path, agent_env, caplog):
    async def sc():
        async with Server(tmp_path, noise_close=4413) as srv:
            a = agent_env.make(srv.pair())

            async def queue_more(conn):
                a._outbox.put({"type": "voice_command", "text": "ещё"})
            srv.on_session = queue_more
            agent_env.monkeypatch.setattr(agent_module.config, "VPS_WS_URL", srv.url)
            with pytest.raises(_Stop):
                await a.run()
            return a
    a = run(sc)
    assert agent_env.sleeps[0] == 60
    assert "4413" in caplog.text
    assert not a._outbox._pending


def test_agent_without_keys_status_not_secure(tmp_path, agent_env):
    async def sc():
        async with Server(tmp_path, legacy_close=1000) as srv:
            a = agent_env.make(FakeSecureStore())
            agent_env.monkeypatch.setattr(agent_module.config, "VPS_WS_URL", srv.url)
            with pytest.raises(_Stop):
                await a.run()
            return srv, a
    srv, a = run(sc)
    assert srv.first_kinds == ["text", "text"]
    assert srv.texts[0]["token"] == agent_module.config.WS_TOKEN.strip()
    assert statuses(a) == [{"secure": False, "text": agent_module.STATUS_NOT_SECURE}]
    assert "VPN" not in agent_module.STATUS_NOT_SECURE + agent_module.STATUS_NOT_PAIRED         + agent_module.STATUS_SERVER_REQUIRES


def test_recv_loop_routes_secure_server_key():
    a = agent_module.Agent.__new__(agent_module.Agent)
    got = []

    class FakeConn:
        def __init__(self):
            self._m = [json.dumps({"type": "secure_server_key", "pub": "x", "fp": "y"})]

        def __aiter__(self):
            return self

        async def __anext__(self):
            if not self._m:
                raise StopAsyncIteration
            return self._m.pop()

        def accept_server_key(self, msg):
            got.append(msg["type"])

    a._ws = FakeConn()
    asyncio.run(a._recv_loop())
    assert got == ["secure_server_key"]
