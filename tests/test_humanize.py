"""Тесты быстрой стилизации ответов системы в стиле J.A.R.V.I.S. (sakura_core/stylize.py)."""

import asyncio
from unittest.mock import AsyncMock, MagicMock

import config
import sakura_core.bridge as br
from sakura_core.router import Decision
from sakura_core.stylize import (
    HUMANIZE_SYSTEM_PROMPT,
    humanize_command_reply,
    is_informational_action,
)


def test_is_informational_action():
    assert is_informational_action("weather.now") is True
    assert is_informational_action("schedule.today") is True
    assert is_informational_action("schedule.tomorrow") is True
    assert is_informational_action("schedule.next") is True
    assert is_informational_action("schedule.next_couple") is True
    assert is_informational_action("steam.current") is True
    assert is_informational_action("steam.achievements") is True
    assert is_informational_action("steam.playtime") is True
    assert is_informational_action("vps.status") is True
    assert is_informational_action("vps.feeling") is True
    assert is_informational_action("briefing.now") is True

    # Неинформационные или команды управления
    assert is_informational_action("schedule.refresh") is False
    assert is_informational_action("music.next") is False
    assert is_informational_action("system.volume") is False
    assert is_informational_action("open.app") is False
    assert is_informational_action("") is False
    assert is_informational_action(None) is False


def test_humanize_command_reply_success():
    raw = "В Москве сейчас +5 градусов, облачно."
    expected = "Мастер, в столице сейчас плюс пять градусов, небо затянуто облаками."

    mock_gen = AsyncMock(return_value=expected)

    async def _go():
        return await humanize_command_reply(raw, action="weather.now", llm_generator=mock_gen)

    res = asyncio.run(_go())
    assert res == expected
    mock_gen.assert_awaited_once()
    call_args, call_kwargs = mock_gen.call_args
    assert "В Москве сейчас +5 градусов" in call_args[0]
    assert call_kwargs["system"] == HUMANIZE_SYSTEM_PROMPT
    assert "J.A.R.V.I.S." in call_kwargs["system"]
    assert 'Обращайся к Мастеру строго на "Вы"' in call_kwargs["system"]


def test_humanize_command_reply_timeout_fallback():
    raw = "Сегодня: 2 пары. 1. Высшая математика (09:00)."

    async def _slow_gen(*args, **kwargs):
        await asyncio.sleep(2.0)
        return "Не должно дойти"

    async def _go():
        return await humanize_command_reply(raw, action="schedule.today", timeout=0.05, llm_generator=_slow_gen)

    res = asyncio.run(_go())
    assert res == raw


def test_humanize_command_reply_error_fallback():
    raw = "В игре сейчас: Elden Ring Nightreign (34 часа)."
    mock_gen = AsyncMock(side_effect=RuntimeError("API quota exhausted"))

    async def _go():
        return await humanize_command_reply(raw, action="steam.current", llm_generator=mock_gen)

    res = asyncio.run(_go())
    assert res == raw


def test_humanize_command_reply_empty_response_fallback():
    raw = "Статус сервера: все сервисы работают штатно."
    mock_gen = AsyncMock(return_value="   ")

    async def _go():
        return await humanize_command_reply(raw, action="vps.status", llm_generator=mock_gen)

    res = asyncio.run(_go())
    assert res == raw


def test_humanize_command_reply_non_informational_action():
    raw = "Громкость 70."
    mock_gen = AsyncMock(return_value="Стилизованная фраза")

    async def _go():
        return await humanize_command_reply(raw, action="system.volume", llm_generator=mock_gen)

    res = asyncio.run(_go())
    assert res == raw
    mock_gen.assert_not_called()


def test_humanize_command_reply_no_keys_in_test_env(monkeypatch):
    monkeypatch.setattr(config, "GEMINI_KEYS", [])
    raw = "Сводка: температура 12 градусов."

    async def _go():
        return await humanize_command_reply(raw, action="weather.now", llm_generator=None)

    res = asyncio.run(_go())
    assert res == raw


def test_v3_fast_path_integration_with_humanize(monkeypatch):
    """v3_fast_path стилизует ответ информационной VPS-команды перед озвучкой."""
    monkeypatch.setattr(br, "get_router", lambda: MagicMock(
        route=AsyncMock(return_value=Decision("weather.now", "llm"))))

    async def _fake_exec(decision, **kw):
        return (True, ("В Москве +5, облачно.", True))
    monkeypatch.setattr(br, "execute_decision", _fake_exec)

    async def _fake_humanize(text, action=""):
        return f"Мастер, погода для Вас: {text}"
    monkeypatch.setattr("sakura_core.stylize.humanize_command_reply", _fake_humanize)

    spoken = []
    async def _speak(phrase, listen=None):
        spoken.append(phrase)

    done = asyncio.run(br.v3_fast_path("какая погода", data={}, device_ws=None, device_id="laptop",
                                       register_command=None, speak=_speak))
    assert done is True
    assert spoken == ["Мастер, погода для Вас: В Москве +5, облачно."]


def test_v3_fast_path_integration_does_not_stylize_on_backend_error(monkeypatch):
    """Если команда завершилась ошибкой (ok=False), сырой текст ошибки не стилизуется."""
    monkeypatch.setattr(br, "get_router", lambda: MagicMock(
        route=AsyncMock(return_value=Decision("weather.now", "llm"))))

    async def _fake_exec(decision, **kw):
        return (True, ("Источник погоды недоступен.", False))
    monkeypatch.setattr(br, "execute_decision", _fake_exec)

    humanize_mock = AsyncMock()
    monkeypatch.setattr("sakura_core.stylize.humanize_command_reply", humanize_mock)

    spoken = []
    async def _speak(phrase, listen=None):
        spoken.append(phrase)

    done = asyncio.run(br.v3_fast_path("какая погода", data={}, device_ws=None, device_id="laptop",
                                       register_command=None, speak=_speak))
    assert done is True
    assert spoken == ["Источник погоды недоступен."]
    humanize_mock.assert_not_called()
