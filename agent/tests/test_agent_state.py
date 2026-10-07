"""tests/test_agent_state.py — смена состояния агента и возврат в idle."""

import threading

from core import agent as agent_module


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
