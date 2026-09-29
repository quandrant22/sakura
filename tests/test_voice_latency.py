"""perf/voice-latency (п.2): классификатор роутера параллельно со стримом.

Проверяемые инварианты:
  * команда → стрим ответа отменён, TTS не вызван;
  * болтовня → TTS получает текст, суммарная задержка ≈
    max(классификатор, первое предложение), а НЕ сумма;
  * Router.route зовёт on_llm ровно перед LLM-классификатором
    (точные пути и «не забудь …» — без хука).

Run: python -m pytest tests/test_voice_latency.py -q
"""

import asyncio
import time
from unittest.mock import AsyncMock, MagicMock

import adapters.voice as voice_mod
import adapters.ws as wh
import sakura_core.bridge as br
import sakura_core.llm as llm
import sakura_core.reactions as reactions
from sakura_core.router import Decision, Router

T_CLASSIFY = 0.35   # «классификатор» в фейковом роутере
T_SENTENCE = 0.35   # первое предложение LLM готово (≈ first_token)


# ── фейки ──────────────────────────────────────────────────────────


class _FakeSession:
    pending = None


class _FakeRouter:
    """Роутер-двойник: хук on_llm вызывается как в настоящем Router."""

    def __init__(self, decision, delay: float = T_CLASSIFY):
        self.session = _FakeSession()
        self._decision = decision
        self._delay = delay

    async def route(self, text, context=None, *, on_llm=None):
        if on_llm is not None:
            on_llm()
        await asyncio.sleep(self._delay)
        return self._decision


async def _fake_stream_tokens(contents, **kwargs):
    """Токены: первое предложение готово на T_SENTENCE."""
    await asyncio.sleep(T_SENTENCE - 0.05)
    yield "Привет, мир. "
    await asyncio.sleep(0.05)
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


def _mk_ask_voice(outcome, tts_calls):
    """Двойник ask_gemini_voice, идущий через НАСТОЯЩИЙ stream_llm_to_tts
    (шлюз gate и буферизация — реальные, сеть — замокана)."""
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


def _setup(monkeypatch, tts_calls, *, decision, executed):
    """Патчи окружения ws + сети LLM/TTS. Возвращает ws_dev."""
    ws_dev = MagicMock()
    ws_dev.send = AsyncMock()

    # сеть → фейки
    monkeypatch.setattr(llm, "stream_tokens", _fake_stream_tokens)
    monkeypatch.setattr(llm, "pick_key", lambda api_key=None: "test-key")
    monkeypatch.setattr(llm, "get_client", lambda key: MagicMock())

    async def _fake_live(text, emotion, on_packet, label=""):
        tts_calls.append((time.monotonic(), text, label))
        await on_packet(b"AUDIO")
        return 1

    async def _fake_send(data):
        return None

    monkeypatch.setattr(voice_mod, "_live_synthesize", _fake_live)
    monkeypatch.setattr(voice_mod, "_make_audio_sender",
                        lambda websocket, device_id: _fake_send)

    # роутер: команда/болтовня
    monkeypatch.setattr(br, "get_router", lambda: _FakeRouter(decision))

    async def _exec(decision, **kw):
        return (executed, None)
    monkeypatch.setattr(br, "execute_decision", _exec)

    # состояние и лёгкие ветки ws
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
    return ws_dev


def _data(text):
    return {"device_id": "laptop", "text": text,
            "active_window": "", "context": []}


# ── тесты ──────────────────────────────────────────────────────────


def test_command_cancels_stream_and_never_calls_tts(monkeypatch):
    """Классификатор вернул действие → стрим отменён, TTS не вызван."""
    tts_calls, outcome = [], {}
    _setup(monkeypatch, tts_calls,
           decision=Decision("music.next", "llm"), executed=True)
    ctx = _mk_ctx(_mk_ask_voice(outcome, tts_calls))

    asyncio.run(wh.handle_voice_command(None, _data("смени трек"), ctx))

    assert outcome.get("cancelled") is True, "стрим ответа должен быть отменён"
    assert outcome.get("completed") is not True
    assert tts_calls == [], "TTS не должен вызываться при команде"


def test_chatter_tts_gets_text_with_parallel_latency(monkeypatch):
    """Болтовня → буфер отдан в TTS; задержка ≈ max(классификатор,
    первое предложение), а не сумма; токены не текли до вердикта."""
    tts_calls, outcome = [], {}
    _setup(monkeypatch, tts_calls,
           decision=Decision(None, "conversation"), executed=False)
    ctx = _mk_ctx(_mk_ask_voice(outcome, tts_calls))

    t0 = time.monotonic()
    asyncio.run(wh.handle_voice_command(
        None, _data("давно не виделись как проходит время"), ctx))

    assert outcome.get("completed") is True, "голосовой стрим доигран до конца"
    assert tts_calls, "TTS должен получить текст"
    first_dt = tts_calls[0][0] - t0

    # текст доставлен по предложениям (буфер + продолжение стрима)
    assert tts_calls[0][1] == "Привет, мир."
    assert any(c[1] == "Как дела?" for c in tts_calls)

    # не раньше вердикта классификатора
    assert first_dt >= T_CLASSIFY - 0.02, \
        f"токены ушли в TTS до вердикта ({first_dt:.3f}с)"
    # ≈ max, а не сумма
    serial = T_CLASSIFY + T_SENTENCE
    assert first_dt < serial - 0.10, \
        f"задержка {first_dt:.3f}с ≈ сумме {serial:.2f}с — пути не параллельны"
    assert first_dt >= T_SENTENCE - 0.05


def test_router_on_llm_only_before_classifier():
    """Хук on_llm срабатывает только на шаге LLM-классификатора."""
    calls = []

    async def _classify(text, catalog):
        calls.append("llm")
        return None

    r = Router(declarations=[], llm_classify=_classify)

    asyncio.run(r.route("как у тебя дела", None,
                        on_llm=lambda: calls.append("on_llm")))
    assert calls == ["on_llm", "llm"], "хук должен быть строго ДО классификатора"

    # fast-путь («не забудь …») возвращается до LLM → хука нет
    calls.clear()
    dec = asyncio.run(r.route("не забудь позвонить маме", None,
                              on_llm=lambda: calls.append("on_llm")))
    assert calls == []
    assert dec.source == "conversation"


def test_gate_timeout_behaves_as_not_command():
    """Таймаут шлюза (классификатор завис) → открываемся как «не команда»."""
    async def _go():
        g = voice_mod.VoiceGate()
        verdict = await g.wait_open(0.05)
        return verdict, g.opened

    verdict, opened = asyncio.run(_go())
    assert verdict is False and opened is True

