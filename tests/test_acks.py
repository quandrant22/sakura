"""fix/voice-acks: быстрые голосовые подтверждения команд агента (без LLM)."""

import asyncio
import random
import time
from unittest.mock import AsyncMock, MagicMock

import pytest

import adapters.ws as wh
import config
import modules.acks as acks
import modules.state as st
import modules.tts_cache as tts_cache
import modules.tts_server as tts
import sakura_core.bridge as br
import sakura_core.ws_protocol as wp
from sakura_core.router import Decision
from tests.test_turn_end import FakeWS, _data, _mk_ask_voice, _mk_ctx, _setup

PCM = b"\x01\x00" * 24000            # 1с «звука»


@pytest.fixture(autouse=True)
def _fresh(monkeypatch, tmp_path):
    monkeypatch.setattr(acks, "_pending", {})
    monkeypatch.setattr(acks, "_armed_at", {})
    monkeypatch.setattr(acks, "_last", {})
    monkeypatch.setattr(acks, "_speak_locks", {})
    monkeypatch.setattr(tts_cache, "_mem", tts_cache.OrderedDict())
    monkeypatch.setattr(tts_cache, "_locks", {})
    monkeypatch.setattr(tts_cache, "WARMUP_PAUSE_S", 0.0)
    monkeypatch.setattr(config, "TTS_CACHE_DIR", str(tmp_path / "tts_cache"))
    monkeypatch.setattr(config, "ACKS_ENABLED", True)
    monkeypatch.setattr(config, "ACK_WIT_PROB", 0.0)
    monkeypatch.setattr(config, "ACK_PENDING_S", 5.0)
    monkeypatch.setattr(tts, "_last_end", {})


@pytest.fixture
def synth_calls(monkeypatch):
    calls = []

    async def _fake_live(text, emotion, on_packet, label="", strict=False):
        calls.append(text)
        await on_packet(PCM)
        return 1
    monkeypatch.setattr(tts, "_live_synthesize", _fake_live)
    return calls


# ── фразы ───────────────────────────────────────────────────────────


def test_categories():
    assert acks.choose("system.volume", "pc", "70") in {"Громкость 70.", "Сделала."}
    assert acks.choose("music.volume_up", "pc") == "Сделала."      # без числа
    assert acks.choose("app.switch_open", "pc", "Steam") in {"Открываю.", "Steam запущен."}
    assert acks.choose("music.next", "pc") in {"Включаю.", "Готово."}
    assert acks.choose("browser.back", "pc") in acks.PHRASES["default"]


@pytest.mark.parametrize("param,category", [
    (None, "music"), ("", "music"), ("яндекс музыка", "music"), ("Музыку", "music"),
    ("steam", "open_app"), ("Telegram", "open_app"),
])
def test_open_app_category_by_param(param, category):
    assert acks.category_for("open.app", param) == category


def test_open_app_phrases():
    assert acks.choose("open.app", "pc", None) in {"Включаю.", "Готово."}
    assert acks.choose("open.app", "pc", "Steam") in {"Открываю.", "Steam запущен."}


def test_wit_probability(monkeypatch):
    monkeypatch.setattr(config, "ACK_WIT_PROB", 1.0)
    assert acks.choose("browser.back", "pc") in acks.WIT


def test_no_repeat_in_a_row_per_device():
    rng = random.Random(1)
    prev = {}
    for i in range(300):
        dev = ("pc", "phone")[i % 2]
        phrase = acks.choose("browser.back", dev, rng=rng)
        assert phrase != prev.get(dev)
        prev[dev] = phrase


def test_error_phrases():
    assert acks.error_phrase("Устройство оффлайн") == "Устройство недоступно."
    assert acks.error_phrase("") == "Не получилось."
    assert acks.error_phrase("файл не найден.") == "Не получилось: файл не найден."
    assert acks.error_phrase("app_not_found:steam") == "Не получилось: не нашла steam."
    assert acks.detail_is_error("app_not_found:steam")
    assert not acks.detail_is_error("выполнено")


def test_fixed_phrases_have_no_placeholders():
    fixed = acks.fixed_phrases()
    assert "Готово." in fixed and "Выполняю." in fixed
    assert not [p for p in fixed if "{" in p]
    assert len(fixed) == len(set(fixed))


