"""feat/proto-v2: точки записи журнала чата (sakura_core/chat_hooks.py).

Голосовой ход (настоящий потоковый ответ), подтверждения, Telegram
(входящие, медиа, команды, исходящие, проактивные), /export_chat,
/clear_chat.

Run: python -m pytest tests/test_chat_hooks.py -q
"""

import asyncio
import time
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from aiogram.methods import SendMessage, SendPhoto, SendSticker

import config
import modules.acks as acks
import modules.tts_cache as tts_cache
import modules.tts_server as tts
import modules.users as users
from adapters.commands import cmd_clear_chat_impl, cmd_export_chat_impl
from modules import chat_log
from sakura_core import chat_hooks, voice_turns
from tests.test_turn_end import FakeWS
from tests.test_voice_turns import DEV, _start, _wait_for, voice  # noqa: F401  (фикстура)

MASTER_ID = int(config.MASTER_ID)


def _log():
    return [(m["role"], m["channel"], m["text"]) for m in chat_log.history()[0]]


# ── голосовой ход ──────────────────────────────────────────────────


def test_streamed_voice_answer_logged_once_without_tone(voice):  # noqa: F811
    ws, ctx, _ = voice

    async def _go():
        t = _start(ws, ctx, "расскажи что-нибудь")
        await asyncio.wait_for(t.task, 10)
        return t
    t = asyncio.run(_go())

    msgs = chat_log.history()[0]
    assert [(m["role"], m["channel"]) for m in msgs] == [("user", "voice"), ("assistant", "voice")]
    user, bot = msgs
    assert user["text"] == "расскажи что-нибудь"
    assert "[ТОН" not in bot["text"] and bot["text"].startswith("Это первое предложение")
    assert bot["reply_to"] == user["id"]
    assert user["meta"]["turn_id"] == bot["meta"]["turn_id"] == t.turn_id
    assert "interrupted" not in bot["meta"]


def test_superseded_turn_answer_not_logged(voice):  # noqa: F811
    """Вытесненный ход: его потоковый ответ не договорён — в журнал не идёт."""
    ws, ctx, _ = voice

    async def _go():
        _start(ws, ctx, "длинная история")
        await _wait_for(lambda: any(m.get("type") == "tts_chunk" for m in ws.sent))
        t2 = _start(ws, ctx, "а теперь другое")
        await asyncio.wait_for(t2.task, 10)
    asyncio.run(_go())

    assert [(r, t[:12]) for r, _, t in _log()] == [
        ("user", "длинная исто"), ("user", "а теперь дру"), ("assistant", "Это первое п")]


def test_literal_phrase_then_cancel_marked_interrupted(monkeypatch):
    monkeypatch.setattr(voice_turns, "_last", {})
    monkeypatch.setattr(tts, "_last_end", {})

    async def _synth(text, websocket, device_id, emotion="спокойная"):
        return 1
    monkeypatch.setattr(tts, "_synthesize_and_stream", _synth)
    ws = FakeWS()
    started = asyncio.Event()

    async def _turn():
        await chat_hooks.on_voice_request({"device_id": DEV, "text": "прочитай список"},
                                          AsyncMock())
        await tts.stream_tts_to_device("Первый пункт списка.", ws, DEV, literal=True)
        started.set()
        await asyncio.sleep(10)

    async def _plain():
        await chat_hooks.on_voice_request({"device_id": DEV, "text": "хватит"}, AsyncMock())

    async def _go():
        voice_turns.start(DEV, ws, _turn)
        await started.wait()
        t2 = voice_turns.start(DEV, ws, _plain)
        await t2.task
    asyncio.run(_go())

    msgs = chat_log.history()[0]
    assert [m["text"] for m in msgs] == ["прочитай список", "Первый пункт списка.", "хватит"]
    assert msgs[1]["meta"].get("interrupted") is True


