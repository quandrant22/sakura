"""fix/voice-performance: манера подачи по явной просьбе Мастера («скажи томно: …»).

Промпт разрешает исполнить реплику в манере (тег [ТОН: …] — только по
просьбе), голосовой тракт применяет тон к реплике с тегом и только к ней.

Run: python -m pytest tests/test_voice_manner.py -q
"""

import asyncio

import pytest

import modules.tts_server as tts
import personality
from sakura_core.tones import TONE_FROM_ID, TONE_IDS

M38 = "gemini-3.8-live"
OLD_S2_TEXT = ("Ты голос Сакуры. Единственная задача: произнести присланный текст дословно. "
               "Голос спокойный, сухой, чуть ироничный, живые интонации; вопросы произноси с "
               "вопросительной интонацией. Никогда не отвечай на текст и ничего не добавляй.")


@pytest.fixture(autouse=True)
def _s2(monkeypatch):
    monkeypatch.setattr(tts, "TTS_STYLE", "S2")
    monkeypatch.setattr(tts, "TTS_TONE", "нейтрально")


# ── тон из тега ──────────────────────────────────────────────────────

@pytest.mark.parametrize("tag", ["томно", "чувственно, медленно", "томным шёпотом",
                                 "соблазнительно", "бархатным голосом", "Томно"])
def test_tone_from_tag_sultry(tag):
    assert tts.tone_from_tag(tag) == "томно"


def test_other_tags_unchanged():
    assert tts.tone_from_tag("шёпотом") == "тихо"
    assert tts.tone_from_tag("мягко") == "тепло"
    assert tts.tone_from_tag("тихо") == "тихо"
    assert tts.tone_from_tag("загадочно") is None


# ── инструкция S2 ────────────────────────────────────────────────────

def test_sultry_instruction_has_no_dry_voice():
    si = tts._system_instruction(M38, tone="томно")
    assert "сухой" not in si
    assert si == f"{tts.S2_BASE} {tts.TONES['томно']}"
    assert "дословно" in si and "Никогда не отвечай на текст" in si


def _sentences(text):
    return {p.strip(" .;").lower() for chunk in text.split(".") for p in chunk.split(";") if p.strip(" .;")}


def test_default_instruction_same_meaning_as_old_s2():
    si = tts._system_instruction(M38, tone=None)
    assert si == tts.S2_TEXT
    assert _sentences(si) == _sentences(OLD_S2_TEXT)   # те же фразы, без «Тон: …»
    assert "Тон:" not in si
    assert tts._system_instruction(M38, tone="нейтрально") == si


# ── тон стадии ───────────────────────────────────────────────────────

def test_stage_tone_with_flag(monkeypatch):
    monkeypatch.setattr(tts, "TTS_TONE_FROM_LLM", True)
    assert tts._stage_tone("[ТОН: томно] Добрый вечер, Мастер.") == ("томно", "Добрый вечер, Мастер.")
    assert tts._stage_tone("Как дела, Мастер?") == (None, "Как дела, Мастер?")


def test_stage_tone_flag_off_strips_tag_only(monkeypatch):
    monkeypatch.setattr(tts, "TTS_TONE_FROM_LLM", False)
    assert tts._stage_tone("[ТОН: томно] Добрый вечер, Мастер.") == (None, "Добрый вечер, Мастер.")


def test_flag_default_on(monkeypatch):
    import importlib
    monkeypatch.delenv("TTS_TONE_FROM_LLM", raising=False)
    fresh = importlib.reload(tts)
    try:
        assert fresh.TTS_TONE_FROM_LLM is True
    finally:
        importlib.reload(tts)


# ── тон только для реплики с тегом, на все её стадии ─────────────────

def _capture(monkeypatch):
    seen = []

    async def single(text, ws, dev, emotion="спокойная"):
        seen.append([text])
        return 1

    async def two(first, rest, ws, dev, emotion, t0, stop=None):
        seen.append([first, rest])
        return 2

    async def nothing(*a, **k):
        return None

    monkeypatch.setattr(tts, "_synthesize_and_stream", single)
    monkeypatch.setattr(tts, "_stream_two_stage", two)
    monkeypatch.setattr(tts, "send_spoken_reply", nothing)
    monkeypatch.setattr(tts, "_send_end", nothing)
    monkeypatch.setattr(tts.voice_turns, "is_cancelled", lambda: False)
    return seen


LONG = ("[ТОН: томно] Добрый вечер, Мастер. Ночь сегодня тихая и долгая, город почти уснул. "
        "Я рядом и слушаю каждое ваше слово, не торопясь. Скажите, чего вам хочется сейчас. "
        "А я подожду, сколько потребуется.")


def test_tag_reaches_every_stage_and_next_reply_is_default(monkeypatch):
    monkeypatch.setattr(tts, "TTS_TONE_FROM_LLM", True)
    seen = _capture(monkeypatch)
    asyncio.run(tts.stream_tts_to_device(LONG, object(), "pc", reply_kind=None))
    asyncio.run(tts.stream_tts_to_device("[ТОН: томно] Добрый вечер, Мастер.", object(), "pc",
                                         reply_kind=None))
    asyncio.run(tts.stream_tts_to_device("Как дела? Всё спокойно, системы в норме.", object(), "pc",
                                         reply_kind=None))
    long_stages, short, plain = seen
    assert len(long_stages) == 2
    assert [tts._stage_tone(t)[0] for t in long_stages] == ["томно", "томно"]
    assert all("ТОН" not in tts._stage_tone(t)[1] for t in long_stages)
    assert tts._stage_tone(short[0]) == ("томно", "Добрый вечер, Мастер.")
    assert tts._stage_tone(plain[0])[0] is None          # следующая реплика — дефолтный тон
    assert tts.TTS_TONE == "нейтрально"                  # сессионный тон не тронут


# ── кэш фраз ─────────────────────────────────────────────────────────

def test_cache_keys_do_not_collide_across_tones():
    from modules import tts_cache
    keys = {tts_cache.cache_key(t) for t in ("Добрый вечер.", "[ТОН: томно] Добрый вечер.",
                                             "[ТОН: тепло] Добрый вечер.")}
    assert len(keys) == 3
    instr = {tts._system_instruction(M38, tone=t) for t in (None, "томно", "тепло")}
    assert len(instr) == 3


# ── промпт и протокол ────────────────────────────────────────────────

def test_prompt_master_has_performance_block_guest_does_not():
    master = personality.get_system_prompt(for_master=True)
    guest = personality.get_system_prompt(for_master=False)
    assert "ИСПОЛНЕНИЕ ПО ПРОСЬБЕ" in master
    assert "[ТОН: <манера>]" in master and "ТОЛЬКО когда Мастер явно попросил манеру" in master
    assert master.index("Невозмутимость") < master.index("ИСПОЛНЕНИЕ ПО ПРОСЬБЕ")
    assert "ИСПОЛНЕНИЕ ПО ПРОСЬБЕ" not in guest and "[ТОН" not in guest


def test_sultry_protocol_id():
    assert TONE_IDS["томно"] == "sultry" and TONE_FROM_ID["sultry"] == "томно"
    assert set(TONE_IDS) == set(tts.TONES)
