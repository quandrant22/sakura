"""Состояние диалога (этап 2) — один объект вместо словарей modules/state.py
(_pending_system / _pending_plan / _pending_clarify) и глобального флага forget.

Поля ожидания: что ждём, от какого устройства, до какого времени, исходное
действие. Логика подтверждения не изобретается: check_confirmation перенесена
как есть из modules/state.py:85 (границы слов, приоритет отрицания, 15 тестов).
"""

from __future__ import annotations

import re as _re
import time
from dataclasses import dataclass, field
from typing import Optional

# ── check_confirmation: перенесено как есть из modules/state.py ──────────

_PS_CONFIRM_WORDS = (
    "да", "давай", "подтверждаю", "подтверждай", "выключай",
    "выключи", "точно", "конечно", "ага", "угу", "ок", "окей",
    "валяй", "действуй", "подтвердить",
)

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

    tl = text.lower().strip().rstrip(".!?,")

    # 1. Сначала проверяем отрицательные фразы (приоритет!)
    for phrase in _PS_DENY_PHRASES:
        if _re.search(rf"(?<!\w){_re.escape(phrase)}(?!\w)", tl):
            return "deny"

    # 2. Проверяем слова отрицания
    for word in _PS_DENY_WORDS:
        if _re.search(rf"(?<!\w){_re.escape(word)}(?!\w)", tl):
            return "deny"

    # 3. Проверяем слова подтверждения
    for word in _PS_CONFIRM_WORDS:
        if _re.search(rf"(?<!\w){_re.escape(word)}(?!\w)", tl):
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
            self._pending = None

    # — разрешение короткого ответа —
    def resolve(self, text: str) -> Optional[tuple[str, str, Pending]]:
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
        if verdict is None:
            self._pending = None
            return p.kind, "deny", p
        self._pending = None
        return p.kind, verdict, p