# ── кэш ─────────────────────────────────────────────────────────────


def test_cache_second_call_without_synthesis(synth_calls, monkeypatch):
    async def _go():
        a = await tts_cache.get_pcm("Готово.")
        b = await tts_cache.get_pcm("Готово.")
        tts_cache._mem.clear()                     # перезапуск: только диск
        c = await tts_cache.get_pcm("Готово.")
        return a, b, c
    a, b, c = asyncio.run(_go())
    assert synth_calls == ["Готово."]
    assert (a[1], b[1], c[1]) == ("синтез", "память", "диск")
    assert a[0] == b[0] == c[0] == PCM


def test_cache_key_changes_with_model_or_voice(synth_calls, monkeypatch):
    asyncio.run(tts_cache.get_pcm("Есть."))
    monkeypatch.setattr(tts, "TTS_MODEL", "gemini-3.8-live")
    asyncio.run(tts_cache.get_pcm("Есть."))
    monkeypatch.setattr(tts, "TTS_VOICE", "Kore")
    asyncio.run(tts_cache.get_pcm("Есть."))
    assert synth_calls == ["Есть.", "Есть.", "Есть."]


def test_failed_synthesis_not_cached(monkeypatch):
    async def _boom(text, emotion, on_packet, label="", strict=False):
        await on_packet(b"\x00\x00" * 10)        # обрывок
        raise RuntimeError("1011")
    monkeypatch.setattr(tts, "_live_synthesize", _boom)
    pcm, _ = asyncio.run(tts_cache.get_pcm("Принято."))
    assert pcm is None
    assert not tts_cache._mem


def test_play_sends_chunks_then_tts_end(synth_calls):
    ws = FakeWS()
    asyncio.run(tts_cache.play("Готово.", ws, "pc"))
    kinds = [m["type"] for m in ws.sent]
    assert kinds[-1] == "tts_end" and kinds.count("tts_end") == 1
    assert kinds.count("tts_chunk") == len(PCM) // tts_cache.CHUNK_BYTES


# ── голосовой ход + command_result ─────────────────────────────────


def _voice_command(monkeypatch, ws, action, cmd_id="cmd1"):
    _setup(monkeypatch, ws, decision=Decision(action, "llm"))

    async def _exec(decision, **kw):
        return (True, cmd_id)
    monkeypatch.setattr(br, "execute_decision", _exec)
    monkeypatch.setattr(st, "_pending_commands",
                        {cmd_id: {"action": action, "device": "laptop",
                                  "ts": time.monotonic(), "status": "sent"}})


def _result_ctx():
    return {"ask_gemini": AsyncMock(), "bot": MagicMock(),
            "_resolve_command_status": lambda *a: "executed"}


async def _wait_for(pred, timeout=2.0):
    t0 = time.monotonic()
    while not pred():
        if time.monotonic() - t0 > timeout:
            return False
        await asyncio.sleep(0.005)
    return True


def test_ack_only_after_command_result_and_fast_on_cache(monkeypatch, synth_calls):
    """Ход с командой агенту молчит и не закрыт; после command_result —
    фраза из кэша и один tts_end. Первый пакет < 300мс от command_result."""
    ws = FakeWS()
    _voice_command(monkeypatch, ws, "music.next")

    async def _go():
        await tts_cache.warmup(acks.fixed_phrases())
        synth_calls.clear()
        await wh.handle_voice_command(None, _data("следующий трек"),
                                      _mk_ctx(_mk_ask_voice({})))
        before = list(ws.sent)
        t_result = time.monotonic()
        await wp.handle_command_result(
            None, {"type": "command_result", "id": "cmd1", "ok": True,
                   "device_id": "laptop"}, _result_ctx())
        assert await _wait_for(lambda: any(m["type"] == "tts_chunk" for m in ws.sent))
        first_chunk_ms = (time.monotonic() - t_result) * 1000
        assert await _wait_for(lambda: ws.tts_ends())
        return before, first_chunk_ms

    before, first_ms = asyncio.run(_go())
    assert before == [], before                      # до результата — тишина
    assert synth_calls == []                         # звук из кэша
    assert len(ws.tts_ends()) == 1 and ws.sent[-1]["type"] == "tts_end"
    print(f"\n[замер] command_result → первый аудиопакет (кэш): {first_ms:.1f} мс")
    assert first_ms < 300


