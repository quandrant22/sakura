"""perf/voice-latency (п.3): предконнект Live-сессии TTS.

Инварианты:
  * сессия открывается ЗАРАНЕЕ — пока роутер классифицирует запрос и
    идёт первый токен LLM (handshake ∥ классификатор, а не после);
  * первая стадия синтеза забирает готовую сессию и НЕ делает новый коннект;
  * команда/отмена/ttl закрывают предконнект и возвращают слот семафора;
  * без предконнекта путь прежний (фолбэк в обычный синтез);
  * handle_voice_command стартует предконнект до вердикта классификатора.

Сеть не трогаем: клиент Live API подменён фейком.

Run: python -m pytest tests/test_tts_preconnect.py -q
"""

import asyncio
import json
import time
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

import adapters.voice as voice_mod
import adapters.ws as wh
import modules.tts_server as tts
import sakura_core.bridge as br
import sakura_core.llm as llm
import sakura_core.reactions as reactions
from sakura_core.router import Decision

T_CONNECT = 0.10   # «handshake» Live API в фейковом клиенте


# ── двойники Live API ──────────────────────────────────────────────


class _Resp:
    """Ответ сессии: либо аудио-пакет, либо конец хода."""

    def __init__(self, data, complete=False):
        self.data = data
        self.server_content = SimpleNamespace(turn_complete=complete)


class _FakeSession:
    def __init__(self, packets):
        self._packets = packets
        self.sent = []

    async def send_client_content(self, *, turns, turn_complete):
        self.sent.append((turns, turn_complete))

    async def receive(self):
        for p in self._packets:
            yield _Resp(p)
        yield _Resp(None, complete=True)


class _FakeConnector:
    """Двойник async-CM client.aio.live.connect(): считает коннекты."""

    def __init__(self, live):
        self._live = live
        self._session = None

    async def __aenter__(self):
        self._live.connect_calls += 1
        self._live.connect_started.append(time.monotonic())
        await asyncio.sleep(T_CONNECT)          # «handshake» с Live API
        self._session = _FakeSession(self._live.packets)
        self._live.sessions.append(self._session)
        return self._session

    async def __aexit__(self, *exc):
        self._live.closed += 1
        return False


class _FakeLive:
    def __init__(self, packets=(b"A", b"B")):
        self.packets = list(packets)
        self.connect_calls = 0
        self.connect_started = []
        self.sessions = []
        self.closed = 0

    def connect(self, *, model, config):
        return _FakeConnector(self)


class _FakeClient:
    def __init__(self, live):
        self.aio = SimpleNamespace(live=live)


@pytest.fixture
def live(monkeypatch):
    """Живой фейк Live API: ни одного реального сокета."""
    lv = _FakeLive()
    monkeypatch.setattr(tts, "_get_client",
                        AsyncMock(return_value=_FakeClient(lv)))
    monkeypatch.setattr(tts, "get_active_key", lambda: "test-key")
    monkeypatch.setattr(tts, "mark_key_used", lambda key: None)
    return lv


def _packets(sink):
    """on_packet, складывающий пакеты в sink (список)."""
    async def _on_packet(data):
        sink.append(data)
    return _on_packet


async def _slots_free() -> int:
    """Сколько мест семафора TTS реально свободно (0..2)."""
    got = 0
    for _ in range(2):
        try:
            await asyncio.wait_for(tts._sem.acquire(), 0.2)
            got += 1
        except asyncio.TimeoutError:
            break
    for _ in range(got):
        tts._sem.release()
    return got


# ── предбанник: коннект параллельно первому токену ──────────────────


def test_preconnect_opens_session_while_tokens_still_pending(live):
    """«Первый токен» ждёт классификатор — а коннект уже прошёл в фоне."""
    async def _go():
        t0 = time.monotonic()
        assert await tts.preconnect() is True
        # Токен/классификатор ещё не готовы, но handshake уже идёт в фоне.
        await asyncio.sleep(0.01)                 # задача-держатель стартовала
        assert tts.preconnect_status() == "connecting"
        assert live.connect_calls == 1, "коннект должен стартовать сразу"
        await asyncio.sleep(T_CONNECT + 0.05)     # «первый токен пришёл»
        return tts.preconnect_status(), time.monotonic() - t0, t0

    status, dt, t0 = asyncio.run(_go())
    assert status == "ready", "к первому токену сессия обязана быть готовой"
    assert dt >= T_CONNECT
    assert live.connect_started[0] >= t0, "коннект ушёл в фон, а не в конец пути"


