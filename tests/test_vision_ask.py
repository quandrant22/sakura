"""feat/vision: разовый вопрос, хендлеры реестра, приватность кадра.

Run: python -m pytest tests/test_vision_ask.py -q
"""

import asyncio
import base64
import json
import logging

import pytest

import config
import modules.state as st
from sakura_core.executor import AgentCommand, ExecutionContext
from sakura_core.vision import ask, capture, model, seen, settings

MASTER = "laptop"
SECRET = b"\xff\xd8\xff" + b"SECRET-PIXELS" * 40
SECRET_B64 = base64.b64encode(SECRET).decode()


class PC:
    secure = True

    def __init__(self, reply=None):
        self.reply = reply
        self.sent = []

    async def send(self, raw):
        msg = json.loads(raw)
        self.sent.append(msg)
        if msg.get("type") == "vision.capture" and self.reply is not None:
            r = {"type": "vision.frame", "request_id": msg["request_id"],
                 "device_id": MASTER, **self.reply}
            asyncio.get_running_loop().call_soon(
                lambda: asyncio.ensure_future(capture.handle_frame(self, r)))


@pytest.fixture(autouse=True)
def clean(monkeypatch, tmp_path):
    capture.reset()
    seen.reset()
    saved = dict(st.connected_devices)
    st.connected_devices.clear()
    monkeypatch.setattr(config, "PRIVATE_REQUIRES_SECURE", True)
    monkeypatch.setattr(config, "VISION_SETTINGS_PATH", str(tmp_path / "vision.json"))
    monkeypatch.setattr(st, "_pending_describe", {})
    yield
    capture.reset()
    seen.reset()
    st.connected_devices.clear()
    st.connected_devices.update(saved)


def online(pc, features=(capture.FEATURE,)):
    st.connected_devices[MASTER] = pc
    capture.note_features(MASTER, {"features": list(features)})
    return pc


def model_says(monkeypatch, text):
    calls = []

    async def fake(image, mime, prompt, **kw):
        calls.append((len(image), mime, prompt))
        return text
    monkeypatch.setattr(model, "see", fake)
    return calls


def run(coro):
    return asyncio.run(coro)


# ── ask.answer ─────────────────────────────────────────────────────

def test_answer_ok_and_remembers(monkeypatch):
    online(PC({"status": "ok", "image": SECRET_B64, "window": {"title": "Steam"}}))
    calls = model_says(monkeypatch, "Открыт Steam, библиотека игр.\nВИДЕЛА: Steam, библиотека")
    text, ok = run(ask.answer(MASTER, "что у меня тут?"))
    assert (text, ok) == ("Открыт Steam, библиотека игр.", True)
    assert "что у меня тут?" in calls[0][2]
    s = seen.latest()
    assert (s.saw, s.title, s.purpose) == ("Steam, библиотека", "Steam", "ask")


@pytest.mark.parametrize("reason, phrase", [
    ("private_window", "приватное"), ("disabled", "запрещено"), ("no_display", "выключен"),
])
def test_answer_client_refused(monkeypatch, reason, phrase):
    online(PC({"status": "skipped", "reason": reason}))
    calls = model_says(monkeypatch, "не должно звучать")
    text, _ = run(ask.answer(MASTER, "?"))
    assert phrase in text and calls == []


def test_answer_offline_and_unsupported(monkeypatch):
    model_says(monkeypatch, "x")
    assert "не в сети" in run(ask.answer(MASTER, "?"))[0]
    online(PC(), features=())
    assert "не умеет" in run(ask.answer(MASTER, "?"))[0]


def test_question_from():
    assert ask.question_from("  ") == ask.DEFAULT_QUESTION
    assert len(ask.question_from("а" * 1000)) == ask.QUESTION_MAX


# ── хендлеры реестра ───────────────────────────────────────────────

