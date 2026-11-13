"""
modules/intimacy_mode.py — режим интимного общения (18+), v2.

Режим живёт ТОЛЬКО в оперативной памяти: ни файлов, ни БД. Перезапуск —
выключен. Инициатор — только Мастер, и только в своём канале:

    voice       — голос с мастер-устройства
    tg_private  — личный чат Мастера в Telegram

Режим, включённый в одном канале, не действует в другом. Общий чат и
гости режим не включают и не видят (I1).

Детектор (I2):
  • ручная команда («режим 18+», «интимный режим») — включает;
  • сильный маркер — включает;
  • слабые маркеры — включают только при двух разных в одном сообщении
    (или продлевают уже включённый режим);
  • нейтральный текст продлевает включённый режим ненадолго и не дальше
    CONTINUATION_CAP от последнего маркера: ложное срабатывание не может
    держать режим бесконечно.

Барьер памяти (I3): is_intimate_content — сильный маркер или два слабых.

В журнал — только канал и причина, никогда текст сообщения (I4).
"""

from __future__ import annotations

import logging
import re
import time as _time

log = logging.getLogger("sakura.intimacy")

CHANNELS: tuple[str, ...] = ("voice", "text", "tg_private", "telegram", "desktop")

def _normalize_channel(channel: str | None) -> str:
    if not channel:
        return ""
    ch = str(channel).lower().strip()
    if ch in ("telegram", "tg"):
        return "tg_private"
    if ch in ("desktop", "chat"):
        return "text"
    return ch

TTL_SECONDS = 900              # 15 мин после маркера
CONTINUATION_TTL = 300         # нейтральная реплика продлевает на 5 мин…
CONTINUATION_CAP = 1800        # …но не дальше 30 мин от последнего маркера

# channel → (active_until, last_marker_at); monotonic
_state: dict[str, tuple[float, float]] = {}

# Флаг для ночной рефлексии: был ли режим хоть в одном канале
_was_active_since_reflection: bool = False


# ── Словари ──────────────────────────────────────────────────────────
# Каждая запись — регулярное выражение для основы слова; левая граница
# слова обязательна, правая — нет (ловим словоформы).

_STRONG = [
    r"секс(?!изм|ист)", r"интим", r"эротик", r"эротичн", r"порно", r"хентай",
    r"трахн", r"трахат", r"трахал", r"трахать", r"потрахат",
    r"переспат", r"минет", r"куни\b", r"куннилингус", r"дроч", r"мастурб", r"оргазм", r"orgasm",
    r"вагин", r"пенис", r"клитор", r"эрекци", r"нюдс", r"скинуть нюд",
    r"без трусов",
    r"сиськ", r"сисек", r"сосо[кч]", r"шлюшк",
    r"попк[ауеи]", r"отсос", r"шлепни", r"оттрах",
    r"(?:нарисуй|покажи|изобрази|хочу|трогай|ласкай|целуй|поцелуй)\s+.*(?:груд|сос[ока]|сиськ|попк|жоп|поп[уе]|тело|трусик|ножки)",
    r"(?:эротическ|пошл|интимн|сексуальн)\w*\s+(?:рисунок|арт|картинк|поза|вид|фантази)",
    r"снима[юея]\s+(?:с\s+себя\s+)?(?:всё|все|одежду|белье|трусики|лифчик)",
    r"раздева(?:юсь|ется|ем|й|йся)",
    r"сними\s+(?:с\s+себя\s+)?(?:всё|все|одежду|белье|трусики|лифчик)",
]

_WEAK = [
    r"18\+", r"18 плюс", r"для взрослых",
    r"постел", r"в кровати",
    r"нагот", r"обнаж", r"голая", r"голый", r"голенькая", r"раздет", r"раздева",
    r"снять одежду", r"без одежды",
    r"возбужд", r"страст", r"похот", r"влечени", r"фантази",
    r"грудь", r"груди", r"сосок", r"соски", r"попк", r"задниц",
    r"ебать", r"ебал", r"ебёт", r"ебет", r"выебат", r"ебш",
    r"поцелу", r"целуй", r"ласкать", r"ласкай", r"ласки\b",
]

_STOP_PHRASES = [
    "хватит", "стоп", "смени тему", "переключись", "другая тема",
    "хватит об этом", "выключи режим", "отключи режим", "обычный режим",
    "приват офф",
]

_MANUAL_ACTIVATE = [
    "режим 18+", "18+ режим", "включи режим 18", "интим режим",
    "интимный режим", "приватный режим", "включи приват", "начни приват",
    "режим 18", "18 плюс", "интим", "эротика",
]

_STRONG_RX = [re.compile(rf"(?<!\w){p}", re.IGNORECASE) for p in _STRONG]
_WEAK_RX = [re.compile(rf"(?<!\w){p}", re.IGNORECASE) for p in _WEAK]
_STOP_RX = [re.compile(rf"(?<!\w){re.escape(s)}(?!\w)", re.IGNORECASE) for s in _STOP_PHRASES]
_MANUAL_RX = [re.compile(rf"(?<!\w){re.escape(m)}(?![\w+])", re.IGNORECASE) for m in _MANUAL_ACTIVATE]


