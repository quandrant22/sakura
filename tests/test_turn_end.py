"""fix/turn-end: каждый голосовой ход закрывается ровно одним tts_end.

Клиент возвращает оверлей в idle только по tts_end. Потоковый ответ
(adapters/voice.py stream_llm_to_tts) и команды без озвучки его не шлют —
handle_voice_command добирает его в finally через ensure_turn_end.
"""

import asyncio
import json
import time
from unittest.mock import AsyncMock, MagicMock

import pytest

import adapters.voice as voice_mod
import adapters.ws as wh
import modules.tts_server as tts
import sakura_core.bridge as br
import sakura_core.llm as llm
import sakura_core.reactions as reactions
from sakura_core.router import Decision


# ── фейки ──────────────────────────────────────────────────────────


class FakeWS:
    """Websocket-двойник: копит отправленные JSON-сообщения."""

    def __init__(self, closed: bool = False):
        self.closed = closed
        self.sent: list[dict] = []

    async def send(self, raw):
        if self.closed:
            raise ConnectionError("websocket закрыт")
        self.sent.append(json.loads(raw))

    def tts_ends(self) -> list[dict]:
        return [m for m in self.sent if m.get("type") == "tts_end"]


class _FakeSession:
    pending = None


class _FakeRouter:
    def __init__(self, decision):
        self.session = _FakeSession()
        self._decision = decision

    async def route(self, text, context=None, *, source=None, on_llm=None):
        if on_llm is not None:
            on_llm()
        await asyncio.sleep(0.05)
        return self._decision


async def _fake_stream_tokens(contents, **kwargs):
    await asyncio.sleep(0.02)
    yield "Привет, мир. "
    await asyncio.sleep(0.02)
    yield "Как дела?"


def _mk_ctx(ask_voice):
    return {
        "ask_gemini": AsyncMock(return_value="Ок"),
        "ask_gemini_voice": ask_voice,
        "send_safe": AsyncMock(),
        "_find_vip_by_name": lambda *a, **k: None,
        "_translate_en": AsyncMock(),
        "_clean_slate": AsyncMock(),
        "_execute_plan": AsyncMock(return_value=(False, "")),
        "_register_command": lambda action, device: "cmd1",
        "_get_active_ws": lambda: (None, None),
        "bot": MagicMock(),
    }


def _mk_ask_voice(outcome):
    """ask_gemini_voice через НАСТОЯЩИЙ потоковый stream_llm_to_tts
    (он сам tts_end не шлёт)."""
    async def ask_voice(**kw):
        try:
            await voice_mod.stream_llm_to_tts(
                contents="тест", system="",
                websocket=kw.get("websocket"),
                device_id=kw.get("device_id") or "laptop",
                max_tokens=60, timeout=6.0,
                gate=kw.get("gate"),
            )
            outcome["completed"] = True
        except asyncio.CancelledError:
            outcome["cancelled"] = True
            raise
    return ask_voice


def _setup(monkeypatch, ws_dev, *, decision, executed=False):
    monkeypatch.setattr(tts, "_last_end", {})

    monkeypatch.setattr(llm, "stream_tokens", _fake_stream_tokens)
    monkeypatch.setattr(llm, "pick_key", lambda api_key=None: "test-key")
    monkeypatch.setattr(llm, "get_client", lambda key: MagicMock())

    async def _fake_live(text, emotion, on_packet, label=""):
        await on_packet(b"AUDIO")
        return 1

    async def _fake_audio(data):
        return None

    monkeypatch.setattr(voice_mod, "_live_synthesize", _fake_live)
    monkeypatch.setattr(voice_mod, "_make_audio_sender",
                        lambda websocket, device_id: _fake_audio)

    # буквальная озвучка: синтез замокан, _send_end — настоящий
    async def _fake_synth(text, websocket, device_id, emotion="спокойная"):
        return 1
    monkeypatch.setattr(tts, "_synthesize_and_stream", _fake_synth)
    monkeypatch.setattr(wh, "tts_preconnect", AsyncMock(return_value=False))
    monkeypatch.setattr(wh, "tts_release_preconnect", AsyncMock())

    monkeypatch.setattr(br, "get_router", lambda: _FakeRouter(decision))

    async def _exec(decision, **kw):
        return (executed, None)
    monkeypatch.setattr(br, "execute_decision", _exec)

    monkeypatch.setattr(wh.st, "connected_devices", {"laptop": ws_dev})
    monkeypatch.setattr(wh.st, "_pending_system", {})
    monkeypatch.setattr(wh.st, "_pending_plan", {})
    monkeypatch.setattr(wh.st, "_pending_clarify", {})
    monkeypatch.setattr(wh, "_im_mark", lambda t: None)
    monkeypatch.setattr(wh, "pending_forget_active", lambda: False)
    monkeypatch.setattr(wh, "should_prank", lambda t: False)
    monkeypatch.setattr(wh, "match_voice_trigger", lambda t: None)
    monkeypatch.setattr(wh, "parse_teaching", lambda t: None)
    monkeypatch.setattr(wh, "_has_tg_trigger", lambda t: False)
    monkeypatch.setattr(reactions, "get_mood_reaction", lambda t: None)
    import modules.game_hub as gh
    monkeypatch.setattr(gh, "get_game_context_for_device", lambda *a: None)