@pytest.mark.parametrize("log_acks", [False, True])
def test_acks_logged_only_with_flag(monkeypatch, log_acks):
    monkeypatch.setattr(config, "CHAT_LOG_ACKS", log_acks)
    monkeypatch.setattr(voice_turns, "_last", {})
    monkeypatch.setattr(tts, "_last_end", {})
    monkeypatch.setattr(acks, "_pending", {})
    monkeypatch.setattr(acks, "_armed_at", {})
    monkeypatch.setattr(acks, "_speak_locks", {})
    monkeypatch.setattr(config, "ACKS_ENABLED", True)
    monkeypatch.setattr(config, "ACK_PENDING_S", 5.0)
    monkeypatch.setattr(config, "ACK_WIT_PROB", 0.0)

    async def _get_pcm(text):
        return b"\x01\x00" * 480, "память"
    monkeypatch.setattr(tts_cache, "get_pcm", _get_pcm)
    ws = FakeWS()

    async def _turn():
        await chat_hooks.on_voice_request({"device_id": DEV, "text": "следующий трек"},
                                          AsyncMock())
        acks.arm("c1", ws=ws, device_id=DEV, action="music.next")
        acks.arm("c2", ws=ws, device_id=DEV, action="music.next")

    async def _go():
        t = voice_turns.start(DEV, ws, _turn)
        await t.task
        await acks.on_result("c1", True, "")
        await acks.on_result("c2", False, "плеер не отвечает")
        await asyncio.sleep(0.1)
    asyncio.run(_go())

    texts = [t for _, _, t in _log()]
    assert texts[0] == "следующий трек"
    assert "Не получилось: плеер не отвечает." in texts, "ошибка пишется всегда"
    has_ack = any(t in ("Включаю.", "Готово.") for t in texts)
    assert has_ack is log_acks


def test_is_ack():
    for t in ("Готово.", "Громкость 70.", "Steam запущен.", "Выполняю.", "Готово, Мастер."):
        assert chat_hooks.is_ack(t), t
    for t in ("Готово, включила «Мою волну» и сделала потише.", "Не получилось.", ""):
        assert not chat_hooks.is_ack(t), t


@pytest.mark.parametrize("text,cmd", [
    ("Не записывай", "off"), ("Сакура, не записывай!", "off"),
    ("перестань записывать", "off"), ("Запись.", "on"), ("включи запись", "on"),
    ("не записывай это в календарь", None), ("запись к врачу", None), ("", None),
])
def test_privacy_command_exact(text, cmd):
    assert chat_hooks.privacy_command(text) == cmd


def test_non_master_device_not_logged():
    async def _go():
        t = voice_turns.start("phone", FakeWS(), lambda: chat_hooks.on_voice_request(
            {"device_id": "phone", "text": "привет"}, AsyncMock()))
        await t.task
    asyncio.run(_go())
    assert chat_log.count() == 0


# ── Telegram ───────────────────────────────────────────────────────

@pytest.fixture
def tg(monkeypatch):
    monkeypatch.setattr(users, "is_master", lambda uid: uid == MASTER_ID)


def _msg(text=None, *, uid=MASTER_ID, chat="private", **media):
    return SimpleNamespace(
        text=text, caption=media.pop("caption", None),
        chat=SimpleNamespace(type=chat, id=uid), from_user=SimpleNamespace(id=uid),
        answer=AsyncMock(), **media)


def _through(message, *outgoing):
    """Входящее через outer-middleware; обработчик шлёт исходящие."""
    async def handler(event, data):
        for method in outgoing:
            await chat_hooks.on_tg_sent(method)
        return "handled"
    return asyncio.run(chat_hooks.tg_incoming_middleware(handler, message, {}))


def test_tg_text_and_reply(tg):
    r = _through(_msg("как дела?"), SendMessage(chat_id=MASTER_ID, text="Хорошо, Мастер."))
    assert r == "handled"
    msgs = chat_log.history()[0]
    assert [(m["role"], m["channel"], m["device"], m["text"]) for m in msgs] == [
        ("user", "telegram", "telegram", "как дела?"),
        ("assistant", "telegram", "telegram", "Хорошо, Мастер.")]
    assert msgs[1]["reply_to"] == msgs[0]["id"]


def test_tg_media_placeholders(tg):
    _through(_msg(photo=[object()], caption="закат"),
             SendPhoto(chat_id=MASTER_ID, photo="https://example.invalid/x.jpg",
                       caption="Красиво."))
    _through(_msg(voice=object()))
    _through(_msg(sticker=object()), SendSticker(chat_id=MASTER_ID, sticker="CAAC"))
    assert [t for _, _, t in _log()] == [
        "[фото] закат", "[фото] Красиво.", "[голосовое]", "[стикер]", "[стикер]"]


