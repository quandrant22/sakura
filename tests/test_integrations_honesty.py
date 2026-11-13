"""Честные статусы интеграций: не настроено → ok=False сразу, без ожиданий.

Сводка (briefing.now) на пути v3, календарь без token.json, Steam без ключей,
молчаливое отключение SearXNG, запасное тихоокеанское время лимитера.
"""

import asyncio
import datetime as dt
import logging
import time
from zoneinfo import ZoneInfo

import pytest

import config
import modules.briefing as briefing
import modules.calendar_module as cal
import modules.voice_info as vi
from capabilities._vps import vps_answer
from sakura_core.executor import ExecutionContext, get_handler


def _run(coro):
    return asyncio.run(coro)


def _call(action_id: str, text: str = ""):
    ctx = ExecutionContext(device_ws=None, device_id="pc",
                           register_command=lambda *a, **k: None,
                           extra={"text": text, "source": "test"})
    return _run(get_handler(action_id)(ctx))


# ── сводка ──────────────────────────────────────────────────────────────


@pytest.fixture
def briefing_sources(monkeypatch):
    values = {"_get_calendar_snippet": "", "_get_tasks_snippet": "",
              "_get_weather_snippet": "", "_get_self_snippet": "",
              "_get_anniversaries_snippet": "", "_get_schedule_snippet": ""}
    for name in values:
        monkeypatch.setattr(briefing, name, lambda n=name: values[n])
    return values


def test_briefing_now_through_v3_handler(briefing_sources):
    briefing_sources["_get_weather_snippet"] = "Ясно +5°C 60%"
    briefing_sources["_get_tasks_snippet"] = "Задачи: купить хлеб"
    briefing_sources["_get_schedule_snippet"] = "Пары сегодня: 18:40 Практика, ауд. 531"
    text, ok = _call("briefing.now", "что нового")
    assert ok is True
    assert "Погода: Ясно +5°C 60%." in text
    assert "купить хлеб" in text and "18:40 Практика" in text
    assert "Составь" not in text, "в ответ команды не должна попадать инструкция для модели"


def test_briefing_now_empty_sources_is_honest(briefing_sources):
    text, ok = _run(vi.handle("briefing:now"))
    assert ok is True and "не вижу" in text
    assert text != "Такой команды у меня пока нет."


def test_briefing_prompt_still_wraps_facts(briefing_sources):
    briefing_sources["_get_tasks_snippet"] = "Задачи: купить хлеб"
    prompt = _run(briefing.build_briefing_prompt())
    assert prompt.startswith("Данные для брифинга:") and "купить хлеб" in prompt


def test_briefing_sources_are_read_concurrently(briefing_sources, monkeypatch):
    def slow():
        time.sleep(0.3)
        return ""
    for name in briefing_sources:
        monkeypatch.setattr(briefing, name, slow)
    t0 = time.monotonic()
    _run(briefing.build_briefing_facts())
    assert time.monotonic() - t0 < 1.0, "шесть источников по 0.3с должны идти параллельно"


# ── календарь ───────────────────────────────────────────────────────────


def test_calendar_without_token_answers_at_once(monkeypatch, tmp_path):
    monkeypatch.setattr(cal, "TOKEN_FILE", str(tmp_path / "token.json"))
    monkeypatch.setattr(cal, "build", lambda *a, **k: pytest.fail("сеть трогать нельзя"))
    t0 = time.monotonic()
    text, ok = _call("calendar.list", "что в календаре")
    assert time.monotonic() - t0 < 1.0
    assert (text, ok) == ("Google Календарь не подключён.", False)
    assert cal.get_upcoming_events() == [] and cal.get_calendar_context() == ""


def test_calendar_without_google_libs_is_not_empty_calendar(monkeypatch, tmp_path):
    token = tmp_path / "token.json"
    token.write_text("{}", encoding="utf-8")
    monkeypatch.setattr(cal, "TOKEN_FILE", str(token))
    monkeypatch.setattr(cal, "build", None)
    with pytest.raises(cal.CalendarUnavailable):
        cal.get_calendar_service()
    text, ok = _call("calendar.list")
    assert ok is False and "не подключён" in text and "событий нет" not in text


# ── Steam ───────────────────────────────────────────────────────────────


@pytest.mark.parametrize("action", ["steam.current", "steam.recent", "steam.last",
                                    "steam.achievements", "steam.playtime", "steam.progress"])
def test_steam_without_keys_says_not_configured(monkeypatch, action):
    monkeypatch.setattr(config, "STEAM_KEY", "")
    monkeypatch.setattr(config, "STEAM_ID", "")
    text, ok = _run(vps_answer(action, "Elden Ring", "сколько наиграл"))
    assert (text, ok) == (vi.STEAM_NOT_CONFIGURED, False)


def test_steam_with_keys_reaches_source(monkeypatch):
    import modules.steam_integration as steam
    monkeypatch.setattr(config, "STEAM_KEY", "k")
    monkeypatch.setattr(config, "STEAM_ID", "1")

    async def recent():
        return [{"name": "Valheim", "playtime_2weeks": 180}]
    monkeypatch.setattr(steam, "get_recently_played", recent)
    text, ok = _run(vps_answer("steam.recent"))
    assert ok is True and "Valheim" in text


# ── SearXNG ─────────────────────────────────────────────────────────────


def test_searxng_without_url_warns_once(monkeypatch, caplog):
    from sakura_core.search import providers
    monkeypatch.setattr(config, "SEARCH_PROVIDERS", "parallel,searxng")
    monkeypatch.setattr(config, "SEARXNG_URL", "")
    monkeypatch.setattr(providers, "_searxng_warned", False)
    with caplog.at_level(logging.WARNING, logger="sakura.search"):
        assert providers.enabled() == ["parallel"]
        assert providers.enabled() == ["parallel"]
    warnings = [r for r in caplog.records if "SEARXNG_URL" in r.getMessage()]
    assert len(warnings) == 1

    monkeypatch.setattr(config, "SEARXNG_URL", "http://127.0.0.1:8888")
    assert providers.enabled() == ["parallel", "searxng"]


# ── лимитер: тихоокеанское время без tzdata ─────────────────────────────


def test_pacific_fallback_matches_zone_database():
    from sakura_core.rate_limiter import _PacificFallback
    fallback, real = _PacificFallback(), ZoneInfo("America/Los_Angeles")
    moment = dt.datetime(2025, 1, 1, tzinfo=dt.timezone.utc)
    while moment.year < 2028:
        assert (moment.astimezone(fallback).replace(tzinfo=None)
                == moment.astimezone(real).replace(tzinfo=None)), moment
        moment += dt.timedelta(hours=1)
    for day in (dt.date(2026, 1, 15), dt.date(2026, 7, 15)):
        assert (dt.datetime.combine(day, dt.time(0), fallback).timestamp()
                == dt.datetime.combine(day, dt.time(0), real).timestamp())


# ── конфигурация ────────────────────────────────────────────────────────


def test_secure_public_url_default_is_tls(monkeypatch):
    import importlib
    monkeypatch.delenv("SECURE_PUBLIC_URL", raising=False)
    src = open(config.__file__, encoding="utf-8").read()
    assert 'os.getenv("SECURE_PUBLIC_URL", "wss://' in src
    assert importlib.util.find_spec("tzdata") is not None, "tzdata должен быть установлен"


def test_telegram_adapter_has_no_dummy_token():
    import adapters.telegram as tg
    src = open(tg.__file__, encoding="utf-8").read()
    assert "DUMMY_TOKEN" not in src
    assert "TELEGRAM_TOKEN не задан" in src