def test_preconnect_is_idempotent(live):
    """Повторный вызов не открывает вторую сессию."""
    async def _go():
        await tts.preconnect()
        await tts.preconnect()
        await asyncio.sleep(T_CONNECT + 0.05)
        return live.connect_calls

    assert asyncio.run(_go()) == 1


def test_stage1_claims_session_without_new_connect(live):
    """Стадия 1 синтезирует в готовой сессии: новый коннект не делается."""
    packets = []

    async def _go():
        await tts.preconnect()
        await asyncio.sleep(T_CONNECT + 0.05)     # сессия готова
        t_tok = time.monotonic()                  # «первый токен»
        n = await tts._live_synthesize_preferred(
            "Привет, мир.", "спокойная", _packets(packets))
        dt = time.monotonic() - t_tok
        await asyncio.sleep(0.05)                 # держатель закрывает сессию
        return n, dt

    n, dt = asyncio.run(_go())
    assert n == 2 and packets == [b"A", b"B"], "пакеты идут в TTS как раньше"
    assert live.connect_calls == 1, "стадия 1 коннектилась заново"
    assert dt < T_CONNECT, f"handshake снова на критическом пути ({dt:.2f}с)"
    assert tts.preconnect_status() == "off", "забранная сессия снята с предбанника"
    assert live.closed == 1, "держатель обязан закрыть сессию после release"
    assert live.sessions[0].sent, "текст уходит в сессию через send_client_content"


def test_preferred_falls_back_without_preconnect():
    """Нет предконнекта — синтез прежним путём (фолбэк вызывающего)."""
    calls, got = [], []

    async def _fallback(text, emotion, on_packet, label=""):
        calls.append((text, label))
        await on_packet(b"F")
        return 1

    async def _go():
        return await tts._live_synthesize_preferred(
            "текст", "спокойная", _packets(got), label="стадия 1",
            synth=_fallback)

    assert asyncio.run(_go()) == 1
    assert calls == [("текст", "стадия 1")]
    assert got == [b"F"]


def test_release_preconnect_closes_session_and_frees_slot(live):
    """Команда/отмена: предконнект закрыт, слот семафора вернулся."""
    async def _go():
        await tts.preconnect()
        await asyncio.sleep(T_CONNECT + 0.05)
        assert await _slots_free() == 1, "слот держит предконнект — так и надо"
        await tts.release_preconnect()
        return await _slots_free()

    assert asyncio.run(_go()) == 2
    assert live.closed == 1
    assert tts.preconnect_status() == "off"


def test_unclaimed_preconnect_expires_by_ttl(live):
    """Никто не забрал — сессия закрывается сама, слот возвращается."""
    async def _go():
        await tts.preconnect(ttl=0.1)
        await asyncio.sleep(T_CONNECT + 0.25)
        return tts.preconnect_status(), live.closed, await _slots_free()

    status, closed, slots = asyncio.run(_go())
    assert closed == 1, "простаивающая сессия должна закрыться"
    assert status == "off" and slots == 2


# ── handle_voice_command: предконнект до вердикта классификатора ────


class _FakeRouter:
    """Роутер-двойник: порядок «хук → классификация → вердикт» в order."""

    def __init__(self, decision, order, delay: float = 0.25):
        self.session = SimpleNamespace(pending=None)
        self._decision = decision
        self._order = order
        self._delay = delay

    async def route(self, text, context=None, *, on_llm=None):
        if on_llm is not None:
            on_llm()
        self._order.append("classify")
        await asyncio.sleep(self._delay)
        self._order.append("verdict")
        return self._decision


async def _fake_stream_tokens(contents, **kwargs):
    """Два предложения (две стадии синтеза)."""
    yield "Привет, мир. "
    await asyncio.sleep(0.05)
    yield "Как дела?"


