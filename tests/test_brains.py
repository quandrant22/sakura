"""feat/brains: в данных промпта нет счётчиков и сроков (характер не тронут)."""

import asyncio
import re
from datetime import date, datetime, timedelta

import pytest

import modules.context as ctx
import modules.emotional_memory as em
import modules.relationship as rel
import modules.rituals as rituals
import modules.sakura_narrative as nar
import personality

COUNTER = re.compile(r"\d+\s*(дн|час|мин|раз)", re.I)
RULE = ("Не называй счётчики и сроки — дни вместе, минуты в игре, сколько раз писала, "
        "номер версии — если Мастер сам не спросил. Время суток бери только из строки СЕЙЧАС.")


# ── 5.1 персона ─────────────────────────────────────────────────────


def test_persona_example_without_counter():
    prompt = personality.get_system_prompt()
    assert "«Опять игра. Не то чтобы это моё дело.»" in prompt
    assert "Третий час в игре" not in prompt


def test_persona_has_rule_and_grew_at_most_60_tokens():
    prompt = personality.get_system_prompt()
    assert RULE in prompt
    added = len(prompt) - len(prompt.replace(RULE + "\n", ""))
    assert added / 3.5 <= 60, added


# ── 5.2а narrative ──────────────────────────────────────────────────


@pytest.mark.parametrize("days,phrase", [
    (0, "мы знакомы недавно"), (29, "мы знакомы недавно"),
    (30, "мы знакомы уже не первый месяц"), (89, "мы знакомы уже не первый месяц"),
    (90, "мы давно вместе"), (199, "мы давно вместе"),
    (200, "мы вместе очень давно"), (1000, "мы вместе очень давно"),
])
def test_together_phrase(days, phrase):
    assert nar.together_phrase(days) == phrase


class _Rows:
    def __init__(self, rows):
        self._rows = rows

    def fetchall(self):
        return self._rows


class _Conn:
    def execute(self, sql, *a):
        return _Rows([{"text": "Мастер находится дома"},
                      {"text": "Мастер потратил вечер на отладку звука."},
                      {"text": "Мастер играет в видеоигры."}])


def _build_narrative(monkeypatch, days):
    import memory.db as db
    import modules.episodes as episodes
    import modules.secret_diary as diary
    monkeypatch.setattr(nar, "_narrative_cache", "")
    monkeypatch.setattr(nar, "_cache_built_at", 0.0)
    monkeypatch.setattr(rel, "get_first_run_date", lambda: date(2026, 6, 14))
    monkeypatch.setattr(rel, "get_relationship_age_days", lambda: days)
    monkeypatch.setattr(rel, "get_sakura_interests", lambda: [])
    monkeypatch.setattr(db, "_conn", lambda: _Conn())
    monkeypatch.setattr(episodes, "get_recent_episodes", lambda limit=5: [
        {"text": "Выполнила команду: Да. → system:shutdown"},
        {"text": "Выполнила команду: Да. → system:shutdown"},
        {"text": "Мастер находится на работе."},
        {"text": "Спорили о часовых поясах."},
    ])
    monkeypatch.setattr(diary, "get_recent_entries", lambda limit=2: [])
    return asyncio.run(nar.build_narrative())


@pytest.mark.parametrize("days", [5, 116, 400])
def test_narrative_no_counters_and_no_noise(monkeypatch, days):
    text = _build_narrative(monkeypatch, days)
    assert text.startswith("МОЯ ИСТОРИЯ:")
    assert nar.together_phrase(days).capitalize() in text
    assert not COUNTER.search(text), text
    assert "Выполнила команду" not in text
    assert "находится" not in text
    assert "Спорили о часовых поясах" in text
    assert "отладку звука" in text


# ── 5.2б ctx ────────────────────────────────────────────────────────


def _ctx_block(monkeypatch, tmp_path, proactive):
    class _Fixed(datetime):
        @classmethod
        def now(cls, tz=None):
            return datetime(2026, 10, 8, 21, 0)
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(ctx, "datetime", _Fixed)
    monkeypatch.setattr(ctx, "get_devices_snapshot", lambda: {})
    monkeypatch.setattr(ctx, "get_health_snapshot", lambda: {})
    monkeypatch.setattr(ctx, "get_sakura_mood", lambda: {})
    monkeypatch.setattr(ctx, "get_last_proactive", lambda: proactive)
    monkeypatch.setattr(ctx, "get_silence_minutes", lambda: 0)
    return ctx.build_context_block()


def test_ctx_wrote_today_without_count(monkeypatch, tmp_path):
    block = _ctx_block(monkeypatch, tmp_path,
                       {"count_today": 3, "topics_today": ["monitor_device"]})
    assert "Сегодня уже писала по своей инициативе." in block
    assert not COUNTER.search(block), block
    assert "monitor_device" not in block


def test_ctx_no_line_when_zero(monkeypatch, tmp_path):
    block = _ctx_block(monkeypatch, tmp_path, {"count_today": 0, "topics_today": []})
    assert "писала" not in block.lower()


# ── 5.2в version ────────────────────────────────────────────────────


@pytest.mark.parametrize("days", [10, 100, 200, 400])
def test_version_hint_without_number(monkeypatch, days):
    monkeypatch.setattr(rel, "get_first_run_date", lambda: date.today() - timedelta(days=days))
    hint = em.get_version_hint()
    assert hint and "ВЕРСИЯ" not in hint
    assert not re.search(r"\d", hint), hint


# ── 5.2г return-hint ────────────────────────────────────────────────


@pytest.mark.parametrize("hours", [9, 30, 100])
def test_return_hint_without_hours(monkeypatch, hours):
    last = datetime.now() - timedelta(hours=hours)
    monkeypatch.setattr(rituals, "_load", lambda: {"last_interaction": str(last)})
    hint = rituals.get_return_context()["prompt_hint"]
    assert hint
    assert not COUNTER.search(hint), hint
    assert not re.search(r"\d", hint), hint
