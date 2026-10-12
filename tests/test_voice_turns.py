"""fix/voice-reply-text: текст голосового ответа в окно и turn_id ходов.

  * после голосового ответа устройству-источнику уходит
    {"type": "reply", "text": …, "turn_id": …} — до tts_end хода, без
    тегов тона, не длиннее 4000 символов, только master-устройствам;
  * у каждого голосового хода turn_id (uuid4 hex[:12]) — в tts_chunk,
    tts_end и reply;
  * новый запрос того же устройства вытесняет незавершённый ход: стрим и
    предсинтез отменены, старый ход закрыт tts_end со своим turn_id ДО
    первого сообщения нового; два хода одного устройства не идут
    параллельно.

Run: python -m pytest tests/test_voice_turns.py -q
"""

import asyncio
import json
import re
import time
from unittest.mock import AsyncMock

import pytest
import websockets

import adapters.voice as voice_mod
import adapters.ws as wh
import config
import memory.memory as mem
import modules.acks as acks
import modules.mood_broadcast as mood_broadcast
import modules.state as st
import modules.tts_cache as tts_cache
import modules.tts_server as tts
import modules.web_search as web_search
import modules.ws_auth as ws_auth
import sakura_core.llm as llm
import sakura_core.ws_protocol as proto
from modules import device_manager, presence_sync, rituals
from modules.ws_auth import _WS_SECRET, MAX_WS_MESSAGE_SIZE
from sakura_core import voice_turns
from sakura_core.router import Decision
from tests.test_turn_end import FakeWS, _data, _mk_ctx, _setup

TURN_ID = re.compile(r"^[0-9a-f]{12}$")
DEV = "laptop"

# Длинные предложения: ответ сразу «длинный» — стадии TTS стартуют по ходу
# стрима, а не одной стадией в конце.
SENTENCES = [
    "Это первое предложение достаточно длинного ответа, чтобы стадия стартовала. ",
    "[ТОН: тепло] Второе предложение идёт следом и тоже уходит в синтез. ",
    "Третье предложение продолжает рассказ, пока Мастер слушает. ",
    "Четвёртое предложение закрывает длинный ответ.",
]


async def _slow_tokens(contents, **kwargs):
    for s in SENTENCES:
        await asyncio.sleep(0.05)
        yield s


async def _fake_live(text, emotion, on_packet, label="", strict=False):
    for _ in range(3):
        await on_packet(b"PCM")
        await asyncio.sleep(0.03)
    return 3


@pytest.fixture
def voice(monkeypatch):
    """Настоящие handle_voice_command → ask_gemini_voice → stream_llm_to_tts
    и настоящие отправщики tts_chunk/tts_end/reply; подменены LLM, синтез,
    история, сборка системного промпта."""
    ws = FakeWS()
    _setup(monkeypatch, ws, decision=Decision(None, "conversation"))
    monkeypatch.setattr(voice_turns, "_last", {})
    monkeypatch.setattr(llm, "stream_tokens", _slow_tokens)
    monkeypatch.setattr(voice_mod, "_live_synthesize", _fake_live)
    monkeypatch.setattr(voice_mod, "_make_audio_sender", tts._make_audio_sender)
    monkeypatch.setattr(config, "get_active_key", lambda: "test-key")
    monkeypatch.setattr(config, "mark_key_used", lambda key: None)

    async def _build_system(query=""):
        return "system"
    monkeypatch.setattr(llm, "_build_system", _build_system)
    monkeypatch.setattr(llm, "_build_contents", lambda *a, **k: [])
    monkeypatch.setattr(web_search, "needs_search", lambda t: False)
    monkeypatch.setattr(mem, "add_to_history", lambda role, text: None)
    monkeypatch.setattr(mood_broadcast, "broadcast_mood_after_reply",
                        AsyncMock(return_value=None))
    monkeypatch.setattr(ws_auth, "is_master_device", lambda d: d == DEV)

    outcome: dict[str, list] = {"completed": [], "cancelled": []}

    async def ask_voice(**kw):
        try:
            r = await llm.ask_gemini_voice(**kw)
        except asyncio.CancelledError:
            outcome["cancelled"].append(kw["user_message"])
            raise
        outcome["completed"].append(kw["user_message"])
        return r

    return ws, _mk_ctx(ask_voice), outcome


def _start(ws, ctx, text):
    return voice_turns.start(
        DEV, ws, lambda: wh.handle_voice_command(None, _data(text), ctx))


