"""Состояние диалога (этап 2) — один объект вместо словарей modules/state.py
(_pending_system / _pending_plan / _pending_clarify) и глобального флага forget.

Поля ожидания: что ждём, от какого устройства, до какого времени, исходное
действие. Логика подтверждения не изобретается: check_confirmation перенесена
как есть из modules/state.py:85 (границы слов, приоритет отрицания, 15 тестов).
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from typing import Optional

log = logging.getLogger("sakura.session")

# ── check_confirmation: перенесено как есть из modules/state.py ──────────

_PS_CONFIRM_WORDS = frozenset({
    "да", "давай", "подтверждаю", "подтверждай", "подтвердить",
    "конечно", "точно", "ага", "угу", "ок", "окей", "валяй",
    "действуй", "выключай",
})
_PS_CONFIRM_FILLERS = frozenset({"пожалуйста", "ну", "тогда", "уже", "сейчас"})

_PS_DENY_WORDS = (
    "нет", "отмена", "стоп", "не надо", "хватит", "отставить",
    "передумал", "не выключай", "не выключайте", "отмени",
    "отменить", "не надо", "не подтверждаю", "не подтверждай",
)

# Фразы, содержащие отрицание — всегда отменяют, даже если содержат
# слово подтверждения ("не подтверждаю", "не выключай").
_PS_DENY_PHRASES = (
    "не подтверждаю", "не подтверждай", "не выключай", "не выключайте",
    "не надо", "передумал", "отменить", "отмени",
)


def check_confirmation(text: str) -> str | None:
    """Проверить, содержит ли текст подтверждение или отмену.

    Возвращает:
      "confirm" — подтверждение выполнено
      "deny"    — отмена
      None      — ни то, ни другое (обычная реплика)

    Приоритет у отрицания: «нет, не подтверждаю» → deny.
    """
    if not text:
        return None

    def tokenize(value: str) -> list[str]:
        tokens: list[str] = []
        current: list[str] = []
        for character in value.lower():
            if character.isalpha():
                current.append(character)
            elif current:
                tokens.append("".join(current))
                current.clear()
        if current:
            tokens.append("".join(current))
        return tokens

    tokens = tokenize(text)

    def contains_phrase(phrase: str) -> bool:
        phrase_tokens = tokenize(phrase)
        width = len(phrase_tokens)
        return any(tokens[index:index + width] == phrase_tokens
                   for index in range(len(tokens) - width + 1))

    # Отрицание всегда имеет приоритет над подтверждающими словами.
    if any(contains_phrase(phrase) for phrase in _PS_DENY_PHRASES):
        return "deny"
    if any(contains_phrase(word) for word in _PS_DENY_WORDS):
        return "deny"

    allowed = _PS_CONFIRM_WORDS | _PS_CONFIRM_FILLERS
    if (tokens and len(tokens) <= 4
            and set(tokens) <= allowed
            and set(tokens) & _PS_CONFIRM_WORDS):
        return "confirm"

    return None


# ── Ожидание ──────────────────────────────────────────────────────────────

DEFAULT_TTL = 60.0  # как TTL подтверждений system:* в v2


@dataclass
class Pending:
    """Чего мы ждём от Мастера."""

    kind: str                     # "confirm" | "plan" | "clarify"
    action: Optional[str] = None  # исходное действие (для confirm)
    device: Optional[str] = None  # от какого устройства ждём ответ
    until: float = 0.0            # до какого времени (time.monotonic())
    payload: dict = field(default_factory=dict)  # план / варианты уточнения


class Session:
    """Состояние одного диалога: активное ожидание и его разрешение."""

    def __init__(self):
        self._pending: Optional[Pending] = None

    # — выставить ожидание —
    def expect(self, kind: str, *, action: Optional[str] = None,
               device: Optional[str] = None, ttl: float = DEFAULT_TTL,
               payload: Optional[dict] = None) -> Pending:
        self._pending = Pending(kind=kind, action=action, device=device,
                                until=time.monotonic() + ttl,
                                payload=dict(payload or {}))
        return self._pending

    @property
    def pending(self) -> Optional[Pending]:
        """Активное ожидание или None (просроченное сбрасывается)."""
        self._expire()
        return self._pending

    def cancel(self) -> None:
        self._pending = None

    def _expire(self) -> None:
        p = self._pending
        if p is not None and p.until and time.monotonic() > p.until:
            if p.kind == "confirm":
                log.info(f"[confirm] истекло: action={p.action or 'unknown'}")
            self._pending = None

    # — разрешение короткого ответа —
    def resolve(self, text: str, *, source: str | None = None) -> Optional[tuple[str, str, Pending]]:
        """Если ждём ответа, разрешить ожидание.

        Для kind="confirm"/"plan": проверяет check_confirmation (да/нет).
        Для kind="clarify": любой ответ принимается как значение параметра.

        Возвращает (kind, verdict_or_value, pending) или None.
        """
        self._expire()
        p = self._pending
        if p is None:
            return None

        if p.kind == "clarify":
            # Любой ответ — значение параметра
            self._pending = None
            return p.kind, text.strip(), p

        verdict = check_confirmation(text)
        if p.kind == "confirm":
            if verdict is None:
                self._pending = None
                return None
            if (source != "telegram"
                    and (source is None or p.device is None or source != p.device)):
                return p.kind, "wrong_source", p
            self._pending = None
            return p.kind, verdict, p

        if verdict is None:
            self._pending = None
            return p.kind, "deny", p
        self._pending = None
        return p.kind, verdict, p