def test_no_ack_for_followup_llm(monkeypatch, synth_calls):
    ws = FakeWS()
    _voice_command(monkeypatch, ws, "music.now_playing", cmd_id="cmd2")
    asyncio.run(wh.handle_voice_command(None, _data("что играет"),
                                        _mk_ctx(_mk_ask_voice({}))))
    assert acks._pending == {}
    assert asyncio.run(acks.on_result("cmd2", True, "")) is False
    assert ws.tts_ends() == [{"type": "tts_end", "device_id": "laptop"}]
    assert synth_calls == []


def test_ack_on_error_with_reason(monkeypatch):
    spoken = []

    async def _play(text, websocket, device_id, t_ref=None):
        spoken.append(text)
        return "память"
    monkeypatch.setattr(tts_cache, "play", _play)

    async def _go():
        acks.arm("cmd3", ws=FakeWS(), device_id="pc", action="app.switch_open", param="Steam")
        return await acks.on_result("cmd3", False, "приложение не найдено")
    assert asyncio.run(_go()) is True
    assert spoken == ["Не получилось: приложение не найдено."]


def test_pending_phrase_once_then_success_silent_error_spoken(monkeypatch):
    monkeypatch.setattr(config, "ACK_PENDING_S", 0.05)
    spoken = []

    async def _play(text, websocket, device_id, t_ref=None):
        spoken.append(text)
        return "память"
    monkeypatch.setattr(tts_cache, "play", _play)

    async def _go():
        ws = FakeWS()
        acks.arm("a", ws=ws, device_id="pc", action="browser.back")
        acks.arm("b", ws=ws, device_id="pc", action="browser.back")
        await asyncio.sleep(0.2)
        await acks.on_result("a", True, "")
        await acks.on_result("b", False, "Устройство оффлайн")
    asyncio.run(_go())
    assert spoken == ["Выполняю.", "Выполняю.", "Устройство недоступно."]


def test_acks_disabled(monkeypatch, synth_calls):
    monkeypatch.setattr(config, "ACKS_ENABLED", False)
    ws = FakeWS()
    _voice_command(monkeypatch, ws, "music.next")
    asyncio.run(wh.handle_voice_command(None, _data("следующий трек"),
                                        _mk_ctx(_mk_ask_voice({}))))
    assert acks._pending == {}
    assert ws.tts_ends() == [{"type": "tts_end", "device_id": "laptop"}]


def test_telegram_ack_unchanged(monkeypatch):
    """Telegram: «Готово.» через ack, как раньше; голосовой хук не нужен."""
    monkeypatch.setattr(br, "get_router", lambda: MagicMock(
        route=AsyncMock(return_value=Decision("music.next", "llm"))))

    async def _exec(decision, **kw):
        return (True, "cmd9")
    monkeypatch.setattr(br, "execute_decision", _exec)
    ack = AsyncMock()
    assert asyncio.run(br.v3_fast_path(
        "следующий", data={}, device_ws=None, device_id="pc",
        register_command=None, ack=ack)) is True
    ack.assert_awaited_once_with("Готово.")
    assert acks._pending == {}


def test_ok_true_with_error_detail_spoken_as_error(monkeypatch):
    """Агент прислал ok=True, но detail — ошибка: подтверждение говорит ошибку."""
    spoken = []

    async def _play(text, websocket, device_id, t_ref=None):
        spoken.append(text)
        return "память"
    monkeypatch.setattr(tts_cache, "play", _play)
    monkeypatch.setattr(st, "_pending_commands",
                        {"c5": {"action": "app.switch_open", "device": "pc",
                                "ts": time.monotonic(), "status": "sent"}})

    async def _go():
        acks.arm("c5", ws=FakeWS(), device_id="pc", action="app.switch_open", param="Steam")
        await wp.handle_command_result(
            None, {"type": "command_result", "id": "c5", "ok": True,
                   "detail": "app_not_found:steam", "device_id": "pc"}, _result_ctx())
        await _wait_for(lambda: spoken)
    asyncio.run(_go())
    assert spoken == ["Не получилось: не нашла steam."]