def _data(text):
    return {"device_id": "laptop", "text": text,
            "active_window": "", "context": []}


def _patch_fast_path_speak(monkeypatch, phrase, listen):
    """v3_fast_path отвечает буквальной репликой через speak (как реестр)."""
    async def _fast(text, *, speak, **kw):
        await speak(phrase, listen=listen)
        return True
    monkeypatch.setattr(br, "v3_fast_path", _fast)


# ── тесты ──────────────────────────────────────────────────────────


def test_stream_answer_gets_single_tts_end(monkeypatch):
    """Потоковый ответ без stream_tts_to_device → ровно один tts_end."""
    ws, outcome = FakeWS(), {}
    _setup(monkeypatch, ws, decision=Decision(None, "conversation"))

    asyncio.run(wh.handle_voice_command(
        None, _data("давно не виделись как проходит время"),
        _mk_ctx(_mk_ask_voice(outcome))))

    assert outcome.get("completed") is True
    ends = ws.tts_ends()
    assert len(ends) == 1, ws.sent
    assert ends[0] == {"type": "tts_end", "device_id": "laptop"}
    assert ws.sent[-1]["type"] == "tts_end", "tts_end — последним"


@pytest.mark.parametrize("listen", [None, 4.0])
def test_literal_reply_tts_end_not_duplicated(monkeypatch, listen):
    """Буквальная реплика сама шлёт tts_end (с listen или без) → второго нет."""
    ws = FakeWS()
    _setup(monkeypatch, ws, decision=Decision(None, "conversation"))
    _patch_fast_path_speak(monkeypatch, "Готово, Мастер.", listen)

    asyncio.run(wh.handle_voice_command(
        None, _data("включи свет"), _mk_ctx(AsyncMock())))

    ends = ws.tts_ends()
    assert len(ends) == 1, ws.sent
    if listen is None:
        assert "listen" not in ends[0]
    else:
        assert ends[0]["listen"] == listen


def test_command_with_cancelled_prefetch_gets_single_tts_end(monkeypatch):
    """Команда, prefetch голоса отменён, озвучки нет → ровно один tts_end."""
    ws, outcome = FakeWS(), {}
    _setup(monkeypatch, ws, decision=Decision("music.next", "llm"),
           executed=True)

    asyncio.run(wh.handle_voice_command(
        None, _data("смени трек"), _mk_ctx(_mk_ask_voice(outcome))))

    assert outcome.get("cancelled") is True
    assert outcome.get("completed") is not True
    ends = ws.tts_ends()
    assert len(ends) == 1, ws.sent
    assert "listen" not in ends[0]


def test_exception_in_handler_still_sends_tts_end(monkeypatch):
    """Исключение в обработчике → tts_end всё равно ушёл."""
    ws = FakeWS()
    _setup(monkeypatch, ws, decision=Decision(None, "conversation"))

    def _boom(text):
        raise RuntimeError("сбой ветки")
    monkeypatch.setattr(wh, "match_voice_trigger", _boom)

    with pytest.raises(RuntimeError):
        asyncio.run(wh.handle_voice_command(
            None, _data("что-нибудь"), _mk_ctx(_mk_ask_voice({}))))

    assert len(ws.tts_ends()) == 1, ws.sent


def test_closed_websocket_no_exception(monkeypatch):
    """Закрытый websocket: ход завершается без исключения."""
    ws = FakeWS(closed=True)
    _setup(monkeypatch, ws, decision=Decision("music.next", "llm"),
           executed=True)

    asyncio.run(wh.handle_voice_command(
        None, _data("смени трек"), _mk_ctx(_mk_ask_voice({}))))

    # и напрямую: ошибка отправки проглочена, время не записано
    asyncio.run(tts.ensure_turn_end(ws, "laptop", time.monotonic()))
    assert ws.sent == []
    assert "laptop" not in tts._last_end


def test_ensure_turn_end_respects_since(monkeypatch):
    """tts_end раньше since (прошлый ход) не засчитывается."""
    monkeypatch.setattr(tts, "_last_end", {})
    ws = FakeWS()

    async def _go():
        await tts._send_end(ws, "laptop")          # прошлый ход
        since = time.monotonic()
        await tts.ensure_turn_end(ws, "laptop", since)   # добавлен
        await tts.ensure_turn_end(ws, "laptop", since)   # уже есть
    asyncio.run(_go())

    assert len(ws.tts_ends()) == 2


# ── ранние return до основного try (обёртка handle_voice_command) ──


