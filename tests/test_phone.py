"""Телефон: исполнитель phone.*, action_run, speak:false, SECURE_ONLY_MASTERS,
active/track в devices, vision_request с камеры (server/phone).

Run: python -m pytest tests/test_phone.py -q
"""

import asyncio
import json
import re
from unittest.mock import AsyncMock

import pytest

import config
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


# ── S4: SECURE_ONLY_MASTERS ─────────────────────────────────────────

def test_secure_only_master_needs_noise_connection(monkeypatch):
    from modules import ws_auth
    monkeypatch.setattr(ws_auth, "_MASTER_DEVICES", {"laptop", "phone"})
    noise, token, loopback = WS(secure=True), WS(), WS()
    loopback.remote_address = ("127.0.0.1", 5555)
    monkeypatch.setattr(st, "connected_devices", {"phone": noise})
    assert ws_auth.is_master_device("phone") is True
    assert ws_auth.is_master_device("phone", noise) is True
    for plain in (token, loopback):                      # токен и loopback master не дают
        assert ws_auth.is_master_device("phone", plain) is False
        monkeypatch.setitem(st.connected_devices, "phone", plain)
        assert ws_auth.is_master_device("phone") is False
    monkeypatch.setattr(st, "connected_devices", {})
    assert ws_auth.is_master_device("phone") is False, "не подключён — не master"


def test_other_masters_unaffected_and_config_switch(monkeypatch):
    from modules import ws_auth
    monkeypatch.setattr(ws_auth, "_MASTER_DEVICES", {"laptop", "phone"})
    monkeypatch.setattr(st, "connected_devices", {"laptop": WS(), "phone": WS()})
    assert ws_auth.is_master_device("laptop") is True       # ПК: токен/loopback как раньше
    monkeypatch.setattr(config, "SECURE_ONLY_MASTERS", set())
    assert ws_auth.is_master_device("phone") is True        # правило выключено env-ом
    assert config.PHONE_DEVICES == ["phone"]


def test_registered_master_flag_follows_transport(monkeypatch):
    from modules import ws_auth
    from sakura_core import proto_v2
    monkeypatch.setattr(ws_auth, "_MASTER_DEVICES", {"phone"})
    monkeypatch.setattr(config, "PROTO_V2", True)
    monkeypatch.setattr(st, "device_proto", {})
    out = {}
    for name, ws in (("noise", WS(secure=True)), ("token", WS())):
        monkeypatch.setitem(st.connected_devices, "phone", ws)
        asyncio.run(proto_v2.on_register(ws, {"device_id": "phone", "proto": 2}))
        out[name] = ws.of("registered")[0]["master"]
    assert out == {"noise": True, "token": False}


def test_non_master_phone_requests_rejected_in_v2(monkeypatch):
    from modules import ws_auth
    from sakura_core import proto_v2
    monkeypatch.setattr(ws_auth, "_MASTER_DEVICES", {"phone"})
    monkeypatch.setattr(config, "PROTO_V2", True)
    plain = WS()
    monkeypatch.setattr(st, "connected_devices", {"phone": plain})
    asyncio.run(proto_v2.handle(plain, {"type": "devices_request", "request_id": "r", "device_id": "phone"}, {}))
    assert plain.sent[-1]["code"] == "not_master"


def test_e2e_noise_phone_is_master_token_phone_is_not(monkeypatch):
    import websockets

    from modules import ws_auth
    from securechannel.client import connect_session
    from tests.test_securechannel_ws import paired_device, until
    monkeypatch.setattr(ws_auth, "_MASTER_DEVICES", {"laptop", "pc", "phone"})
    monkeypatch.setattr(config, "SECURE_CHANNEL", "optional")
    monkeypatch.setattr(config, "PROTO_V2", True)

    async def sc(uri):
        priv, info = await paired_device(uri, hint="phone")
        async with websockets.connect(uri, max_size=None) as ws:
            c = await connect_session(ws, priv, info["server_pub_bytes"], device_id="phone")
            await c.send(json.dumps({"type": "register", "proto": 2}))
            noise = await until(c, lambda m: m.get("type") == "registered")
        async with websockets.connect(uri) as ws2:               # тот же id по токену
            await ws2.send(json.dumps({"type": "register", "device_id": "phone",
                                       "token": ws_auth._WS_SECRET, "proto": 2}))
            token = json.loads(await asyncio.wait_for(ws2.recv(), 3))
        return noise, token
    import tests.test_securechannel_ws as T
    noise, token = _run_with_env(monkeypatch, T, sc)
    assert noise["master"] is True and token["master"] is False