def _ws_env(monkeypatch, order, synth_calls, *, decision, executed=False):
    """Мини-окружение ws: устройство, сеть, перехватчики и предконнект."""
    ws_dev = MagicMock()
    ws_dev.send = AsyncMock()
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
    monkeypatch.setattr(llm, "stream_tokens", _fake_stream_tokens)
    monkeypatch.setattr(llm, "pick_key", lambda api_key=None: "test-key")
    monkeypatch.setattr(llm, "get_client", lambda key: MagicMock())
    monkeypatch.setattr(br, "get_router", lambda: _FakeRouter(decision, order))

    async def _exec_decision(decision, **kw):
        # executed=False → v3-путь уступает разговорному, True → команда.
        return (executed, None)

    monkeypatch.setattr(br, "execute_decision", _exec_decision)
    import modules.game_hub as gh
    monkeypatch.setattr(gh, "get_game_context_for_device", lambda *a: None)

    # Настоящий предконнект (клиент фейковый) + запись порядка вызовов.
    real_preconnect = tts.preconnect

    async def _recording_preconnect(*a, **kw):
        order.append("preconnect")
        return await real_preconnect(*a, **kw)

    monkeypatch.setattr(wh, "tts_preconnect", _recording_preconnect)

    async def _fake_synth(text, emotion, on_packet, label=""):
        synth_calls.append(label)
        await on_packet(b"FALLBACK")
        return 1

    monkeypatch.setattr(voice_mod, "_live_synthesize", _fake_synth)
    return ws_dev


def _record_release(monkeypatch):
    """Реальное закрытие предконнекта + отметка «вызвано»."""
    calls = []
    real_release = tts.release_preconnect

    async def _recording_release():
        calls.append(True)
        await real_release()

    monkeypatch.setattr(wh, "tts_release_preconnect", _recording_release)
    return calls


def _mk_ctx():
    async def ask_voice(**kw):
        await voice_mod.stream_llm_to_tts(
            contents="тест", system="", websocket=kw.get("websocket"),
            device_id=kw.get("device_id") or "laptop",
            max_tokens=60, timeout=6.0, gate=kw.get("gate"))
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


def _data(text="давно не виделись как проходит время"):
    return {"device_id": "laptop", "text": text,
            "active_window": "", "context": []}


def _sent_audio(ws_dev):
    """Аудио, реально ушедшее на устройство, в порядке отправки."""
    import base64
    out = []
    for call in ws_dev.send.await_args_list:
        payload = json.loads(call.args[0])
        if payload.get("type") == "tts_chunk":
            out.append(base64.b64decode(payload["audio"]).decode())
    return out


def test_ws_preconnects_before_verdict_and_reuses_session(monkeypatch, live):
    """Предконнект стартует ДО вердикта классификатора, стадия 1 берёт
    уже открытую сессию — второго коннекта нет."""
    order, synth_calls = [], []
    ws_dev = _ws_env(monkeypatch, order, synth_calls,
                     decision=Decision(None, "conversation"))
    released = _record_release(monkeypatch)

    asyncio.run(wh.handle_voice_command(None, _data(), _mk_ctx()))

    assert order[0] == "preconnect", f"порядок: {order}"
    assert order.index("preconnect") < order.index("verdict")
    assert live.connect_calls == 1, "сессию открывали не один раз"
    assert synth_calls == ["стадия 2"], \
        f"стадия 1 должна взять предбанник, а не коннектиться: {synth_calls}"
    assert _sent_audio(ws_dev) == ["A", "B", "FALLBACK"]
    assert released == [True]


def test_ws_command_closes_preconnect(monkeypatch, live):
    """Команда: предконнект закрывается — TTS не тратится зря."""
    order, synth_calls = [], []
    _ws_env(monkeypatch, order, synth_calls,
            decision=Decision("music.next", "llm"), executed=True)
    released = _record_release(monkeypatch)

    asyncio.run(wh.handle_voice_command(None, _data("смени трек"), _mk_ctx()))

    assert order.index("preconnect") < order.index("classify")
    assert released == [True], "канал предбанника не закрыт"
    assert live.closed == 1 and synth_calls == []
