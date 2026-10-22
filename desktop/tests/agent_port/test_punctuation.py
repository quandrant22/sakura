"""Пунктуация вопросов в _post_process (core/hearing.py)."""
import sys
from pathlib import Path

import pytest

AGENT_ROOT = Path(__file__).resolve().parents[2]
if str(AGENT_ROOT) not in sys.path:
    sys.path.insert(0, str(AGENT_ROOT))

from desktop.core import hearing  # noqa: E402

# (фраза, ожидаемый финальный знак)
QUESTION_TABLE = [
    ("что ты делаешь", "?"),
    ("как дела", "?"),
    ("сколько времени", "?"),
    ("работает ли это", "?"),
    ("а где мой телефон", "?"),
    ("я знаю что делать", "."),
    ("включи как в прошлый раз", "."),
    ("сделай потише", "."),
    ("то ли дождь то ли снег", "."),
    # Известное ограничение: без вопросительного слова/частицы «ли»
    # вопрос не распознаём — ставим точку (Vosk «?» не ставит).
    ("ты меня слышишь", "."),
]


@pytest.mark.parametrize("text,expected", QUESTION_TABLE)
def test_post_process_marks_questions(text, expected):
    out = hearing._post_process(text)
    assert out.endswith(expected), f"{text!r} -> {out!r}"


@pytest.mark.parametrize("text", [
    "Сколько времени?",
    "Открой телеграм.",
    "Стоп!",
])
def test_post_process_keeps_existing_punctuation(text):
    """_post_process не ломает уже расставленную пунктуацию."""
    assert hearing._post_process(text) == text