def _run_with_env(monkeypatch, T, scenario):
    """Стенд test_securechannel_ws без pytest-фикстуры: те же подмены вручную."""
    import modules.state as _st
    import sakura_core.ws_protocol as proto
    from modules import device_manager, presence_sync, rituals
    saved = dict(_st.connected_devices)
    _st.connected_devices.clear()
    monkeypatch.setattr(_st, "device_proto", {})
    monkeypatch.setattr(device_manager, "set_device_offline", lambda d, r=None: None)
    monkeypatch.setattr(presence_sync, "set_offline", lambda d: None)
    monkeypatch.setattr(rituals, "should_farewell", lambda: False)
    monkeypatch.setattr(proto, "update_device", lambda *a, **k: None)
    monkeypatch.setattr(proto, "should_greet_device", lambda d: False)
    monkeypatch.setattr(proto, "should_brief", lambda: False)
    monkeypatch.setattr(proto, "ps_update", lambda *a, **k: None)
    try:
        return T.run(scenario)
    finally:
        _st.connected_devices.clear()
        _st.connected_devices.update(saved)


# ── S3: speak:false ─────────────────────────────────────────────────

def _silent_turn(ws, speak=False):
    """Контекст хода как у voice_turns.start (без запуска задачи)."""
    from sakura_core import voice_turns
    turn = voice_turns.Turn(turn_id="t1", device_id="laptop", ws=ws, speak=speak)
    return voice_turns, voice_turns.use(turn), turn


def test_silent_turn_sends_reply_only_without_synthesis(monkeypatch):
    import modules.tts_server as tts
    ws = WS()

    async def boom(*a, **k):
        raise AssertionError("Live-синтез в тихом ходе не нужен")
    monkeypatch.setattr(tts, "_synthesize_and_stream", boom)
    monkeypatch.setattr(tts, "_live_synthesize", boom)
    vt, tok, _turn = _silent_turn(ws)
    try:
        async def go():
            await tts.stream_tts_to_device("Готово, Мастер.", ws, "laptop", literal=True,
                                           reply_kind="llm")
            await tts._send_end(ws, "laptop")
            await tts.ensure_turn_end(ws, "laptop", 0.0)
        asyncio.run(go())
    finally:
        vt.reset(tok)
    assert [m["type"] for m in ws.sent] == ["reply"]
    assert ws.sent[0]["text"] == "Готово, Мастер." and ws.sent[0]["turn_id"] == "t1"
    assert not ws.of("tts_chunk") and not ws.of("tts_end")


def test_silent_turn_does_not_open_live_session(monkeypatch):
    import modules.tts_server as tts
    monkeypatch.setattr(tts, "_preconnect_task", None)
    vt, tok, _ = _silent_turn(WS())
    try:
        assert asyncio.run(tts.preconnect()) is False
    finally:
        vt.reset(tok)
    assert tts._preconnect_task is None


def test_spoken_turn_still_closes_with_tts_end(monkeypatch):
    import modules.tts_server as tts
    ws = WS()
    vt, tok, turn = _silent_turn(ws, speak=True)
    try:
        asyncio.run(tts._send_end(ws, "laptop"))
    finally:
        vt.reset(tok)
    assert ws.of("tts_end") and turn.ended


