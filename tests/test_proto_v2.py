"""feat/proto-v2: протокол v2 (журнал чата) — через настоящий ws_handler.

Контракт: формы ответов совпадают с мок-сервером ветки feat/desktop-rewrite
(desktop/tools/mock_server.py + фикстуры, копия в tests/fixtures/proto_v2):
каждое поле фикстуры есть в ответе сервера и того же типа.

Run: python -m pytest tests/test_proto_v2.py -q
"""

import asyncio
import json
from pathlib import Path

import pytest
import websockets

import adapters.ws as wh
import config
import modules.state as st
import modules.tts_server as tts
import sakura_core.ws_protocol as proto
from modules import chat_log, device_manager, presence_sync, rituals
from modules.ws_auth import _WS_SECRET, MAX_WS_MESSAGE_SIZE
from sakura_core import voice_turns

FIXTURES = Path(__file__).parent / "fixtures" / "proto_v2"
MASTER, MASTER2, GUEST = "laptop", "pc", "phone"     # MASTER_DEVICES=laptop,pc
ANSWER = "Включаю «Мою волну»."


def _fixture(name):
    return json.loads((FIXTURES / f"{name}.json").read_text(encoding="utf-8"))


# ── контракт: поля и типы ──────────────────────────────────────────

def _assert_shape(sample: dict, actual: dict, where: str = ""):
    """Все поля образца есть в ответе, типы совпадают (int и float — число)."""
    for key, value in sample.items():
        assert key in actual, f"{where}: нет поля {key!r} в {actual}"
        if value is None or actual[key] is None:
            continue
        num = (int, float)
        if isinstance(value, num) and not isinstance(value, bool):
            assert isinstance(actual[key], num) and not isinstance(actual[key], bool), \
                f"{where}.{key}: {type(actual[key]).__name__}"
        else:
            assert isinstance(actual[key], type(value)), \
                f"{where}.{key}: {type(actual[key]).__name__} вместо {type(value).__name__}"
        if isinstance(value, dict):
            _assert_shape(value, actual[key], f"{where}.{key}")


def test_contract_message_matches_fixture():
    sample = _fixture("history")["messages"][0]
    m, _ = chat_log.append("assistant", "voice", "Сегодня у тебя:\n1. Созвон",
                           device=MASTER, meta={"turn_id": "0123456789ab"})
    wire = chat_log.to_wire(m)
    _assert_shape(sample, wire, "Message")
    assert isinstance(wire["ts"], float)
    roles = {x["role"] for x in _fixture("history")["messages"]}
    channels = {x["channel"] for x in _fixture("history")["messages"]}
    assert roles <= set(chat_log.ROLES) and channels <= set(chat_log.CHANNELS)


# ── стенд: настоящий сервер ────────────────────────────────────────

@pytest.fixture
def server(monkeypatch):
    saved = dict(st.connected_devices)
    st.connected_devices.clear()
    monkeypatch.setattr(st, "device_proto", {})
    monkeypatch.setattr(device_manager, "set_device_offline", lambda d: None)
    monkeypatch.setattr(presence_sync, "set_offline", lambda d: None)
    monkeypatch.setattr(rituals, "should_farewell", lambda: False)
    monkeypatch.setattr(proto, "update_device", lambda *a, **k: None)
    monkeypatch.setattr(proto, "should_greet_device", lambda d: False)
    monkeypatch.setattr(proto, "should_brief", lambda: False)
    monkeypatch.setattr(proto, "ps_update", lambda *a, **k: None)
    monkeypatch.setattr(voice_turns, "_last", {})
    monkeypatch.setattr(tts, "_last_end", {})
    monkeypatch.setattr(config, "PROTO_V2", True)

    async def _no_audio(text, websocket, device_id, emotion="спокойная"):
        return 1
    monkeypatch.setattr(tts, "_synthesize_and_stream", _no_audio)

    calls = []

    async def _inner(websocket, data, ctx, t_recv):
        """Ход: ответ буквальной репликой (как быстрый путь реестра)."""
        calls.append(data["text"])
        ws_dev = st.connected_devices.get(data["device_id"])
        await tts.stream_tts_to_device(ANSWER, ws_dev, data["device_id"], literal=True)
    monkeypatch.setattr(wh, "_handle_voice_command_inner", _inner)
    yield calls
    st.connected_devices.clear()
    st.connected_devices.update(saved)


