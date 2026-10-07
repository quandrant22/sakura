"""tests/test_stt_e2e_text.py — разбор текста STT от e2e-моделей GigaAM v3
(заглавные, запятые, точки, цифры) на стороне агента."""

from unittest.mock import MagicMock

import pytest

import core.hearing as H

E2E_PHRASES = [
    "Сакура, сделай потише на 20.",
    "Да.",
    "Открой Steam.",
    "Ты меня слышишь?",
]


def _hearing():
    h = H.Hearing.__new__(H.Hearing)
    h.agent = MagicMock()
    h._dialog = False
    return h


@pytest.mark.parametrize("text", E2E_PHRASES)
def test_plain_e2e_phrase_goes_to_server_unchanged(text):
    """Обычные фразы: не закладка, не игровой режим, диалог не трогают."""
    h = _hearing()
    assert H._bookmark_content(text) is None
    assert h._maybe_game_mode(text) is False
    h._update_dialog(text)
    assert h._dialog is False
    h.agent.bus.emit.assert_not_called()
    h.agent.set_state.assert_not_called()


@pytest.mark.parametrize("text, expected", [
    ("Сакура, запомни это: купить хлеб!", "купить хлеб"),
    ("Запомни это. Купить хлеб.", "Купить хлеб"),
    ("Сохрани это, позвонить маме?", "позвонить маме"),
    ("запомни это купить хлеб", "купить хлеб"),          # как раньше (Vosk/v2)
])
def test_bookmark_strips_e2e_punctuation(text, expected):
    assert H._bookmark_content(text) == expected


def test_bookmark_too_short_is_not_bookmark():
    assert H._bookmark_content("Запомни это.") is None


@pytest.mark.parametrize("text, on", [
    ("Включи игровой режим.", True),
    ("Сакура, игровой режим!", True),
    ("Выключи игровой режим.", False),
    ("Выйди из игрового режима.", False),
])
def test_game_mode_survives_e2e_text(text, on):
    h = _hearing()
    assert h._maybe_game_mode(text) is True
    h.agent.bus.emit.assert_called_once_with("game_mode", on=on)


def test_dialog_toggle_survives_e2e_text():
    h = _hearing()
    h._update_dialog("Давай поболтаем?")
    assert h._dialog is True
    h._update_dialog("Хватит, спасибо.")
    assert h._dialog is False