def test_llm_voice_reply_in_silent_turn_skips_tts(monkeypatch):
    """ask_gemini_voice в тихом ходе: генерация без стрима в TTS, текст — reply-ем."""
    from sakura_core import llm
    ws = WS()
    seen = {}

    async def fake_generate(*a, **k):
        return "Привет, Мастер."

    async def no_stream(*a, **k):
        seen["stream"] = True
        return "", "neutral"
    monkeypatch.setattr(llm, "generate", fake_generate)
    monkeypatch.setattr("adapters.voice.stream_llm_to_tts", no_stream)
    monkeypatch.setattr(llm, "_build_system", AsyncMock(return_value="system"))
    monkeypatch.setattr("config.get_active_key", lambda: "k")
    monkeypatch.setattr("config.mark_key_used", lambda k: None)
    vt, tok, _ = _silent_turn(ws)
    try:
        text, _emotion = asyncio.run(llm.ask_gemini_voice("привет", websocket=ws, device_id="laptop"))
    finally:
        vt.reset(tok)
    assert "stream" not in seen and "Привет" in text
    assert [m["type"] for m in ws.sent] == ["reply"] and ws.of("reply")[0]["kind"] == "llm"


# ── S6: vision_request с камеры ─────────────────────────────────────

JPEG = b"\xff\xd8\xff\xe0" + b"\x00" * 64


def _vision(monkeypatch, secure=True, master=True, **fields):
    """vision_request.handle с подменой модели; возвращает (ответы, промпт, лог)."""
    import base64

    from modules import ws_auth
    from sakura_core import llm, vision_request
    seen = {}

    async def fake_generate(parts, **kw):
        seen["parts"], seen["kw"] = parts, kw
        return "На столе чашка и книга."
    monkeypatch.setattr(llm, "generate", fake_generate)
    monkeypatch.setattr(ws_auth, "_MASTER_DEVICES", {"phone"} if master else set())
    ws = WS(secure=secure)
    monkeypatch.setattr(st, "connected_devices", {"phone": ws})
    data = {"type": "vision_request", "request_id": "v1", "device_id": "phone",
            "image": base64.b64encode(JPEG).decode(), **fields}
    asyncio.run(vision_request.handle(ws, data))
    return ws.sent, seen


def test_camera_frame_uses_camera_prompt_and_replies(monkeypatch, caplog):
    import logging
    caplog.set_level(logging.DEBUG)
    sent, seen = _vision(monkeypatch, source="camera", question="Что у меня на столе?")
    assert sent[0]["type"] == "reply" and sent[0]["request_id"] == "v1" and sent[0]["kind"] == "llm"
    assert sent[0]["text"] == "На столе чашка и книга."
    prompt = seen["parts"][1].text
    assert "кадр с камеры телефона Мастера" in prompt and "Что у меня на столе?" in prompt
    assert "до трёх предложений" in prompt and "не пересказывай" in prompt
    assert "кадр одного окна" not in prompt
    # кадр не попадает в лог: только размер и длина вопроса
    import base64
    assert base64.b64encode(JPEG).decode() not in caplog.text
    assert "camera кадр" in caplog.text


def test_window_frame_keeps_window_prompt(monkeypatch):
    _sent, seen = _vision(monkeypatch)
    assert "кадр одного окна" in seen["parts"][1].text and "Что в этом окне?" in seen["parts"][1].text
    _sent, seen = _vision(monkeypatch, source="window")
    assert "кадр одного окна" in seen["parts"][1].text


def test_camera_default_question_and_unknown_source(monkeypatch):
    sent, seen = _vision(monkeypatch, source="camera")
    assert "Что на кадре?" in seen["parts"][1].text
    sent, seen = _vision(monkeypatch, source="screen")
    assert sent[0]["code"] == "bad_request" and "parts" not in seen


def test_camera_frame_rules_same_as_window(monkeypatch):
    import base64
    assert _vision(monkeypatch, source="camera", image="x" * 2_000_001)[0][0]["code"] == "bad_request"
    assert _vision(monkeypatch, source="camera", image="не base64!")[0][0]["code"] == "bad_request"
    assert _vision(monkeypatch, source="camera",
                   image=base64.b64encode(b"GIF89a....").decode())[0][0]["code"] == "bad_request"
    assert _vision(monkeypatch, source="camera", master=False)[0][0]["code"] == "not_master"
    assert _vision(monkeypatch, source="camera", secure=False)[0][0]["code"] in ("not_master", "secure_channel_required")