async def _wait_for(pred, timeout=5.0):
    loop = asyncio.get_running_loop()
    end = loop.time() + timeout
    while not pred():
        assert loop.time() < end, "условие не наступило"
        await asyncio.sleep(0.01)


def _of(ws, turn, kind=None):
    return [m for m in ws.sent if m.get("turn_id") == turn.turn_id
            and (kind is None or m["type"] == kind)]


def _assert_not_interleaved(ws, turns):
    """Сообщения ходов идут блоками по порядку ходов: ход i+1 начинается
    только после последнего сообщения хода i."""
    order = [m.get("turn_id") for m in ws.sent]
    ids = [t.turn_id for t in turns]
    seen = [i for i in order if i in ids]
    blocks = [k for j, k in enumerate(seen) if j == 0 or seen[j - 1] != k]
    assert blocks == [i for i in ids if i in blocks], blocks


# ── один ход ───────────────────────────────────────────────────────


def test_reply_text_with_turn_id_before_tts_end(voice):
    """Полный текст ответа уходит reply-ем с turn_id, до tts_end хода."""
    ws, ctx, outcome = voice

    async def _go():
        t = _start(ws, ctx, "расскажи что-нибудь")
        await asyncio.wait_for(t.task, 10)
        return t
    t = asyncio.run(_go())

    assert TURN_ID.match(t.turn_id)
    assert outcome["completed"] and not outcome["cancelled"]
    # каждое сообщение хода — с его turn_id
    assert all(m.get("turn_id") == t.turn_id for m in ws.sent), ws.sent
    chunks = _of(ws, t, "tts_chunk")
    replies = _of(ws, t, "reply")
    ends = _of(ws, t, "tts_end")
    assert chunks and len(replies) == 1 and len(ends) == 1
    reply = replies[0]
    assert "[ТОН" not in reply["text"]
    assert reply["text"].startswith("Это первое предложение")
    assert reply["text"].endswith("закрывает длинный ответ.")
    assert reply["device_id"] == DEV
    kinds = [m["type"] for m in ws.sent]
    assert kinds.index("reply") < kinds.index("tts_end")
    assert kinds[-1] == "tts_end"
    assert voice_turns.active(DEV) is None


def test_no_reply_for_non_master(voice, monkeypatch):
    """Не master-устройство: озвучка как была, reply не уходит."""
    ws, ctx, _ = voice
    monkeypatch.setattr(ws_auth, "is_master_device", lambda d: False)

    async def _go():
        t = _start(ws, ctx, "привет")
        await asyncio.wait_for(t.task, 10)
    asyncio.run(_go())

    kinds = [m["type"] for m in ws.sent]
    assert "reply" not in kinds
    assert "tts_chunk" in kinds and kinds.count("tts_end") == 1


def test_handler_without_turn_unchanged(voice):
    """Прямой вызов обработчика (вне хода) — сообщения без turn_id, как раньше."""
    ws, ctx, _ = voice
    asyncio.run(wh.handle_voice_command(None, _data("привет"), ctx))
    assert ws.sent and all("turn_id" not in m for m in ws.sent)
    assert [m for m in ws.sent if m["type"] == "reply"]


def test_reply_text_strips_tone_and_caps(monkeypatch):
    monkeypatch.setattr(ws_auth, "is_master_device", lambda d: True)
    ws = FakeWS()
    asyncio.run(voice_turns.send_reply(ws, DEV, "[ТОН: тепло] " + "а" * 5000))
    (m,) = ws.sent
    assert m["type"] == "reply" and "turn_id" not in m
    assert m["text"] == "а" * voice_turns.REPLY_MAX_CHARS == "а" * 4000


def test_reply_send_error_does_not_raise(monkeypatch):
    monkeypatch.setattr(ws_auth, "is_master_device", lambda d: True)
    assert asyncio.run(voice_turns.send_reply(FakeWS(closed=True), DEV, "текст")) is False


# ── вытеснение ─────────────────────────────────────────────────────


