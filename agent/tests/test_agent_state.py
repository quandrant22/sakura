"""tests/test_agent_state.py — смена состояния агента и возврат в idle."""

import asyncio
import json
import threading

import pytest

from core import agent as agent_module
from core import tasks as tasks_module


class FakeBus:
    def __init__(self):
        self.states = []

    def emit(self, event, **kw):
        if event == "state":
            self.states.append(kw["value"])


class FakePlayer:
    def __init__(self):
        self.buf = 0
        self.last_feed_ts = 0.0

    def is_drained(self):
        return self.buf == 0

    def buffer_bytes(self):
        return self.buf

    def feed(self, pcm):
        self.buf += len(pcm)

    def feed_binary(self, data):
        self.buf += len(data)

    def flush(self):
        pass

    def interrupt(self):
        self.buf = 0


class FakeHearing:
    def __init__(self, agent):
        self.agent = agent
        self.followups = []

    def open_followup(self, seconds):
        # фиксируем, в каком состоянии был агент в момент вызова
        self.followups.append((seconds, self.agent.state))


def make_agent():
    a = agent_module.Agent.__new__(agent_module.Agent)
    a.bus = FakeBus()
    a._state = "idle"
    a._state_since = 0.0
    a._turn_gen = 0
    a._state_lock = threading.Lock()
    a.player = FakePlayer()
    a.hearing = FakeHearing(a)
    return a


def test_turn_gen_grows_on_change_to_thinking_or_speaking():
    a = make_agent()
    a._set_state("thinking")
    assert a._turn_gen == 1
    a._set_state("speaking")
    assert a._turn_gen == 2
    a._set_state("speaking")          # тот же стейт — не новая реплика
    assert a._turn_gen == 2
    a._set_state("idle")
    a._set_state("listening")
    assert a._turn_gen == 2
    assert a.state == "listening"
    assert a.bus.states == ["thinking", "speaking", "speaking", "idle", "listening"]


def test_state_since_updates_only_on_change(monkeypatch):
    a = make_agent()
    now = [10.0]
    monkeypatch.setattr(agent_module.time, "monotonic", lambda: now[0])
    a._set_state("speaking")
    assert a._state_since == 10.0
    now[0] = 12.0
    a._set_state("speaking")
    assert a._state_since == 10.0
    a._set_state("idle")
    assert a._state_since == 12.0


def test_public_set_state_goes_through_single_point():
    a = make_agent()
    a.set_state("thinking")           # так зовут hearing.py / presence.py
    assert a.state == "thinking"
    assert a._turn_gen == 1


# ── tts_end → idle после опустошения буфера ─────────────────────────────

@pytest.fixture
def fast_drain(monkeypatch):
    monkeypatch.setattr(agent_module, "_DRAIN_POLL_SEC", 0.001)
    monkeypatch.setattr(agent_module, "_DRAIN_TAIL_SEC", 0.001)
    monkeypatch.setattr(agent_module, "_DRAIN_MAX_SEC", 5.0)


class FakeWS:
    def __init__(self, messages):
        self._messages = list(messages)

    def __aiter__(self):
        return self

    async def __anext__(self):
        if not self._messages:
            raise StopAsyncIteration
        return self._messages.pop(0)

    async def send(self, _):
        pass


async def _drain_spawned():
    pending = [t for t in tasks_module._tasks if not t.done()]
    if pending:
        await asyncio.gather(*pending)


def test_tts_end_waits_for_drain_then_idle_then_followup(fast_drain):
    a = make_agent()
    seen_while_playing = []

    class Draining(FakePlayer):
        polls = 0

        def is_drained(self):
            self.polls += 1
            if self.polls < 5:
                seen_while_playing.append(a.state)
                return False
            return True

    a.player = Draining()

    async def main():
        a._ws = FakeWS([
            b"\x00\x00\x00\x00" + b"\x01\x00" * 8,
            json.dumps({"type": "tts_end", "listen": 6}),
        ])
        await a._recv_loop()
        assert a.state == "speaking"      # tts_end сам не ставит idle
        await _drain_spawned()

    asyncio.run(main())
    assert seen_while_playing == ["speaking"] * 4
    assert a.state == "idle"
    assert a.bus.states[-1] == "idle"
    # окно дослушивания открыто ПОСЛЕ idle
    assert a.hearing.followups == [(6.0, "idle")]


def test_stale_idle_does_not_override_new_turn(fast_drain):
    a = make_agent()
    a._set_state("speaking")

    class Draining(FakePlayer):
        polls = 0

        def is_drained(self):
            self.polls += 1
            if self.polls == 2:
                a._set_state("thinking")   # пользователь начал новую реплику
            return self.polls >= 4

    a.player = Draining()
    asyncio.run(a._idle_after_playback(a._turn_gen, listen=5))
    assert a.state == "thinking"
    assert a.hearing.followups == []


def test_tts_end_without_listen_does_not_open_followup(fast_drain):
    a = make_agent()
    a._set_state("speaking")
    asyncio.run(a._idle_after_playback(a._turn_gen))
    assert a.state == "idle"
    assert a.hearing.followups == []



# ── страховки watchdog ──────────────────────────────────────────────────

def test_speaking_stall_goes_idle(monkeypatch, caplog):
    a = make_agent()
    monkeypatch.setattr(agent_module.time, "monotonic", lambda: 100.0)
    a._set_state("speaking")
    a.player.last_feed_ts = 100.0

    a._check_state_stall(now=102.0)        # тишина < 2.5 с — ждём
    assert a.state == "speaking"

    a.player.buf = 10                      # буфер ещё играет — не трогаем
    a._check_state_stall(now=110.0)
    assert a.state == "speaking"

    a.player.buf = 0
    with caplog.at_level("WARNING", logger="sakura.agent"):
        a._check_state_stall(now=102.5)
    assert a.state == "idle"
    assert "[state] speaking без tts_end -> idle" in caplog.text


def test_thinking_timeout_goes_idle(monkeypatch, caplog):
    a = make_agent()
    monkeypatch.setattr(agent_module.time, "monotonic", lambda: 50.0)
    a._set_state("thinking")

    a._check_state_stall(now=74.9)
    assert a.state == "thinking"

    with caplog.at_level("WARNING", logger="sakura.agent"):
        a._check_state_stall(now=75.0)
    assert a.state == "idle"
    assert "[state] thinking без ответа -> idle" in caplog.text


def test_watchdog_ignores_idle_and_listening(caplog):
    a = make_agent()
    for st in ("idle", "listening"):
        a._set_state(st)
        a._check_state_stall(now=10_000.0)
        assert a.state == st
    assert "[state]" not in caplog.text


def test_watchdog_sees_state_set_by_hearing(monkeypatch):
    a = make_agent()
    monkeypatch.setattr(agent_module.time, "monotonic", lambda: 0.0)
    a.set_state("thinking")                # путь hearing.py
    a._check_state_stall(now=30.0)
    assert a.state == "idle"


def test_drain_wait_is_bounded(monkeypatch, fast_drain):
    monkeypatch.setattr(agent_module, "_DRAIN_MAX_SEC", 0.02)
    a = make_agent()
    a._set_state("speaking")
    a.player.buf = 100                     # буфер так и не опустел
    asyncio.run(a._idle_after_playback(a._turn_gen))
    assert a.state == "idle"