def test_handler_v2_client(monkeypatch):
    import capabilities.vision as cv
    online(PC({"status": "ok", "image": SECRET_B64}))
    model_says(monkeypatch, "Вижу рабочий стол.")
    monkeypatch.setattr(ask, "pick_device", lambda d: MASTER)
    out = run(cv._vision_ask(ExecutionContext(device_id=MASTER, extra={"text": "глянь на экран"})))
    assert out == ("Вижу рабочий стол.", True)


def test_handler_legacy_client_marks_question(monkeypatch):
    import capabilities.vision as cv
    pc = online(PC(), features=())                         # старый agent/
    monkeypatch.setattr(ask, "pick_device", lambda d: MASTER)
    out = run(cv._vision_ask(ExecutionContext(device_ws=pc, device_id=MASTER,
                                              extra={"text": "что у меня на экране"})))
    assert out == AgentCommand("screenshot.describe")
    assert st._pending_describe[MASTER] == "что у меня на экране"


def test_handler_no_device(monkeypatch):
    import capabilities.vision as cv
    monkeypatch.setattr(ask, "pick_device", lambda d: None)
    text, ok = run(cv._vision_ask(ExecutionContext(extra={"text": "глянь"})))
    assert not ok and "компьютер" in text


def test_glance_toggle_persists(monkeypatch):
    import capabilities.vision as cv
    monkeypatch.setattr(config, "VISION_GLANCE", True)
    assert settings.glance_enabled() is False                 # по умолчанию выключено
    assert run(cv._glance_on(ExecutionContext()))[1] is True
    assert settings.glance_enabled() is True
    assert run(cv._glance_off(ExecutionContext()))[1] is True
    assert settings.glance_enabled() is False


def test_glance_on_when_server_switch_off(monkeypatch):
    import capabilities.vision as cv
    monkeypatch.setattr(config, "VISION_GLANCE", False)
    text, ok = run(cv._glance_on(ExecutionContext()))
    assert not ok and "выключено на сервере" in text


def test_broken_settings_file_means_off(tmp_path, monkeypatch):
    p = tmp_path / "broken.json"
    p.write_text("{не json", encoding="utf-8")
    monkeypatch.setattr(config, "VISION_SETTINGS_PATH", str(p))
    assert settings.glance_enabled() is False


# ── seen → промпт ──────────────────────────────────────────────────

def test_seen_context_line_and_ttl(monkeypatch):
    monkeypatch.setattr(config, "SEEN_TTL_S", 1800)
    seen.record(MASTER, "Terraria", "бой с боссом", "glance", now=1000.0)
    line = seen.context_line(now=1000.0 + 180)
    assert "3 мин назад" in line and "Terraria" in line and "сама глянула" in line
    assert seen.context_line(now=1000.0 + 1801) == ""


def test_prompt_screen_context_comes_from_seen():
    from modules.context import get_screen_context
    assert get_screen_context() == ""
    seen.record(MASTER, "", "таблица Excel", "ask")
    assert "таблица Excel" in get_screen_context()


# ── приватность: кадр нигде в логах ────────────────────────────────

def test_frame_never_logged(monkeypatch, caplog):
    caplog.set_level(logging.DEBUG)
    online(PC({"status": "ok", "image": SECRET_B64, "window": {"title": "t"}}))
    model_says(monkeypatch, "Ответ.\nВИДЕЛА: что-то")
    run(ask.answer(MASTER, "?"))
    online(PC({"status": "ok", "image": "плохой"}))
    run(ask.answer(MASTER, "?"))
    text = caplog.text
    assert SECRET_B64[:40] not in text and "SECRET-PIXELS" not in text
    assert "КиБ" in text                                       # размер — можно


def test_old_screen_context_is_dropped(monkeypatch):
    """Устаревший тихий кадр старого клиента не анализируется и не хранится."""
    from sakura_core import ws_protocol
    spawned = []
    monkeypatch.setattr(ws_protocol, "spawn", lambda *a, **k: spawned.append(a))
    run(ws_protocol.handle_screen_context(None, {"device_id": MASTER, "screenshot": SECRET_B64}, {}))
    assert spawned == [] and seen.latest() is None
