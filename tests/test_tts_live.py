"""feat/tts-live (этап 3): модель 3.8 Live + S2, тон, откат, стадии, произношение."""

import asyncio
import logging
from unittest.mock import AsyncMock

import pytest

import modules.speech_prep as sp
import modules.tts_server as tts

M38 = "gemini-3.8-live"
M25 = "gemini-2.5-flash-native-audio-latest"


@pytest.fixture(autouse=True)
def _defaults(monkeypatch):
    monkeypatch.setattr(tts, "TTS_MODEL", M38)
    monkeypatch.setattr(tts, "TTS_FALLBACK_MODEL", M25)
    monkeypatch.setattr(tts, "TTS_STYLE", "S2")
    monkeypatch.setattr(tts, "TTS_TONE", "нейтрально")
    monkeypatch.setattr(tts, "TTS_TONE_FROM_LLM", False)
    monkeypatch.setattr(tts, "_primary_down_until", 0.0)
    monkeypatch.setattr(tts, "TTS_SHORT_SINGLE", True)


def _si(cfg):
    si = cfg.system_instruction
    return si.parts[0].text if si is not None else None


# ── 3.1 конфиги по моделям ─────────────────────────────────────────


def test_config_38_live_s2():
    cfg = tts._live_config(M38)
    assert cfg.thinking_config is None
    assert not cfg.enable_affective_dialog
    assert cfg.proactivity is None
    assert _si(cfg) == tts.S2_TEXT
    assert cfg.response_modalities == ["AUDIO"]


def test_config_25_native_audio_as_before_and_forced_s1():
    cfg = tts._live_config(M25)
    assert cfg.thinking_config.thinking_budget == 0
    assert cfg.enable_affective_dialog is True
    assert cfg.system_instruction is None              # S2 на 2.5 ломается → S1
    assert tts._style(M25) == "S1"
    assert tts._user_text("Привет.", M25).startswith(tts.S1_TEXT)


def test_voice_in_config():
    cfg = tts._live_config(M38, voice="Despina")
    assert cfg.speech_config.voice_config.prebuilt_voice_config.voice_name == "Despina"


def test_user_text_s2_is_text_only():
    assert tts._user_text("Ты меня слышишь?", M38) == "Ты меня слышишь?"


def test_style_s1_on_38(monkeypatch):
    monkeypatch.setattr(tts, "TTS_STYLE", "S1")
    assert tts._live_config(M38).system_instruction is None
    assert tts._user_text("Да.", M38).startswith(tts.S1_TEXT)
    assert "ровным голосом" not in tts._user_text("Да.", M38)


# ── 3.4 тон ─────────────────────────────────────────────────────────


@pytest.mark.parametrize("tone", ["тепло", "сухо-иронично", "серьёзно", "тихо", "бодро"])
def test_tts_tone_goes_to_system_instruction(monkeypatch, tone):
    monkeypatch.setattr(tts, "TTS_TONE", tone)
    assert _si(tts._live_config(M38)) == f"{tts.S2_TEXT} {tts.TONES[tone]}"


def test_unknown_tone_is_neutral(monkeypatch):
    monkeypatch.setattr(tts, "TTS_TONE", "громко")
    assert _si(tts._live_config(M38)) == tts.S2_TEXT


@pytest.mark.parametrize("tag,tone", [("тепло", "тепло"), ("насмешливо", "сухо-иронично"),
                                      ("серьёзно", "серьёзно"), ("шёпотом", "тихо"),
                                      ("радостно", "бодро"), ("загадочно", None)])
def test_tone_from_tag(tag, tone):
    assert tts.tone_from_tag(tag) == tone


def test_llm_tone_off_by_default_tag_stripped():
    tone, text = tts._stage_tone("[ТОН: тепло] Привет.")
    assert tone is None and text == "Привет."


def test_llm_tone_overrides_when_enabled(monkeypatch):
    monkeypatch.setattr(tts, "TTS_TONE_FROM_LLM", True)
    tone, text = tts._stage_tone("[ТОН: тепло] Привет.")
    assert tone == "тепло" and text == "Привет."
    assert _si(tts._live_config(M38, tone=tone)).endswith(tts.TONES["тепло"])


