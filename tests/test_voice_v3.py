"""Тесты этапа 4: клиенты LLM, бюджеты, честный стриминг голоса.

Run: python -m pytest tests/test_voice_v3.py -q
"""

import asyncio
import time

import pytest

import sakura_core.llm as llm
from sakura_core import budget


# ── llm: клиент в кэше, один раз за процесс ───────────────────────────────


def test_client_cached_one_per_process():
    before = llm.created_count()
    c1 = llm.get_client("test-key-cache-1")
    c2 = llm.get_client("test-key-cache-1")
    assert c1 is c2
    assert llm.created_count() == before + 1  # второй вызов не создаёт новый
    c3 = llm.get_client("test-key-cache-2")
    assert c3 is not c1


# ── llm: таймауты и фолбэк моделей ────────────────────────────────────────


class _SlowModels:
    def generate_content(self, **kwargs):
        time.sleep(1.0)
        raise AssertionError("не должен дожить до конца")


class _FakeClient:
    def __init__(self, models):
        self.models = models


def test_generate_timeout_kills_hang(monkeypatch):
    monkeypatch.setattr(llm, "get_client", lambda key: _FakeClient(_SlowModels()))
    t0 = time.monotonic()
    text = asyncio.get_event_loop().run_until_complete(
        llm.generate("тест", timeout=0.05)
    )
    dt = time.monotonic() - t0
    assert text == ""
    assert dt < 1.0  # зависший вызов не подвесил путь (в v2 подвешивал)


def test_generate_falls_back_between_models(monkeypatch):
    calls = []

    class _FirstFails:
        def generate_content(self, *, model, **kwargs):
            calls.append(model)
            if model == llm.config.MAIN_MODEL:
                raise RuntimeError("упала основная")
            return type("R", (), {"text": "ответ"})()

    monkeypatch.setattr(llm, "get_client", lambda key: _FakeClient(_FirstFails()))
    text = asyncio.get_event_loop().run_until_complete(llm.generate("тест"))
    assert text == "ответ"
    assert calls == [llm.config.MAIN_MODEL, llm.config.FALLBACK_MODEL]


def test_stream_tokens_yields_incrementally(monkeypatch):
    class _Chunk:
        def __init__(self, t):
            self.text = t

    class _StreamModels:
        def generate_content_stream(self, **kwargs):
            return iter([_Chunk("При"), _Chunk("вет. "), _Chunk("Как дела?")])

    monkeypatch.setattr(llm, "get_client", lambda key: _FakeClient(_StreamModels()))

    async def _collect():
        return [t async for t in llm.stream_tokens("тест")]

    assert asyncio.get_event_loop().run_until_complete(_collect()) == \
        ["При", "вет. ", "Как дела?"]


# ── бюджет: предупреждение с троттлингом ──────────────────────────────────


def test_budget_warns_on_exceed_and_throttles(caplog):
    budget._last_warn.clear()
    with caplog.at_level("WARNING", logger="sakura.budget"):
        budget.check("command_registry", 500)
        budget.check("command_registry", 600)   # в пределах 5с — тишина
    warns = [r for r in caplog.records if "command_registry" in r.message]
    assert len(warns) == 1
    assert "500" in warns[0].message
    # до бюджета — не пишем
    caplog.clear()
    with caplog.at_level("WARNING", logger="sakura.budget"):
        budget._last_warn.clear()
        budget.check("command_registry", 100)
    assert not [r for r in caplog.records if "command_registry" in r.message]


# ── голосовой адаптер: честный стриминг ───────────────────────────────────


def test_iter_sentences_releases_incrementally():
    from adapters.voice import iter_sentences
    consumed = []

    async def tokens():
        for t in ("Привет, Мастер", ". ", "Как дела?"):
            consumed.append(t)
            yield t

    async def _go():
        out = []
        async for s in iter_sentences(tokens()):
            out.append((s, len(consumed)))
        return out

    out = asyncio.get_event_loop().run_until_complete(_go())
    # первое предложение высвобождено, когда прочитан только 2-й токен
    assert out[0] == ("Привет, Мастер.", 2)
    assert out[1][0] == "Как дела?"


def test_voice_stream_sends_packets_in_order(monkeypatch):
    import adapters.voice as av

    synth_started = []
    consumed = []

    class FakeWS:
        async def send(self, raw):
            sent.append(raw)

    async def fake_stream_tokens(*args, **kwargs):
        for t in ("Первая фраза. ", "Вторая фраза. "):
            consumed.append(t)
            yield t

    async def fake_synthesize(text, emotion, put, label=""):
        synth_started.append((text, len(consumed)))
        for p in (b"a1", b"a2"):
            await put(p)

    sent = []

    def fake_sender(ws, device_id):
        async def _s(packet):
            sent.append(packet)
        return _s

    monkeypatch.setattr(llm, "stream_tokens", fake_stream_tokens)
    monkeypatch.setattr(av, "_live_synthesize", fake_synthesize)
    monkeypatch.setattr(av, "_make_audio_sender", fake_sender)

    full_text, emotion = asyncio.get_event_loop().run_until_complete(
        av.stream_llm_to_tts(
            contents="тест", system="", websocket=FakeWS(), device_id="laptop",
            client=object(), model="m", api_key="test-key-cache-1",
        )
    )
    # синтез обоих предложений запущен, в исходном порядке, полный текст собран
    assert [t for t, _ in synth_started] == ["Первая фраза.", "Вторая фраза."]
    assert [p for p in sent if isinstance(p, bytes)] == [b"a1", b"a2", b"a1", b"a2"]
    assert full_text == "Первая фраза. Вторая фраза."


def test_voice_stream_empty_falls_back_to_generate(monkeypatch):
    import adapters.voice as av

    async def empty_stream(*args, **kwargs):
        return
        yield  # pragma: no cover

    async def fake_generate(*args, **kwargs):
        return "EMOTION:радостная\nГотово, Мастер. Всё сделано."

    started = []

    async def fake_two_stage(first, rest, ws, dev, emotion, t0, stop=None):
        started.append((first, rest, emotion))
        return 4

    monkeypatch.setattr(llm, "stream_tokens", empty_stream)
    monkeypatch.setattr(llm, "generate", fake_generate)
    monkeypatch.setattr(av, "_stream_two_stage", fake_two_stage)

    text, emotion = asyncio.get_event_loop().run_until_complete(
        av.stream_llm_to_tts(contents="тест", system="", websocket=object(),
                             device_id="laptop", client=object(), model="m",
                             api_key="test-key-cache-1")
    )
    assert text == "Готово, Мастер. Всё сделано."
    assert emotion == "радостная"
    assert started and started[0][0] == "Готово, Мастер." and started[0][1] == "Всё сделано."

