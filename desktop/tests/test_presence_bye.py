"""Три ПК и присутствие: input_idle_s в каждом ping, bye при выключении, сне и выходе (не дольше 1 с)."""
import asyncio
import json
import threading
import time
from types import SimpleNamespace

from desktop.core import agent as agent_module
from desktop.core import config
from desktop.core.platform import session_events as SE


class FakeWS:
    def __init__(self, hang=False):
        self.sent, self.hang, self.closed = [], hang, False

    async def send(self, raw):
        if self.hang:
            await asyncio.sleep(30)  # сеть не отвечает
        self.sent.append(json.loads(raw))

    async def close(self):
        self.closed = True


def _agent(ws=None):
    a = agent_module.Agent.__new__(agent_module.Agent)
    a._ws = ws
    a._current_track = {}
    a._last_window = ""
    a._window_since = 0.0
    a._activity_level = 0.0
    a.media = None
    return a


# ── input_idle_s ─────────────────────────────────────────────────────

class IdleClock:
    """Платформа с GetLastInputInfo: секунды с последнего ввода растут, ввод их сбрасывает."""
    def __init__(self):
        self.now, self.last_input = 100.0, 100.0

    def idle_seconds(self):
        return self.now - self.last_input


def test_input_idle_grows_without_input_and_resets_on_input(monkeypatch):
    clock = IdleClock()
    monkeypatch.setattr("desktop.core.platform.get_platform", lambda: clock)
    monkeypatch.setattr(agent_module, "get_active_window", lambda: "Блокнот")
    monkeypatch.setattr(agent_module, "get_system_info", lambda: {})
    monkeypatch.setattr("desktop.core.presence.get_extended_system_info", lambda: {})
    a = _agent()
    seen = []
    for step in (0, 4, 9.5):
        clock.now = 100.0 + step
        seen.append(a._payload("ping")["input_idle_s"])
    assert seen == [0.0, 4.0, 9.5]                      # растёт без ввода
    clock.last_input = clock.now                        # мышь сдвинули
    assert a._payload("ping")["input_idle_s"] == 0.0    # сбросилось
    assert "input_idle_s" in a._payload("register")


def test_input_idle_unknown_is_omitted():
    assert agent_module.input_idle_seconds(SimpleNamespace(idle_seconds=lambda: 10 ** 9)) is None
    assert agent_module.input_idle_seconds(SimpleNamespace(idle_seconds=lambda: 1 / 0)) is None
    assert agent_module.input_idle_seconds(SimpleNamespace(idle_seconds=lambda: 3.14159)) == 3.1


def test_ping_at_least_every_10_seconds():
    assert agent_module.PING_MAX_SEC <= 10
    assert config.PING_INTERVAL <= 10 or min(config.PING_INTERVAL, agent_module.PING_MAX_SEC) <= 10


# ── bye ──────────────────────────────────────────────────────────────

def test_session_messages_classified():
    assert SE.classify(SE.WM_QUERYENDSESSION, 0) == "shutdown"
    assert SE.classify(SE.WM_ENDSESSION, 1) == "shutdown"
    assert SE.classify(SE.WM_ENDSESSION, 0) is None          # выключение отменено
    assert SE.classify(SE.WM_POWERBROADCAST, SE.PBT_APMSUSPEND) == "sleep"
    assert SE.classify(SE.WM_POWERBROADCAST, SE.PBT_APMRESUMEAUTOMATIC) == "resume"
    assert SE.classify(0x0010, 0) is None                    # WM_CLOSE


def test_session_events_once_per_burst():
    got, t = [], [0.0]
    ev = SE.SessionEvents(got.append, clock=lambda: t[0])
    ev.handle(SE.WM_QUERYENDSESSION, 0)
    ev.handle(SE.WM_ENDSESSION, 1)                           # тот же уход — один bye
    ev.handle(SE.WM_POWERBROADCAST, SE.PBT_APMSUSPEND)
    ev.handle(SE.WM_POWERBROADCAST, SE.PBT_APMRESUMESUSPEND)
    ev.handle(SE.WM_POWERBROADCAST, SE.PBT_APMRESUMEAUTOMATIC)
    t[0] = 3600.0
    ev.handle(SE.WM_POWERBROADCAST, SE.PBT_APMSUSPEND)       # уснул снова через час
    assert got == ["shutdown", "sleep", "resume", "sleep"]


def _in_loop(a, fn):
    """Агент с циклом событий в своём потоке (как ядро); fn — из потока окна выключения/сна."""
    loop = asyncio.new_event_loop()
    th = threading.Thread(target=loop.run_forever, daemon=True)
    th.start()
    a._loop = loop
    try:
        return fn()
    finally:
        loop.call_soon_threadsafe(loop.stop)
        th.join(2)


def test_bye_on_shutdown_and_sleep_with_reason(monkeypatch):
    monkeypatch.setattr(config, "DEVICE_ID", "pc")
    for kind in ("shutdown", "sleep"):
        ws = FakeWS()
        a = _agent(ws)
        _in_loop(a, lambda a=a, kind=kind: a._on_session_event(kind))
        assert ws.sent and ws.sent[0]["type"] == "bye"
        assert {k: ws.sent[0][k] for k in ("device_id", "reason")} == {"device_id": "pc", "reason": kind}


def test_bye_does_not_delay_shutdown_more_than_1s():
    ws = FakeWS(hang=True)
    a = _agent(ws)
    t0 = time.monotonic()
    ok = _in_loop(a, lambda: a.say_bye_blocking("shutdown"))
    took = time.monotonic() - t0
    assert ok is False
    assert took < 1.3


def test_bye_once_per_connection_and_exit_from_window():
    from desktop.core.service import CoreService
    ws = FakeWS()
    a = _agent(ws)
    svc = CoreService.__new__(CoreService)
    svc._agent = a
    r1 = asyncio.run(svc.cmd_bye({"reason": "exit"}))
    r2 = asyncio.run(svc.cmd_bye({"reason": "exit"}))
    assert r1 == {"sent": True} and r2 == {"sent": False}
    assert [m["reason"] for m in ws.sent] == ["exit"]
    svc._agent = None
    assert asyncio.run(svc.cmd_bye({})) == {"sent": False}   # ядро ещё не готово — выход не ждёт


def test_bye_without_connection_and_unknown_reason():
    a = _agent(None)
    assert asyncio.run(a.say_bye("shutdown")) is False
    ws = FakeWS()
    a = _agent(ws)
    asyncio.run(a.say_bye("reboot"))
    assert ws.sent[0]["reason"] == "exit"


def test_resume_reconnects():
    ws = FakeWS()
    a = _agent(ws)

    def go():
        a._on_session_event("resume")
        time.sleep(0.1)
    _in_loop(a, go)
    assert ws.closed is True