def test_second_request_cancels_first(voice):
    """Два быстрых запроса: один активный поток, старый отменён и закрыт
    tts_end со своим turn_id до первого сообщения нового."""
    ws, ctx, outcome = voice

    async def _go():
        t1 = _start(ws, ctx, "расскажи длинную историю")
        await _wait_for(lambda: _of(ws, t1, "tts_chunk"))
        t2 = _start(ws, ctx, "а теперь коротко")
        assert voice_turns.active(DEV) is t2
        await asyncio.wait_for(t2.task, 10)
        await asyncio.sleep(0.2)            # запоздавшие пакеты t1, если бы были
        return t1, t2
    t1, t2 = asyncio.run(_go())

    assert t1.turn_id != t2.turn_id
    assert t1.task.cancelled() and t1.cancelled
    assert outcome["cancelled"] == ["расскажи длинную историю"]
    assert outcome["completed"] == ["а теперь коротко"]
    assert all(m.get("turn_id") in (t1.turn_id, t2.turn_id) for m in ws.sent), ws.sent

    # старый ход: звук был, текста нет, ровно один tts_end
    assert _of(ws, t1, "tts_chunk")
    assert not _of(ws, t1, "reply")
    assert len(_of(ws, t1, "tts_end")) == 1
    # новый ход: звук, текст, один tts_end последним
    assert _of(ws, t2, "tts_chunk")
    assert len(_of(ws, t2, "reply")) == 1
    assert len(_of(ws, t2, "tts_end")) == 1
    assert ws.sent[-1] == {**ws.sent[-1], "type": "tts_end", "turn_id": t2.turn_id}
    # потоки не пересекаются: всё от t1 (с его tts_end) — раньше t2
    _assert_not_interleaved(ws, [t1, t2])
    last_t1 = max(i for i, m in enumerate(ws.sent) if m["turn_id"] == t1.turn_id)
    assert ws.sent[last_t1]["type"] == "tts_end"


def test_three_rapid_requests_only_last_survives(voice):
    """Три запроса подряд без пауз: доживает последний, каждый вытесненный
    закрыт ровно одним tts_end, параллельных потоков нет."""
    ws, ctx, outcome = voice

    async def _go():
        t1 = _start(ws, ctx, "раз")
        await asyncio.sleep(0)
        t2 = _start(ws, ctx, "два")
        await asyncio.sleep(0)
        t3 = _start(ws, ctx, "три")
        await asyncio.wait_for(t3.task, 10)
        await asyncio.sleep(0.2)
        return t1, t2, t3
    t1, t2, t3 = asyncio.run(_go())

    assert outcome["completed"] == ["три"]
    for t in (t1, t2):
        assert t.cancelled
        assert len(_of(ws, t, "tts_end")) == 1, ws.sent
        assert not _of(ws, t, "reply")
    assert len(_of(ws, t3, "reply")) == 1
    assert len(_of(ws, t3, "tts_end")) == 1
    _assert_not_interleaved(ws, [t1, t2, t3])


def test_late_ack_of_superseded_turn_is_silent(monkeypatch):
    """Подтверждение команды прошлого хода (command_result пришёл, когда
    начался новый) не озвучивается; прошлый ход закрыт своим tts_end."""
    monkeypatch.setattr(voice_turns, "_last", {})
    monkeypatch.setattr(tts, "_last_end", {})
    monkeypatch.setattr(acks, "_pending", {})
    monkeypatch.setattr(acks, "_armed_at", {})
    monkeypatch.setattr(acks, "_speak_locks", {})
    monkeypatch.setattr(config, "ACKS_ENABLED", True)
    monkeypatch.setattr(config, "ACK_PENDING_S", 5.0)

    async def _get_pcm(text):
        return b"\x01\x00" * 4800, "память"
    monkeypatch.setattr(tts_cache, "get_pcm", _get_pcm)
    ws = FakeWS()

    async def _turn_with_command():
        assert acks.arm("cmd1", ws=ws, device_id=DEV, action="music.next")

    async def _turn_plain():
        await tts.ensure_turn_end(ws, DEV, time.monotonic())

    async def _go():
        t1 = voice_turns.start(DEV, ws, _turn_with_command)
        await t1.task                       # ход закончен, ждёт подтверждения
        assert not t1.ended
        t2 = voice_turns.start(DEV, ws, _turn_plain)
        await t2.task
        await acks.on_result("cmd1", True, "")
        return t1, t2
    t1, t2 = asyncio.run(_go())

    assert not _of(ws, t1, "tts_chunk"), "подтверждение прошлого хода прозвучало"
    assert len(_of(ws, t1, "tts_end")) == 1
    assert len(_of(ws, t2, "tts_end")) == 1
    _assert_not_interleaved(ws, [t1, t2])