class Client:
    def __init__(self, ws, device):
        self.ws, self.device, self.inbox = ws, device, []
        self._n = 0

    async def send(self, msg: dict, rid: bool = True):
        if rid and "request_id" not in msg:
            self._n += 1
            msg = {"request_id": f"r{self._n}", **msg}
        await self.ws.send(json.dumps({"token": _WS_SECRET, "device_id": self.device, **msg}))
        return msg.get("request_id")

    async def wait(self, pred, timeout=3.0):
        for i, m in enumerate(self.inbox):
            if pred(m):
                return self.inbox.pop(i)
        loop = asyncio.get_running_loop()
        end = loop.time() + timeout
        while True:
            m = json.loads(await asyncio.wait_for(self.ws.recv(), max(0.01, end - loop.time())))
            if pred(m):
                return m
            self.inbox.append(m)

    async def request(self, msg: dict):
        rid = await self.send(msg)
        return await self.wait(lambda m: m.get("request_id") == rid)

    async def silent(self, pred, timeout=0.3) -> bool:
        try:
            await self.wait(pred, timeout)
        except asyncio.TimeoutError:
            return True
        return False


async def _connect(uri, device, proto_v=2):
    ws = await websockets.connect(uri, max_size=None)
    c = Client(ws, device)
    reg = {"type": "register"}
    if proto_v:
        reg["proto"] = proto_v
    await c.send(reg, rid=False)
    return c


def _run(scenario):
    async def _go():
        async with websockets.serve(wh.ws_handler, "127.0.0.1", 0,
                                    max_size=MAX_WS_MESSAGE_SIZE,
                                    ping_interval=None) as srv:
            port = srv.sockets[0].getsockname()[1]
            return await asyncio.wait_for(scenario(f"ws://127.0.0.1:{port}"), 15)
    return asyncio.run(_go())


def _is(kind):
    return lambda m: m.get("type") == kind


def _answer_logged(m):
    """Ответ Сакуры записан: пуш chat_message assistant (после tts_end хода)."""
    return m.get("type") == "chat_message" and m["message"]["role"] == "assistant"


# ── регистрация ────────────────────────────────────────────────────

def test_register_v2_gets_registered_shape(server):
    async def sc(uri):
        c = await _connect(uri, MASTER)
        reg = await c.wait(_is("registered"))
        g = await _connect(uri, GUEST)
        reg_g = await g.wait(_is("registered"))
        return reg, reg_g
    reg, reg_g = _run(sc)
    sample = {"type": "registered", "device_id": "mostech", "proto": 2, "master": True}
    _assert_shape(sample, reg, "registered")
    assert reg == {"type": "registered", "device_id": MASTER, "proto": 2, "master": True}
    assert reg_g["master"] is False


def test_old_client_without_proto_gets_nothing_new(server):
    """Регистрация без proto (старый агент): ни registered, ни пушей."""
    async def sc(uri):
        old = await _connect(uri, MASTER, proto_v=None)
        new = await _connect(uri, MASTER2)
        await new.wait(_is("registered"))
        ack = await new.request({"type": "chat_send", "text": "привет", "client_msg_id": "c1"})
        await new.wait(_is("tts_end"))
        return ack, await old.silent(lambda m: True, timeout=0.5)
    ack, old_silent = _run(sc)
    assert ack["type"] == "chat_ack"
    assert old_silent, "старому клиенту ничего не пришло"


def test_proto_v2_disabled(server, monkeypatch):
    monkeypatch.setattr(config, "PROTO_V2", False)

    async def sc(uri):
        c = await _connect(uri, MASTER)
        r = await c.request({"type": "history_request"})
        return r, [m for m in c.inbox if m.get("type") == "registered"]
    r, regs = _run(sc)
    assert regs == []
    assert r["type"] == "error" and r["code"] == "unsupported"


# ── ошибки ─────────────────────────────────────────────────────────

def test_error_shapes_not_master_unsupported_bad_request(server):
    async def sc(uri):
        g = await _connect(uri, GUEST)
        e1 = await g.request({"type": "history_request"})
        e1b = await g.request({"type": "chat_send", "text": "x"})   # соединение живо
        c = await _connect(uri, MASTER)
        e2 = await c.request({"type": "devices_request"})
        e3 = await c.request({"type": "chat_send", "text": "  "})
        e4 = await c.request({"type": "history_request", "limit": "много"})
        e5 = await c.request({"type": "chat_delete", "id": "m999"})
        e6 = await c.request({"type": "chat_clear"})
        return e1, e1b, e2, e3, e4, e5, e6
    errs = _run(sc)
    sample = {"type": "error", "request_id": "r1", "code": "not_found", "message": "сценарий не найден"}
    for e in errs:
        _assert_shape(sample, e, "error")
        assert e["type"] == "error"
    codes = [e["code"] for e in errs]
    assert codes == ["not_master", "not_master", "unsupported", "bad_request",
                     "bad_request", "not_found", "bad_request"]


