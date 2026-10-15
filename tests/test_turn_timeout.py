"""fix/turn-timeout: сторож зависшего голосового хода.

Ход не завершился за TURN_TIMEOUT_S — reply(kind=error) «Не получилось
ответить, повтори.» и tts_end; пока звук идёт — не зависание (до
TURN_TIMEOUT_MAX_S). Времена в тестах сжаты.

Run: python -m pytest tests/test_turn_timeout.py -q
"""

import asyncio

import pytest

import config
import modules.tts_server as tts
import modules.ws_auth as ws_auth
from sakura_core import voice_turns
from tests.test_turn_end import FakeWS

DEV = "laptop"


@pytest.fixture(autouse=True)
def fast(monkeypatch):
    monkeypatch.setattr(voice_turns, "_last", {})
    monkeypatch.setattr(tts, "_last_end", {})
    monkeypatch.setattr(voice_turns, "WATCH_POLL_S", 0.02)
    monkeypatch.setattr(config, "TURN_TIMEOUT_S", 0.3)
    monkeypatch.setattr(config, "TURN_ACTIVE_GRACE_S", 0.15)
    monkeypatch.setattr(config, "TURN_TIMEOUT_MAX_S", 1.0)
    monkeypatch.setattr(ws_auth, "is_master_device", lambda d: d == DEV)


def _run(factory):
    ws = FakeWS()

    async def _go():
        t = voice_turns.start(DEV, ws, lambda: factory(ws))
        await asyncio.wait_for(t.task, 5)
        return t
    return ws, asyncio.run(_go())


def test_hung_turn_gets_error_reply_then_tts_end():
    state = {}

    async def hung(ws):
        try:
            await asyncio.sleep(10)
        except asyncio.CancelledError:
            state["cancelled"] = True
            raise
    ws, t = _run(hung)
    assert state.get("cancelled"), "зависший обработчик снят"
    kinds = [m["type"] for m in ws.sent]
    assert kinds == ["reply", "tts_end"], ws.sent
    r = ws.sent[0]
    assert (r["kind"], r["text"], r["turn_id"]) == ("error", voice_turns.TIMEOUT_REPLY, t.turn_id)
    assert ws.sent[1]["turn_id"] == t.turn_id
    assert "timeout" in t.flags


def test_handler_finally_tts_end_not_duplicated():
    """Обработчик сам закрывает ход в finally (как handle_voice_command) — один tts_end."""
    async def hung(ws):
        try:
            await asyncio.sleep(10)
        finally:
            await tts.ensure_turn_end(ws, DEV, 0.0)
    ws, _ = _run(hung)
    assert [m["type"] for m in ws.sent] == ["reply", "tts_end"]


def test_long_streaming_answer_is_not_hung():
    """Звук идёт дольше TURN_TIMEOUT_S, пакеты частые — ход не трогаем."""
    async def long_answer(ws):
        send = tts._make_audio_sender(ws, DEV)
        for _ in range(30):              # ~0.6 с при TIMEOUT 0.3
            await send(b"PCM")
            await asyncio.sleep(0.02)
        await tts.ensure_turn_end(ws, DEV, 0.0)
    ws, t = _run(long_answer)
    assert [m["type"] for m in ws.sent].count("tts_chunk") == 30
    assert not [m for m in ws.sent if m["type"] == "reply"]
    assert "timeout" not in t.flags


def test_streaming_forever_capped_by_max():
    async def endless(ws):
        send = tts._make_audio_sender(ws, DEV)
        while True:
            await send(b"PCM")
            await asyncio.sleep(0.02)
    ws, t = _run(endless)
    assert "timeout" in t.flags
    tail = [m["type"] for m in ws.sent if m["type"] != "tts_chunk"]
    assert tail == ["reply", "tts_end"]
    last = max(i for i, m in enumerate(ws.sent) if m["type"] == "tts_chunk")
    assert last < [m["type"] for m in ws.sent].index("tts_end"), "после tts_end звука нет"


def test_fast_turn_untouched():
    async def quick(ws):
        await tts.ensure_turn_end(ws, DEV, 0.0)
    ws, t = _run(quick)
    assert [m["type"] for m in ws.sent] == ["tts_end"] and "timeout" not in t.flags


def test_watchdog_off(monkeypatch):
    monkeypatch.setattr(config, "TURN_TIMEOUT_S", 0)

    async def short_hang(ws):
        await asyncio.sleep(0.5)
    ws, t = _run(short_hang)
    assert ws.sent == [] and "timeout" not in t.flags


def test_handler_exception_still_logged_not_timeout():
    async def boom(ws):
        raise RuntimeError("сбой")
    ws, t = _run(boom)
    assert ws.sent == [] and "timeout" not in t.flags and t.done


def test_default_is_30_seconds():
    from pathlib import Path
    src = (Path(config.__file__)).read_text(encoding="utf-8")
    assert 'TURN_TIMEOUT_S = float(os.getenv("TURN_TIMEOUT_S", "30"))' in src
