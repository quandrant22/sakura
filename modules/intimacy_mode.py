"""
modules/intimacy_mode.py — Режим интимного общения (18+).

Режим живёт ТОЛЬКО в оперативной памяти. Никаких файлов, никакой БД.
Перезапуск = выключен. Инициатор — только Мастер.

Слои защиты:
  1. mark() — детектор по триггерам + явная активация + продление по теме
  2. is_intimate_content() — фильтр памяти при извлечении фактов
"""

import logging
import re
import time as _time

log = logging.getLogger("sakura.intimacy")

_active_until: float = 0.0
TTL_SECONDS = 900  # 15 минут с последнего триггера/продления

# Флаги для ночной рефлексии
_was_active_since_reflection: bool = False

# ── Триггеры (широкий спектр) ───────────────────────────────────────
_TRIGGERS = [
    # Прямое обозначение темы
    "секс", "18+", "18 плюс", "взросл", "для взрослых",
    "интим", "приват", "между нами", "закрытая тема",
    # Эвфемизмы и разговорные
    "постель", "постельн", "в постели", "в кровати", "кровать",
    "нагота", "обнаж", "голая", "голый", "раздет", "раздевай",
    "раздеваться", "снять одежду", "без одежды",
    # Отношения и близость
    "сексуальн", "эротичн", "эротика", "похоть", "возбужден",
    "страсть", "страстн", "влечени", "желани", "хотелка",
    "хотелки", "фантази", "фантазир", "грязн", "похотно",
    # Медицинские/анатомические
    "орган", "генит", "половой", "вагин", "пенис",
    "грудь", "соски", "попка", "задниц",
    # Действия
    "трахн", "ебать", "ебш", "ебёт", "ебал", "выебать",
    "минет", "дроч", "мастурб", "оргазм", "orgasm",
    "лесб", "трах", "порно", "порнхаб", "хентай",
    # Разговорные/молодёжные
    "замутить", "потраха", "переспать", "сношени",
    "кекс", "сасай", "дропнуть", "скинуть нуд",
    "голенькая", "без одежды", "без трусов",
]

_STOP_PHRASES = [
    "хватит", "стоп", "смени тему", "переключись",
    "другая тема", "хватит об этом", "выключи режим",
    "отключи режим", "обычный режим", "приват офф",
]

# Явные команды включения (минуя детектор)
_MANUAL_ACTIVATE = [
    "включи режим", "приватный режим", "включи приват",
    "режим 18+", "18+ режим", "открой режим",
    "переключи режим", "между нами режим",
    "начни приват", "давай без фильтров", "без ограничений",
    "сними ограничения", "отключи фильтры", "интим режим",
]

# Паттерны: левая граница \w, правой НЕТ — ловим основу в слове
_TRIGGER_PATTERNS = [re.compile(rf"(?<!\w){re.escape(t)}", re.IGNORECASE) for t in _TRIGGERS]
_STOP_PATTERNS = [re.compile(rf"(?<!\w){re.escape(s)}(?!\w)", re.IGNORECASE) for s in _STOP_PHRASES]
_MANUAL_PATTERNS = [re.compile(rf"(?<!\w){re.escape(m)}(?!\w)", re.IGNORECASE) for m in _MANUAL_ACTIVATE]


def _is_triggered(text: str) -> bool:
    """Проверяет текст на наличие интимных триггеров."""
    for pat in _TRIGGER_PATTERNS:
        if pat.search(text):
            return True
    return False


def _is_manual_activate(text: str) -> bool:
    """Проверяет, является ли текст явной командой включения."""
    tl = text.lower().strip().rstrip(".!?,;:")
    for pat in _MANUAL_PATTERNS:
        if pat.search(tl):
            return True
    return False


def _is_stop(text: str) -> bool:
    """Проверяет, является ли текст командой выключения."""
    for pat in _STOP_PATTERNS:
        if pat.search(text):
            return True
    return False


def mark(text: str) -> None:
    """Вызывается на КАЖДОЕ сообщение Мастера. Определяет активность режима.

    Порядок:
      1. Явные команды выключения
      2. Явная активация по команде (минуя детектор)
      3. Детектор триггеров
      4. Продление по теме (если уже активен — продлить даже без явного триггера)
    """
    global _active_until, _was_active_since_reflection

    # 1. Явные команды выключения
    if _is_stop(text):
        if is_active():
            log.info("[intimacy] mode off (explicit stop)")
        _active_until = 0.0
        return

    # 2. Явная активация по команде
    if _is_manual_activate(text):
        now = _time.monotonic()
        was_already_active = is_active()
        _active_until = now + TTL_SECONDS
        _was_active_since_reflection = True
        if was_already_active:
            log.info("[intimacy] mode extended (manual)")
        else:
            log.info("[intimacy] mode on (manual)")
        return

    # 3. Детектор триггеров
    if _is_triggered(text):
        now = _time.monotonic()
        _active_until = now + TTL_SECONDS
        _was_active_since_reflection = True
        log.info("[intimacy] mode on (trigger)")
        return

    # 4. Продление по теме (если режим уже активен)
    if is_active():
        _active_until = _time.monotonic() + TTL_SECONDS
        log.info("[intimacy] mode extended (topic continuation)")


def is_active() -> bool:
    """Режим активен и не истёк по TTL."""
    return _time.monotonic() < _active_until


def is_intimate_content(text: str) -> bool:
    """Второй барьер: проверяет, содержит ли текст интимный контент.

    Используется при извлечении фактов для памяти — чтобы даже при промахе
    детектора интимный контент не попадал в долговременную память.
    """
    return _is_triggered(text) or _is_manual_activate(text)


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


# ── Для тестов: сброс состояния ─────────────────────────────────────
def _reset_state() -> None:
    """Сброс всего состояния (только для тестов)."""
    global _active_until, _was_active_since_reflection
    _active_until = 0.0
    _was_active_since_reflection = False