def test_tg_commands_guests_and_acks_not_logged(tg):
    _through(_msg("/status"), SendMessage(chat_id=MASTER_ID, text="laptop: онлайн"))
    _through(_msg("привет", uid=555), SendMessage(chat_id=555, text="Привет, гость."))
    _through(_msg("привет", chat="group"))
    _through(_msg("сделай громче"), SendMessage(chat_id=MASTER_ID, text="Готово."))
    assert _log() == [("user", "telegram", "сделай громче")]


def test_tg_proactive_and_voice_turn_outgoing(tg):
    async def _go():
        await chat_hooks.on_tg_sent(SendMessage(chat_id=MASTER_ID, text="Через 30 минут созвон."))
        # исходящее в Telegram изнутри голосового хода — ход пишет себя сам
        async def _turn():
            await chat_hooks.on_tg_sent(SendMessage(chat_id=MASTER_ID, text="Играет трек."))
        await voice_turns.start(DEV, FakeWS(), _turn).task
    asyncio.run(_go())
    assert _log() == [("assistant", "proactive", "Через 30 минут созвон.")]


def test_tg_privacy_command_not_passed_to_handler(tg):
    m = _msg("не записывай")
    assert _through(m) is None
    m.answer.assert_awaited_once_with(chat_hooks.PHRASE_PAUSED)
    _through(_msg("секрет"), SendMessage(chat_id=MASTER_ID, text="Поняла."))
    assert chat_log.count() == 0
    _through(_msg("запись"))
    _through(_msg("можно"))
    assert _log() == [("user", "telegram", "можно")]


def test_tg_session_middleware_logs_after_send(tg):
    mw = chat_hooks.tg_session_middleware()
    sent = []

    async def make_request(bot, method):
        sent.append(method)
        return "ok"

    async def _go():
        return await mw(make_request, None, SendMessage(chat_id=MASTER_ID, text="Доброе утро."))
    assert asyncio.run(_go()) == "ok" and sent
    assert _log() == [("assistant", "proactive", "Доброе утро.")]


def test_export_and_clear_chat_commands():
    chat_log.append("user", "telegram", "привет", device="telegram")
    chat_log.append("assistant", "telegram", "Привет, Мастер.", device="telegram")

    m = _msg("/export_chat")
    m.answer_document = AsyncMock()
    asyncio.run(cmd_export_chat_impl(m))
    doc = m.answer_document.await_args.args[0]
    body = doc.data.decode("utf-8")
    assert doc.filename.startswith("sakura_chat_") and doc.filename.endswith(".md")
    assert "привет" in body and "Привет, Мастер." in body

    m = _msg("/clear_chat")
    asyncio.run(cmd_clear_chat_impl(m))
    assert "/clear_chat да" in m.answer.await_args.args[0] and chat_log.count() == 2
    m = _msg("/clear_chat да")
    asyncio.run(cmd_clear_chat_impl(m))
    assert chat_log.count() == 0 and "удалено 2" in m.answer.await_args.args[0]

    m = _msg("/export_chat")
    asyncio.run(cmd_export_chat_impl(m))
    m.answer.assert_awaited_once_with("Журнал чата пуст.")


def test_journal_size_example():
    """Размер базы на тестовых данных: 1000 пар «вопрос — ответ»."""
    t0 = time.time() - 1000 * 60
    for i in range(1000):
        chat_log.append("user", "voice", f"Сакура, напомни про задачу номер {i}",
                        device=DEV, ts=t0 + i * 60, meta={"turn_id": f"{i:012x}"})
        chat_log.append("assistant", "voice",
                        f"Хорошо, напомню про задачу номер {i} через час. Что-нибудь ещё?",
                        device=DEV, ts=t0 + i * 60 + 2, reply_to=2 * i + 1,
                        meta={"turn_id": f"{i:012x}"})
    s = chat_log.stats()
    print(f"\n[chat_log] {s['messages']} сообщений → {s['bytes'] / 1024:.0f} КиБ "
          f"(база {s['db_bytes'] / 1024:.0f} КиБ + WAL)")
    assert s["messages"] == 2000 and s["bytes"] < 2 * 1024 * 1024