# ── chat_send → chat_ack → chat_message ×2, история ────────────────

def test_chat_send_ack_push_and_answer(server):
    calls = server

    async def sc(uri):
        c = await _connect(uri, MASTER)
        other = await _connect(uri, MASTER2)            # второе master-устройство
        guest = await _connect(uri, GUEST)
        for x in (c, other, guest):
            await x.wait(_is("registered"))
        ack = await c.request({"type": "chat_send", "text": "Включи музыку",
                               "client_msg_id": "u-1"})
        user_push = await other.wait(lambda m: m.get("type") == "chat_message"
                                     and m["message"]["role"] == "user")
        bot_push = await other.wait(lambda m: m.get("type") == "chat_message"
                                    and m["message"]["role"] == "assistant")
        end = await c.wait(_is("tts_end"))
        guest_silent = await guest.silent(_is("chat_message"))
        hist = await c.request({"type": "history_request", "limit": 50})
        return ack, user_push, bot_push, end, guest_silent, hist
    ack, user_push, bot_push, end, guest_silent, hist = _run(sc)

    assert ack == {"type": "chat_ack", "request_id": "r1", "client_msg_id": "u-1",
                   "id": ack["id"]} and isinstance(ack["id"], str)
    u, b = user_push["message"], bot_push["message"]
    sample = _fixture("history")["messages"][0]
    _assert_shape(sample, u, "chat_message.user")
    _assert_shape(sample, b, "chat_message.assistant")
    assert (u["id"], u["text"], u["channel"], u["device"]) == (ack["id"], "Включи музыку", "text", MASTER)
    assert (b["text"], b["channel"], b["reply_to"]) == (ANSWER, "text", u["id"])
    assert u["turn_id"] == b["turn_id"] == end["turn_id"]
    assert calls == ["Включи музыку"]
    assert guest_silent, "не-master устройству пуш не уходит"

    _assert_shape({"type": "history", "request_id": "r", "messages": []}, hist, "history")
    assert hist["has_more"] is False
    assert [m["text"] for m in hist["messages"]] == ["Включи музыку", ANSWER]
    for m in hist["messages"]:
        _assert_shape(sample, m, "history.messages[]")


def test_chat_send_retry_same_client_msg_id_not_processed_twice(server):
    calls = server

    async def sc(uri):
        c = await _connect(uri, MASTER)
        a1 = await c.request({"type": "chat_send", "text": "Погода", "client_msg_id": "u-7"})
        await c.wait(_is("tts_end"))
        await c.wait(_answer_logged)
        a2 = await c.request({"type": "chat_send", "text": "Погода", "client_msg_id": "u-7"})
        silent = await c.silent(_is("tts_end"), timeout=0.4)
        return a1, a2, silent
    a1, a2, silent = _run(sc)
    assert a1["id"] == a2["id"]
    assert calls == ["Погода"] and silent
    assert chat_log.count() == 2        # запрос + ответ, без дубля


def test_voice_command_logged_with_channel_voice(server):
    async def sc(uri):
        c = await _connect(uri, MASTER)
        await c.wait(_is("registered"))
        await c.send({"type": "voice_command", "text": "какая погода"}, rid=False)
        end = await c.wait(_is("tts_end"))
        bot = await c.wait(lambda m: m.get("type") == "chat_message"
                           and m["message"]["role"] == "assistant")
        return end, bot
    end, bot = _run(sc)
    msgs, _ = chat_log.history()
    assert [(m["role"], m["channel"], m["text"]) for m in msgs] == [
        ("user", "voice", "какая погода"), ("assistant", "voice", ANSWER)]
    assert msgs[0]["meta"]["turn_id"] == msgs[1]["meta"]["turn_id"] == end["turn_id"]
    assert msgs[1]["reply_to"] == msgs[0]["id"]
    assert bot["message"]["id"] == str(msgs[1]["id"])


def test_desktop_text_via_voice_command_channel_text(server):
    """Ядро desktop шлёт текст из окна как voice_command с channel: text."""
    async def sc(uri):
        c = await _connect(uri, MASTER)
        await c.send({"type": "voice_command", "text": "Погода", "channel": "text"}, rid=False)
        await c.wait(_is("tts_end"))
        await c.wait(_answer_logged)
    _run(sc)
    assert [m["channel"] for m in chat_log.history()[0]] == ["text", "text"]


