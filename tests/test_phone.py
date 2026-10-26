"""Телефон: исполнитель phone.*, action_run, speak:false, SECURE_ONLY_MASTERS,
active/track в devices, vision_request с камеры (server/phone).

Run: python -m pytest tests/test_phone.py -q
"""

import asyncio
import json
import re

import pytest

import modules.state as st
from modules import presence_sync as ps
from sakura_core import bridge as br
from sakura_core import power_confirm as pcm
from sakura_core.registry import load


class WS:
    """Заглушка соединения: запоминает отправленное."""

    def __init__(self, secure=False):
        self.sent = []
        if secure:
            self.secure = True

    async def send(self, raw):
        self.sent.append(json.loads(raw))

    def of(self, kind):
        return [m for m in self.sent if m.get("type") == kind]


@pytest.fixture
def world(monkeypatch):
    """pc (активный) и phone (Noise, master) онлайн; озвучка/Telegram записываются."""
    import modules.tts_server as tts
    from modules import ws_auth
    pc, phone = WS(), WS(secure=True)
    monkeypatch.setattr(st, "connected_devices", {"pc": pc, "phone": phone})
    monkeypatch.setattr(st, "device_proto", {"pc": 2, "phone": 2})
    monkeypatch.setattr(ws_auth, "_MASTER_DEVICES", {"pc", "laptop", "phone"})
    ps.reset()
    monkeypatch.setattr(ps, "get_active_device", lambda: "pc")
    spoken, tg = [], []

    async def fake_tts(text, websocket, device_id, literal=False, emotion=None, stop=None,
                       listen=None, reply_kind="template"):
        spoken.append((device_id, text, reply_kind))
    monkeypatch.setattr(tts, "stream_tts_to_device", fake_tts)

    async def fake_tg(text, buttons=None):
        tg.append((text, buttons))
    monkeypatch.setattr(pcm, "_telegram", fake_tg)
    br.get_router().session.cancel()
    yield pc, phone, spoken, tg
    br.get_router().session.cancel()
    ps.reset()


def say(text, device="pc", source=None, ws=None):
    out = []

    async def speak(phrase, listen=None):
        out.append(phrase)
    asyncio.run(br.v3_fast_path(
        text, data={"active_window": ""}, device_ws=ws or st.connected_devices.get(device),
        device_id=device, register_command=lambda a, d: "cmd1", speak=speak,
        source=source or device))
    return out


# ── S1: маршрут phone.* ─────────────────────────────────────────────

CASES = [
    ("найди телефон", "phone.find", ""),
    ("где мой телефон", "phone.find", ""),
    ("включи не беспокоить на телефоне", "phone.dnd_on", ""),
    ("выключи не беспокоить на телефоне", "phone.dnd_off", ""),
    ("поставь будильник на телефоне на 7:30", "phone.alarm", "07:30"),
    ("будильник на телефоне на 19.05", "phone.alarm", "19:05"),
    ("поставь таймер на телефоне на 5 минут", "phone.timer", "300"),
    ("таймер на телефоне на 30 секунд", "phone.timer", "30"),
    ("таймер на телефоне на полчаса", "phone.timer", "1800"),
    ("включи фонарик на телефоне", "phone.flashlight", "on"),
    ("выключи фонарик на телефоне", "phone.flashlight", "off"),
    ("громкость на телефоне 40", "phone.volume", "40"),
    ("скопируй на телефон привет мир", "phone.clipboard", "привет мир"),
    ("открой ссылку на телефоне example.com/path", "phone.open_url", "https://example.com/path"),
    ("открой на телефоне ютуб", "phone.open_app", "ютуб"),
    ("пауза на телефоне", "phone.media_play_pause", ""),
    ("следующий трек на телефоне", "phone.media_next", ""),
    ("предыдущий трек на телефоне", "phone.media_prev", ""),
    ("отправь на телефон уведомление купить хлеб", "phone.notify", "купить хлеб"),
]


@pytest.mark.parametrize("phrase,action,arg", CASES)
def test_phone_command_routed_to_phone_not_active_pc(world, phrase, action, arg):
    pc, phone, _spoken, _tg = world
    say(phrase, "pc")
    (cmd,) = phone.of("command")
    assert cmd["action"] == action and cmd["arg"] == arg and cmd["id"] == "cmd1"
    assert pc.of("command") == [], "активному ПК phone.* не уходит"


def test_phone_offline_replies_error_and_does_not_queue(world):
    _pc, phone, spoken, _tg = world
    del st.connected_devices["phone"]
    out = say("найди телефон", "pc")
    assert out == [] and spoken == [("pc", "Телефон не на связи", "error")]
    assert st._pending_commands.get("cmd1") is None
    st.connected_devices["phone"] = phone
    say("найди телефон", "pc")
    assert len(phone.of("command")) == 1, "офлайн-команда не копится в очереди"


def test_phone_offline_from_telegram_goes_to_telegram(world):
    _pc, _phone, spoken, tg = world
    del st.connected_devices["phone"]
    say("найди телефон", "pc", source="telegram")
    assert tg == [("Телефон не на связи", None)] and spoken == []


def test_non_master_phone_gets_no_commands(world, monkeypatch):
    _pc, phone, spoken, _tg = world
    from modules import ws_auth
    monkeypatch.setattr(ws_auth, "_MASTER_DEVICES", {"pc", "laptop"})    # phone не master
    say("найди телефон", "pc")
    assert phone.of("command") == [] and spoken[-1][1] == "Телефон не на связи"


@pytest.mark.parametrize("phrase,ask", [
    ("поставь будильник на телефоне", "На какое время"),
    ("поставь таймер на телефоне", "На сколько"),
    ("громкость на телефоне", "Какую громкость"),
    ("открой на телефоне", "Какое приложение"),
])
def test_missing_argument_asks_instead_of_sending(world, phrase, ask):
    _pc, phone, spoken, _tg = world
    say(phrase, "pc")
    assert phone.of("command") == [] and ask in spoken[-1][1]


def test_phone_triggers_only_with_word_phone_and_do_not_overlap():
    decls = load()
    phone = {d.id: d for d in decls if d.id.startswith("phone.")}
    assert len(phone) == 14
    others = [d for d in decls if d.id not in phone]
    for d in phone.values():
        assert d.executor == "phone" and d.confirm is False and d.followup == "ack"
        for t in d.triggers:
            assert re.search(r"телефон", t), (d.id, t)
            rx = re.compile(rf"(?<!\w){re.escape(t)}(?!\w)", re.IGNORECASE)
            for o in decls:
                for ot in o.triggers:
                    if o.id != d.id:
                        assert not rx.search(ot), f"{d.id}:{t!r} внутри {o.id}:{ot!r}"
                    assert o.id == d.id or t != ot
    assert others, "реестр ПК на месте"


@pytest.mark.parametrize("phrase,action", [
    ("следующий трек", "music.next"), ("пауза", "music.play_pause"),
    ("предыдущий трек", "music.prev"), ("громкость 50", "system.volume"),
    ("напомни через 5 минут позвонить", "reminder.add"),
])
def test_pc_phrases_not_hijacked_by_phone(world, phrase, action):
    decision = asyncio.run(br.get_router().route(phrase))
    assert decision.action == action, (phrase, decision.action)