# ── откат модели ───────────────────────────────────────────────────


class _CM:
    def __init__(self, model, fail):
        self.model, self.fail = model, fail

    async def __aenter__(self):
        if self.fail:
            raise RuntimeError("1007 invalid argument")
        return f"session:{self.model}"

    async def __aexit__(self, *a):
        return False


class _Client:
    def __init__(self, failing):
        self.failing, self.calls = set(failing), []
        outer = self

        class _Live:
            def connect(self, model, config):
                outer.calls.append(model)
                return _CM(model, model in outer.failing)

        class _Aio:
            live = _Live()
        self.aio = _Aio()


async def _open(client):
    async with tts._open_session(client) as (session, model):
        return session, model


def test_fallback_when_primary_does_not_start(caplog):
    client = _Client(failing={M38})
    with caplog.at_level(logging.WARNING, logger=tts.log.name):
        session, model = asyncio.run(_open(client))
    assert (session, model) == (f"session:{M25}", M25)
    assert client.calls == [M38, M25]
    assert any("не поднялась" in r.getMessage() for r in caplog.records)
    # дальше — сразу резервная, без повторной попытки основной
    asyncio.run(_open(client))
    assert client.calls == [M38, M25, M25]


def test_primary_retried_after_hold(monkeypatch):
    client = _Client(failing=set())
    monkeypatch.setattr(tts, "_primary_down_until", 0.0)
    assert asyncio.run(_open(client))[1] == M38


def test_rollback_by_setting(monkeypatch):
    monkeypatch.setattr(tts, "TTS_MODEL", M25)
    client = _Client(failing=set())
    assert asyncio.run(_open(client))[1] == M25


def test_fallback_model_failure_raises():
    client = _Client(failing={M38, M25})
    with pytest.raises(RuntimeError):
        asyncio.run(_open(client))


# ── 3.3 / 3.3б стадии ──────────────────────────────────────────────


def test_short_reply_rules():
    assert tts.is_short_reply("Здесь. Экран активен, процессы штатные.")
    assert not tts.is_short_reply("Раз. Два. Три.")
    assert not tts.is_short_reply("а" * 201)


def test_glue_first_min_25():
    assert tts.glue_first(["Здесь.", "Экран активен, процессы штатные.", "Ещё."]) == \
        ["Здесь. Экран активен, процессы штатные.", "Ещё."]
    assert tts.glue_first(["Длинное первое предложение тут.", "Второе."]) == \
        ["Длинное первое предложение тут.", "Второе."]


def _run_stream_tts(monkeypatch, text):
    single, staged = [], []

    async def _single(t, ws, dev, emotion="спокойная"):
        single.append(t)
        return 1

    async def _two(first, rest, ws, dev, emotion, t0, stop=None):
        staged.append((first, rest))
        return 2
    monkeypatch.setattr(tts, "_synthesize_and_stream", _single)
    monkeypatch.setattr(tts, "_stream_two_stage", _two)
    monkeypatch.setattr(tts, "_send_end", AsyncMock())
    asyncio.run(tts.stream_tts_to_device(text, object(), "pc", stop=lambda: False))
    return single, staged


def test_stream_tts_short_reply_single_request(monkeypatch):
    single, staged = _run_stream_tts(monkeypatch, "Здесь. Экран активен, процессы штатные.")
    assert single == ["Здесь. Экран активен, процессы штатные."] and staged == []


def test_stream_tts_long_reply_first_chunk_glued(monkeypatch):
    text = "Здесь. Экран активен. " + "Процессы штатные, нагрузка в норме. " * 6
    single, staged = _run_stream_tts(monkeypatch, text.strip())
    assert single == []
    # «Здесь.» (6) и «Здесь. Экран активен.» (21) короче 25 — склеено дальше
    assert staged[0][0] == "Здесь. Экран активен. Процессы штатные, нагрузка в норме."
    assert len(staged[0][0]) >= tts.MIN_FIRST_CHUNK