def test_history_paging_read_search_delete_clear(server):
    for i in range(5):
        chat_log.append("user", "voice", f"заметка номер {i}", device=MASTER)

    async def sc(uri):
        c = await _connect(uri, MASTER)
        p1 = await c.request({"type": "history_request", "limit": 2})
        p2 = await c.request({"type": "history_request", "limit": 2,
                              "before_id": p1["messages"][0]["id"]})
        p3 = await c.request({"type": "history_request", "limit": 10,
                              "before_ts": p2["messages"][0]["ts"]})
        rd = await c.request({"type": "chat_read", "last_read_id": p1["messages"][-1]["id"]})
        sr = await c.request({"type": "chat_search", "q": "номер 3"})
        dl = await c.request({"type": "chat_delete", "id": p1["messages"][-1]["id"]})
        cl = await c.request({"type": "chat_clear", "confirm": True})
        empty = await c.request({"type": "history_request"})
        return p1, p2, p3, rd, sr, dl, cl, empty
    p1, p2, p3, rd, sr, dl, cl, empty = _run(sc)

    texts = lambda r: [m["text"] for m in r["messages"]]  # noqa: E731
    assert texts(p1) == ["заметка номер 3", "заметка номер 4"] and p1["has_more"]
    assert texts(p2) == ["заметка номер 1", "заметка номер 2"] and p2["has_more"]
    assert texts(p3) == ["заметка номер 0"] and not p3["has_more"]
    assert rd["type"] == "chat_read" and rd["last_read_id"] == p1["messages"][-1]["id"]
    assert chat_log.get_read(MASTER) == 0          # после chat_clear сброшено
    assert sr["type"] == "chat_search" and texts(sr) == ["заметка номер 3"]
    assert dl == {"type": "chat_delete", "request_id": dl["request_id"],
                  "id": p1["messages"][-1]["id"]}
    assert cl["type"] == "chat_clear" and cl["deleted"] == 4
    assert empty["messages"] == [] and empty["has_more"] is False


# ── пауза записи ───────────────────────────────────────────────────

def test_privacy_pause_and_resume_via_chat_send(server):
    calls = server

    async def sc(uri):
        c = await _connect(uri, MASTER)
        a1 = await c.request({"type": "chat_send", "text": "Не записывай.", "client_msg_id": "p1"})
        r1 = await c.wait(_is("reply"))
        a2 = await c.request({"type": "chat_send", "text": "секретное", "client_msg_id": "p2"})
        await c.wait(_is("tts_end"))
        a3 = await c.request({"type": "chat_send", "text": "Сакура, запись", "client_msg_id": "p3"})
        r3 = await c.wait(_is("reply"))
        a4 = await c.request({"type": "chat_send", "text": "обычное", "client_msg_id": "p4"})
        await c.wait(_is("tts_end"))
        await c.wait(_answer_logged)
        return a1, r1, a2, a3, r3, a4
    a1, r1, a2, a3, r3, a4 = _run(sc)
    assert a1["id"] is None and r1["text"] == "Хорошо, не записываю."
    assert a2["id"] is None, "на паузе не записано"
    assert a3["id"] is None and r3["text"] == "Запись снова включена."
    assert a4["id"] is not None
    assert calls == ["секретное", "обычное"], "команды паузы — не запросы к Сакуре"
    assert [m["text"] for m in chat_log.history()[0]] == ["обычное", ANSWER]


def test_privacy_command_by_voice(server):
    async def sc(uri):
        c = await _connect(uri, MASTER)
        await c.send({"type": "voice_command", "text": "не записывай"}, rid=False)
        await c.wait(_is("tts_end"))
    calls = server
    _run(sc)
    assert chat_log.is_paused() and calls == [] and chat_log.count() == 0


# ── сбой журнала не ломает ответ ───────────────────────────────────

def test_write_failure_does_not_break_answer(server, monkeypatch):
    def _boom(*a, **k):
        raise OSError("диск заполнен")
    monkeypatch.setattr(chat_log, "append", _boom)

    async def sc(uri):
        c = await _connect(uri, MASTER)
        ack = await c.request({"type": "chat_send", "text": "привет", "client_msg_id": "f1"})
        end = await c.wait(_is("tts_end"))
        return ack, end
    ack, end = _run(sc)
    assert ack["type"] == "chat_ack" and ack["id"] is None
    assert end["type"] == "tts_end"
    assert server == ["привет"], "ответ всё равно дан"