def test_v3_confirm_yes_without_speech_gets_single_tts_end(monkeypatch):
    """«да» на v3-подтверждение: команда агенту без озвучки → один tts_end."""
    ws = FakeWS()
    _setup(monkeypatch, ws, decision=Decision(None, "conversation"))

    router = _FakeRouter(Decision(None, "conversation"))
    router.session.pending = object()
    monkeypatch.setattr(br, "get_router", lambda: router)

    import sakura_core.executor as ex

    async def _exec_crit(action, ws_dev, device_id, *a, **k):
        await ws_dev.send(json.dumps({"type": "command", "action": action}))
    monkeypatch.setattr(ex, "execute_critical_action", _exec_crit)

    async def _confirm(text, *, source, on_execute, on_cancel):
        await on_execute("system.shutdown")
        return True
    monkeypatch.setattr(br, "handle_v3_confirm", _confirm)

    voice = AsyncMock()
    asyncio.run(wh.handle_voice_command(None, _data("да"), _mk_ctx(voice)))

    voice.assert_not_awaited()
    assert ws.sent == [
        {"type": "command", "action": "system:shutdown"},
        {"type": "tts_end", "device_id": "laptop"},
    ]


def test_tts_stop_sends_own_tts_end_only(monkeypatch):
    """Стоп озвучки: «Хорошо, остановилась.» шлёт свой tts_end → без дубля."""
    ws = FakeWS()
    _setup(monkeypatch, ws, decision=Decision(None, "conversation"))
    import modules.state as state
    stopped = []
    monkeypatch.setattr(state, "tts_is_reading", lambda key: True)
    monkeypatch.setattr(state, "tts_request_stop", stopped.append)

    asyncio.run(wh.handle_voice_command(None, _data("стоп"), _mk_ctx(AsyncMock())))

    assert stopped == ["laptop"]
    assert ws.tts_ends() == [{"type": "tts_end", "device_id": "laptop"}]


def test_pending_confirm_gets_single_tts_end(monkeypatch):
    """«да» на _pending_system: команда агенту, озвучки нет → один tts_end."""
    ws = FakeWS()
    _setup(monkeypatch, ws, decision=Decision(None, "conversation"))
    monkeypatch.setattr(wh.st, "_pending_commands", {})
    monkeypatch.setattr(wh.st, "_last_executed", {})
    monkeypatch.setattr(wh.st, "_pending_system", {
        "laptop": {"action": "system:shutdown", "device": "laptop",
                   "ts": time.monotonic()},
    })

    voice = AsyncMock()
    asyncio.run(wh.handle_voice_command(None, _data("да"), _mk_ctx(voice)))

    voice.assert_not_awaited()
    assert "laptop" not in wh.st._pending_system
    commands = [m for m in ws.sent if m.get("type") == "command"]
    assert [c["action"] for c in commands] == ["system:shutdown"]
    assert ws.tts_ends() == [{"type": "tts_end", "device_id": "laptop"}]
    assert ws.sent[-1]["type"] == "tts_end"


# ── chore/turn-end-trace: решения по tts_end видны в журнале ──────


def test_send_end_logs_device_and_listen(monkeypatch, caplog):
    """_send_end пишет INFO «tts_end → device=… listen=…»."""
    monkeypatch.setattr(tts, "_last_end", {})
    ws = FakeWS()
    with caplog.at_level("INFO", logger=tts.log.name):
        asyncio.run(tts._send_end(ws, "pc", listen=6.0))
        asyncio.run(tts._send_end(ws, "pc"))
    msgs = [r.getMessage() for r in caplog.records]
    assert "[tts] tts_end → device=pc listen=6.0" in msgs
    assert "[tts] tts_end → device=pc listen=None" in msgs


def test_send_end_closed_socket_no_info(monkeypatch, caplog):
    """Отправка не удалась — INFO «tts_end →» не пишется."""
    monkeypatch.setattr(tts, "_last_end", {})
    with caplog.at_level("INFO", logger=tts.log.name):
        asyncio.run(tts._send_end(FakeWS(closed=True), "pc"))
    assert not [r for r in caplog.records if "tts_end →" in r.getMessage()]


def test_ensure_turn_end_logs_decision(monkeypatch, caplog):
    """ensure_turn_end пишет решение: since, last_end и отправлен/пропущен."""
    monkeypatch.setattr(tts, "_last_end", {})
    ws = FakeWS()

    async def _go():
        since = time.monotonic()
        await tts.ensure_turn_end(ws, "pc", since)   # ход не закрыт
        await tts.ensure_turn_end(ws, "pc", since)   # уже закрыт
        return since

    with caplog.at_level("INFO", logger=tts.log.name):
        since = asyncio.run(_go())
    msgs = [r.getMessage() for r in caplog.records
            if "ensure_turn_end" in r.getMessage()]
    assert len(msgs) == 2
    assert msgs[0] == (f"[tts] ensure_turn_end device=pc since={since:.3f} "
                       f"last_end=0.000 -> отправлен")
    assert msgs[1].startswith(f"[tts] ensure_turn_end device=pc since={since:.3f} "
                              f"last_end=")
    assert msgs[1].endswith(" -> пропущен")
    assert len(ws.tts_ends()) == 1