# ── Классификация текста ─────────────────────────────────────────────

def _strong_hits(text: str) -> int:
    return sum(1 for rx in _STRONG_RX if rx.search(text))


def _weak_hits(text: str) -> int:
    return sum(1 for rx in _WEAK_RX if rx.search(text))


def _is_manual_activate(text: str) -> bool:
    tl = (text or "").lower().strip().rstrip(".!?,;:")
    if tl in ("грудь", "сиськи", "попка", "18+", "интим", "эротика", "нюдс"):
        return True
    return any(rx.search(tl) for rx in _MANUAL_RX)


def _is_stop(text: str) -> bool:
    return any(rx.search(text or "") for rx in _STOP_RX)


def classify(text: str) -> str:
    """'manual' | 'strong' | 'weak2' | 'weak1' | 'none' — без побочных эффектов."""
    text = text or ""
    if _is_manual_activate(text):
        return "manual"
    if _strong_hits(text):
        return "strong"
    weak = _weak_hits(text)
    if weak >= 2:
        return "weak2"
    if weak == 1:
        return "weak1"
    return "none"


def is_intimate_content(text: str) -> bool:
    """Барьер памяти: сильный маркер, ручная команда или два слабых маркера.

    Используется при извлечении фактов — даже при промахе детектора режима
    интимное не попадает в долговременную память, а обычные факты
    («давнее желание», «болит грудь») — попадают.
    """
    return classify(text) in ("manual", "strong", "weak2")


# ── Состояние ────────────────────────────────────────────────────────

def _check_channel(channel: str) -> str:
    norm = _normalize_channel(channel)
    if norm not in ("voice", "text", "tg_private"):
        raise ValueError(f"режим 18+ не работает в канале {channel!r}")
    return norm


def _activate(channel: str, now: float, reason: str) -> None:
    global _was_active_since_reflection
    was = is_active(channel)
    _state[channel] = (now + TTL_SECONDS, now)
    _was_active_since_reflection = True
    log.info("[intimacy] %s channel=%s reason=%s", "extended" if was else "on", channel, reason)


def _off(channel: str, reason: str) -> None:
    if is_active(channel):
        log.info("[intimacy] off channel=%s reason=%s", channel, reason)
    _state.pop(channel, None)


def mark(text: str, channel: str) -> None:
    """Вызывается на КАЖДОЕ сообщение Мастера в его канале.

    Порядок: стоп → ручная команда → сильный → два слабых → продление.
    """
    _check_channel(channel)
    now = _time.monotonic()

    if _is_stop(text):
        _off(channel, "stop")
        return

    kind = classify(text)
    if kind in ("manual", "strong", "weak2"):
        _activate(channel, now, kind)
        return

    if not is_active(channel):
        return

    until, last_marker = _state[channel]
    if kind == "weak1":
        _activate(channel, now, "weak1")
        return
    # Нейтральная реплика внутри режима: короткое продление с потолком.
    new_until = min(max(until, now + CONTINUATION_TTL), last_marker + CONTINUATION_CAP)
    if new_until > until:
        _state[channel] = (new_until, last_marker)


def is_active(channel: str | None = None) -> bool:
    """Активен ли режим. channel=None — в любом канале (для барьеров памяти)."""
    now = _time.monotonic()
    if channel is None:
        return any(now < until for until, _ in _state.values())
    ch = _normalize_channel(channel)
    st = _state.get(ch)
    return bool(st and now < st[0])


def active_channels() -> tuple[str, ...]:
    return tuple(c for c in ("voice", "text", "tg_private") if is_active(c))


def deactivate(channel: str | None = None) -> None:
    """Явное выключение: в одном канале или во всех."""
    for c in ([channel] if channel else list(_state)):
        _off(c, "explicit")


def consume_check() -> bool:
    """Был ли режим со времени последней рефлексии. НЕ сбрасывает флаг."""
    return _was_active_since_reflection


def reset_reflection_flag() -> None:
    """Сбрасывает флаг после завершения ночной рефлексии."""
    global _was_active_since_reflection
    _was_active_since_reflection = False


def _reset_state() -> None:
    """Сброс всего состояния (только для тестов)."""
    global _was_active_since_reflection
    _state.clear()
    _was_active_since_reflection = False


def redact(text: str, channel: str | None) -> str:
    """Для журнала: в активном режиме канала (или для интимного текста) —
    только длина. Текст реплик 18+ не попадает в логи сервера."""
    text = text or ""
    if (channel and channel in CHANNELS and is_active(channel)) or is_intimate_content(text):
        return f"<скрыто: {len(text)} симв.>"
    return repr(text)