def test_ack_carries_turn_id(monkeypatch):
    """Подтверждение своего (не вытесненного) хода — с его turn_id."""
    monkeypatch.setattr(voice_turns, "_last", {})
    monkeypatch.setattr(tts, "_last_end", {})
    monkeypatch.setattr(acks, "_pending", {})
    monkeypatch.setattr(acks, "_armed_at", {})
    monkeypatch.setattr(acks, "_speak_locks", {})
    monkeypatch.setattr(config, "ACKS_ENABLED", True)
    monkeypatch.setattr(config, "ACK_PENDING_S", 5.0)

    async def _get_pcm(text):
        return b"\x01\x00" * 4800, "память"
    monkeypatch.setattr(tts_cache, "get_pcm", _get_pcm)
    ws = FakeWS()

    async def _turn():
        acks.arm("cmd1", ws=ws, device_id=DEV, action="music.next")

    async def _go():
        t = voice_turns.start(DEV, ws, _turn)
        await t.task
        await acks.on_result("cmd1", True, "")
        return t
    t = asyncio.run(_go())

    assert ws.sent and all(m["turn_id"] == t.turn_id for m in ws.sent)
    assert [m["type"] for m in ws.sent][-1] == "tts_end"
    assert len(_of(ws, t, "tts_end")) == 1


# ── настоящий сокет: цикл не ждёт хода ─────────────────────────────


@pytest.fixture
def server_env(monkeypatch):
    saved = dict(st.connected_devices)
    st.connected_devices.clear()
    monkeypatch.setattr(device_manager, "set_device_offline", lambda d: None)
    monkeypatch.setattr(presence_sync, "set_offline", lambda d: None)
    monkeypatch.setattr(rituals, "should_farewell", lambda: False)
    monkeypatch.setattr(proto, "update_device", lambda *a, **k: None)
    monkeypatch.setattr(proto, "should_greet_device", lambda d: False)
    monkeypatch.setattr(proto, "should_brief", lambda: False)
    monkeypatch.setattr(proto, "ps_update", lambda *a, **k: None)
    monkeypatch.setattr(ws_auth, "is_master_device", lambda d: d == DEV)
    monkeypatch.setattr(voice_turns, "_last", {})
    monkeypatch.setattr(tts, "_last_end", {})

    async def _slow_turn(websocket, data, ctx):
        """Голосовой ход: 2с звука, затем текст; tts_end — как в handle_voice_command."""
        t_recv = time.monotonic()
        try:
            send = tts._make_audio_sender(websocket, DEV)
            for _ in range(40):
                await send(b"PCM")
                await asyncio.sleep(0.05)
            await voice_turns.send_reply(websocket, DEV, f"ответ на «{data['text']}»")
        finally:
            await tts.ensure_turn_end(websocket, DEV, t_recv)
    monkeypatch.setattr(wh, "handle_voice_command", _slow_turn)
    yield
    st.connected_devices.clear()
    st.connected_devices.update(saved)


def test_ws_handler_new_voice_command_preempts_running_turn(server_env):
    async def scenario(uri):
        async with websockets.connect(uri, max_size=None) as c:
            async def send(msg):
                await c.send(json.dumps({"token": _WS_SECRET, "device_id": DEV, **msg}))
            await send({"type": "register"})
            await send({"type": "voice_command", "text": "первый"})
            got = []
            while not got or got[-1]["type"] != "tts_chunk":
                got.append(json.loads(await c.recv()))
            await send({"type": "voice_command", "text": "второй"})
            while True:
                m = json.loads(await asyncio.wait_for(c.recv(), 5))
                got.append(m)
                if m["type"] == "tts_end" and m["turn_id"] != got[0]["turn_id"]:
                    return got

    async def _go():
        async with websockets.serve(wh.ws_handler, "127.0.0.1", 0,
                                    max_size=MAX_WS_MESSAGE_SIZE,
                                    ping_interval=None) as server:
            port = server.sockets[0].getsockname()[1]
            return await asyncio.wait_for(scenario(f"ws://127.0.0.1:{port}"), 10)
    got = asyncio.run(_go())

    t1, t2 = got[0]["turn_id"], got[-1]["turn_id"]
    assert TURN_ID.match(t1) and TURN_ID.match(t2) and t1 != t2
    first = [m for m in got if m["turn_id"] == t1]
    second = [m for m in got if m["turn_id"] == t2]
    # первый ход оборван (не все 40 пакетов, без текста) и закрыт своим tts_end
    assert len(first) < 41 and first[-1]["type"] == "tts_end"
    assert not [m for m in first if m["type"] == "reply"]
    # второй — до конца, с текстом
    assert [m["text"] for m in second if m["type"] == "reply"] == ["ответ на «второй»"]
    # блоки не пересекаются
    idx_end1 = got.index(first[-1])
    assert all(got.index(m) > idx_end1 for m in second)