def _voice_stages(monkeypatch, tokens):
    import adapters.voice as av
    import sakura_core.llm as llm
    stages = []

    async def _stream(*a, **k):
        for t in tokens:
            yield t

    async def _synth(text, emotion, put, label="", synth=None):
        stages.append(text)
        await put(b"x")
    monkeypatch.setattr(llm, "stream_tokens", _stream)
    monkeypatch.setattr(av, "_live_synthesize", _synth)
    monkeypatch.setattr(av, "_live_synthesize_preferred", _synth)
    monkeypatch.setattr(av, "_make_audio_sender", lambda ws, d: AsyncMock())
    asyncio.run(av.stream_llm_to_tts(contents="т", system="", websocket=object(),
                                     device_id="pc", client=object(), model="m",
                                     api_key="test-key-cache-1"))
    return stages


def test_voice_short_answer_one_stage(monkeypatch):
    assert _voice_stages(monkeypatch, ["Здесь. ", "Экран активен, процессы штатные."]) == \
        ["Здесь. Экран активен, процессы штатные."]


def test_short_single_switch_off_stream_tts(monkeypatch):
    monkeypatch.setattr(tts, "TTS_SHORT_SINGLE", False)
    assert not tts.is_short_reply("Здесь. Экран активен, процессы штатные.")
    text = "Подтверждаю, всё работает. Экран активен, процессы штатные."
    single, staged = _run_stream_tts(monkeypatch, text)
    assert single == [] and staged == [("Подтверждаю, всё работает.", "Экран активен, процессы штатные.")]


def test_short_single_switch_off_voice(monkeypatch):
    monkeypatch.setattr(tts, "TTS_SHORT_SINGLE", False)
    assert _voice_stages(monkeypatch, ["Подтверждаю, всё работает. ", "Экран активен."]) == \
        ["Подтверждаю, всё работает.", "Экран активен."]


def test_short_single_default_on():
    import os
    if "TTS_SHORT_SINGLE" in os.environ:
        pytest.skip("задан в окружении")
    assert tts.TTS_SHORT_SINGLE is True


def test_voice_long_answer_first_stage_at_least_25(monkeypatch):
    stages = _voice_stages(monkeypatch, ["Здесь. ", "Экран активен. ", "Процессы штатные. ",
                                         "Нагрузка в норме."])
    assert stages[0] == "Здесь. Экран активен. Процессы штатные."   # 21 < 25 → + ещё одно
    assert stages[1:] == ["Нагрузка в норме."]


# ── 3.5 подготовка текста к речи ───────────────────────────────────


@pytest.mark.parametrize("raw,spoken", [
    ("Температура 23°C, ветер 3 м/с.", "Температура двадцать три градуса Цельсия, ветер три метра в секунду."),
    ("Загрузка 98%.", "Загрузка девяносто восемь процентов."),
    ("Свободно 1 ГБ.", "Свободно один гигабайт."),
    ("Пинг 21 мс.", "Пинг двадцать одна миллисекунда."),
    ("Скорость 60 км/ч.", "Скорость шестьдесят километров в час."),
    ("Уже 11%.", "Уже одиннадцать процентов."),
    ("Было 1001 раз.", "Было тысяча один раз."),
    ("Ровно 2,5 км/ч.", "Ровно две целых пять десятых километра в час."),
])
def test_numbers_and_units(raw, spoken):
    assert sp.prepare(raw) == spoken


def test_dictionary_case_insensitive_whole_word():
    assert sp.prepare("Открываю telegram и YouTube, Steam и Steamworks.") == \
        "Открываю Телеграм и Ютуб, Стим и Steamworks."
    for k, v in {"Valheim": "Вальхейм", "Palworld": "Палворлд", "Discord": "Дискорд",
                 "Spotify": "Спотифай"}.items():
        assert sp.prepare(k) == v


def test_prep_only_for_tts_text():
    """В TTS уходит подготовленный текст; модули чата/истории его не зовут."""
    assert tts._user_text("Steam 23°C", M38) == "Стим двадцать три градуса Цельсия"
    import pathlib
    root = pathlib.Path(__file__).resolve().parents[1]
    users = [p.relative_to(root).as_posix() for p in root.rglob("*.py")
             if "speech_prep" in p.read_text(encoding="utf-8", errors="ignore")
             and "venv" not in p.parts and "agent" not in p.parts and "tests" not in p.parts]
    assert sorted(users) == ["modules/speech_prep.py", "modules/tts_server.py"]
