"""
modules/intimacy_mode.py — Режим интимного общения (18+).

Режим живёт ТОЛЬКО в оперативной памяти. Никаких файлов, никакой БД.
Перезапуск = выключен. Инициатор — только Мастер.
"""

import logging
import re
import time as _time

log = logging.getLogger("sakura.intimacy")

_active_until: float = 0.0
TTL_SECONDS = 900  # 15 минут с последнего триггера

# Флаги для ночной рефлексии
_was_active_since_reflection: bool = False

# ── Триггеры ─────────────────────────────────────────────────────────
_TRIGGERS = [
    "секс", "трахн", "ебать", "ебш", "ебёт", "ебал",
    "минет", "дроч", "порно", "голая", "голый", "обнажён",
    "интим", "интимн", "сексуальн", "эротичн",
    "orgasm", "оргазм", "выебать", "вагин", "член",
    "грудь", "попка", "попк", "задн", "перд",
    "лесб", "гей секс", "трах",
    "снять одежду", "раздевайся", "раздеваться",
]

_STOP_PHRASES = [
    "хватит", "стоп", "смени тему", "переключись",
    "другая тема", "хватит об этом",
]

# Сборка regex-паттерна по границам слов (как в user_commands.match)
_TRIGGER_PATTERNS = [re.compile(rf"(?<!\w){re.escape(t)}(?!\w)", re.IGNORECASE) for t in _TRIGGERS]
_STOP_PATTERNS = [re.compile(rf"(?<!\w){re.escape(s)}(?!\w)", re.IGNORECASE) for s in _STOP_PHRASES]


def mark(text: str) -> None:
    """Вызывается на КАЖДОЕ сообщение Мастера. Определяет активность режима."""
    global _active_until, _was_active_since_reflection

    # Явные команды выключения
    for pat in _STOP_PATTERNS:
        if pat.search(text):
            if is_active():
                log.info("[intimacy] mode off (explicit stop)")
            _active_until = 0.0
            return

    # Детектор триггеров
    now = _time.monotonic()
    for pat in _TRIGGER_PATTERNS:
        if pat.search(text):
            _active_until = now + TTL_SECONDS
            _was_active_since_reflection = True
            log.info("[intimacy] mode on")
            return


def is_active() -> bool:
    """Режим активен и не истёк по TTL."""
    return _time.monotonic() < _active_until


def deactivate() -> None:
    """Явное выключение."""
    global _active_until
    if is_active():
        log.info("[intimacy] mode off (explicit)")
    _active_until = 0.0


def consume_check() -> bool:
    """Проверяет был ли режим со времени последней рефлексии. НЕ сбрасывает флаг."""
    return _was_active_since_reflection


def reset_reflection_flag() -> None:
    """Сбрасывает флаг после завершения ночной рефлексии."""
    global _was_active_since_reflection
    _was_active_since_reflection = False
