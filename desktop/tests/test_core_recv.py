"""Цикл приёма сообщений сервера (reply, mood_update, context_transfer, ServerLink),
эмоция голоса, уровень активности, активное окно."""
import asyncio
import json
import threading
from types import SimpleNamespace

from desktop.core import agent as agent_module
from desktop.core import eyes, hearing, presence


class FakeBus:
    def __init__(self):
        self.events = []

    def emit(self, event, **kw):
        self.events.append((event, kw))


class FakeWS:
    def __init__(self, messages):
        self._messages = [json.dumps(m) for m in messages]

    def __aiter__(self):
        return self

    async def __anext__(self):
        if not self._messages:
            raise StopAsyncIteration
        return self._messages.pop(0)


def _agent(messages, link=None):
    a = agent_module.Agent.__new__(agent_module.Agent)
    a.bus = FakeBus()
    a._ws = FakeWS(messages)
    a._state = "idle"
    a._state_since = 0.0
    a._turn_gen = 0
    a._state_lock = threading.Lock()
    a._last_mood_update = None
    a.server_link = link
    return a


def test_reply_mood_and_context_transfer(monkeypatch):
    monkeypatch.setattr("desktop.core.platform.windows.WindowsPlatform.idle_seconds", lambda self: 5.0)
    a = _agent([
        {"type": "reply", "text": "  привет  "},
        {"type": "mood_update", "params": {"is_departure": True, "valence": 0.4, "arousal": 0.6}},
        {"type": "mood_update", "params": {"is_arrival": True}},
        {"type": "context_transfer", "text": "продолжи на ноутбуке"},
    ])
    asyncio.run(a._recv_loop())
    names = [e for e, _ in a.bus.events]
    assert names == ["sakura_text", "orb_departure", "mood_update", "orb_arrival", "mood_update",
                     "context_transfer"]
    assert a.bus.events[0][1] == {"text": "привет"}
    assert a._last_mood_update == {"valence": 0.0, "arousal": 0.3}  # последний mood без значений
    assert a.bus.events[-1][1] == {"text": "продолжи на ноутбуке"}


def test_server_link_consumes_v2_messages():
    seen = []
    link = SimpleNamespace(handle=lambda d: seen.append(d["type"]) or d["type"] == "registered")
    a = _agent([{"type": "registered", "proto": 2}, {"type": "reply", "text": "x"}], link=link)
    asyncio.run(a._recv_loop())
    assert seen == ["registered", "reply"]
    assert [e for e, _ in a.bus.events] == ["sakura_text"]


def test_bad_json_does_not_break_loop():
    a = _agent([{"type": "reply", "text": "1"}])
    a._ws._messages.insert(0, "{not json")
    asyncio.run(a._recv_loop())
    assert [e for e, _ in a.bus.events] == ["sakura_text"]


def test_voice_emotion_neutral_for_silence_and_short():
    assert hearing.analyze_voice_emotion(b"")["label"] == "neutral"
    assert hearing.analyze_voice_emotion(b"\x00\x00" * 100)["label"] == "neutral"  # < 0.1 с
    r = hearing.analyze_voice_emotion(b"\x00\x00" * 16000)
    assert set(r) >= {"label", "valence_hint", "arousal_hint"}


def test_voice_emotion_loud_differs_from_quiet():
    import numpy as np
    t = np.arange(16000) / 16000
    loud = (np.sin(2 * np.pi * 220 * t) * 30000).astype(np.int16).tobytes()
    quiet = (np.sin(2 * np.pi * 220 * t) * 300).astype(np.int16).tobytes()
    assert hearing.analyze_voice_emotion(loud) != hearing.analyze_voice_emotion(quiet)


def test_apply_voice_emotion_neutral_is_noop():
    hearing.apply_voice_emotion({"label": "neutral", "valence_hint": 0, "arousal_hint": 0})


def test_activity_level_global():
    presence._set_activity_level(0.7)
    assert presence.get_activity_level() == 0.7
    presence._set_activity_level(0.0)


def test_activity_watcher_touch_raises_level():
    w = presence.ActivityWatcher.__new__(presence.ActivityWatcher)
    w._lock = threading.Lock()
    w._last_at = 0.0
    w._level = 0.1
    w._touch(0.8)
    assert w._level == 0.8 and w._last_at > 0


def test_active_window_title(monkeypatch):
    fake = SimpleNamespace(GetForegroundWindow=lambda: 42,
                           GetWindowText=lambda h: "Telegram" if h == 42 else "")
    monkeypatch.setattr(eyes, "win32gui", fake)
    assert eyes.get_active_window() == "Telegram"
    monkeypatch.setattr(eyes, "win32gui", None)
    assert eyes.get_active_window() == ""
