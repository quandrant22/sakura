"""Быстрые голосовые подтверждения команд агента — без LLM.

Фразы редактируются только здесь. Голосовой ход, отправивший агенту
команду с followup=ack, «вооружает» подтверждение по cmd_id (arm). Звучит
оно по command_result (on_result): успех — фраза категории действия,
ошибка — причина из detail. Нет результата за ACK_PENDING_S — один раз
«Выполняю.». Ход закрывает tts_end самой фразы (tts_cache.play), поэтому
голосовой обработчик свой tts_end в этом ходе не шлёт (closes_turn).

Ждать command_result внутри голосового хода нельзя: обработчики сокета
вызываются последовательно, и ответ агента пришёл бы только после хода.
"""

from __future__ import annotations

import asyncio
import logging
import random
import time
from dataclasses import dataclass, field

import config

log = logging.getLogger(__name__)

PHRASES: dict[str, list[str]] = {
    "default":  ["Готово.", "Сделано.", "Выполнено.", "Принято.", "Есть.", "Сделала."],
    "volume":   ["Громкость {n}.", "Сделала."],
    "open_app": ["Открываю.", "{app} запущен."],
    "music":    ["Включаю.", "Готово."],
}
WIT = ["Как пожелаете.", "Уже сделано."]
ERROR_REASON = "Не получилось: {reason}."
ERROR_NO_REASON = "Не получилось."
ERROR_DEVICE = "Устройство недоступно."
PENDING = "Выполняю."

CATEGORY: dict[str, str] = {
    "system.volume": "volume",
    "music.volume_up": "volume",
    "music.volume_down": "volume",
    "music.mute": "volume",
    "app.switch": "open_app",
    "app.switch_open": "open_app",
    "music.play_pause": "music",
    "music.next": "music",
    "music.prev": "music",
}

_DEVICE_ERR = ("оффлайн", "недоступ", "offline", "not connected", "нет подключения")
# Агент иногда шлёт ok=True с текстом ошибки (запасной путь execute_command) —
# те же маркеры, что сервер применяет к старым ответам без ok.
_DETAIL_ERR = ("ошибка", "не нашла", "не найдено", "app_not_found", "оффлайн")
_REASON_MAX = 60

# Последняя произнесённая фраза по устройству — подряд не повторяем.
_last: dict[str, str] = {}


def category_for(action: str, param: str | None = None) -> str:
    # open.app: «включи музыку» (без параметра или про музыку) — music,
    # иначе запуск приложения.
    if action == "open.app":
        p = (param or "").strip().lower()
        return "music" if not p or "музык" in p else "open_app"
    return CATEGORY.get(action or "", "default")


def _fill(template: str, values: dict) -> str | None:
    try:
        return template.format(**values)
    except (KeyError, IndexError):
        return None


def choose(action: str, device: str, param: str | None = None,
           rng: random.Random | None = None) -> str:
    """Фраза подтверждения для действия; подряд одна и та же не звучит."""
    rng = rng or random
    values = {}
    if param:
        values = {"app": param}
        # Число — только у абсолютной громкости: у volume_up/down/mute
        # параметр (если есть) — шаг, «Громкость 20.» соврала бы.
        if action == "system.volume":
            values["n"] = param
    if rng.random() < config.ACK_WIT_PROB:
        pool = list(WIT)
    else:
        pool = [t for t in (_fill(p, values) for p in PHRASES[category_for(action, param)]) if t]
        if not pool:
            pool = list(PHRASES["default"])
    fresh = [p for p in pool if p != _last.get(device)]
    phrase = rng.choice(fresh or pool)
    _last[device] = phrase
    return phrase


def detail_is_error(detail: str | None) -> bool:
    return any(t in (detail or "").lower() for t in _DETAIL_ERR)


def error_phrase(detail: str | None) -> str:
    reason = (detail or "").strip().rstrip(".")
    if reason.startswith("app_not_found:"):
        reason = f"не нашла {reason.split(':', 1)[1].strip()}"
    if any(t in reason.lower() for t in _DEVICE_ERR):
        return ERROR_DEVICE
    if not reason:
        return ERROR_NO_REASON
    if len(reason) > _REASON_MAX:
        reason = reason[:_REASON_MAX].rsplit(" ", 1)[0]
    return ERROR_REASON.format(reason=reason)


def fixed_phrases() -> list[str]:
    """Фразы без переменной части — их предсинтезирует прогрев при старте."""
    out: list[str] = []
    for p in [*sum(PHRASES.values(), []), *WIT, ERROR_NO_REASON, ERROR_DEVICE, PENDING]:
        if "{" not in p and p not in out:
            out.append(p)
    return out


# ── ожидание command_result ─────────────────────────────────────────


@dataclass
class _Pending:
    ws: object
    device_id: str
    action: str
    param: str | None
    armed_at: float = field(default_factory=time.monotonic)
    timer: asyncio.Task | None = None
    pending_said: bool = False     # «Выполняю.» уже прозвучало
    speaking: bool = False         # таймер сейчас озвучивает «Выполняю.»


_pending: dict[str, _Pending] = {}
_armed_at: dict[str, float] = {}          # device_id → время последнего arm
_speak_locks: dict[str, asyncio.Lock] = {}
# После «Выполняю.» ждём результат ещё столько (ошибку скажем, успех — молча).
RESULT_TTL_S = 30.0


def arm(cmd_id: str | None, *, ws, device_id: str, action: str,
        param: str | None = None) -> bool:
    """Ход отправил агенту команду: подтверждение прозвучит по command_result."""
    if not config.ACKS_ENABLED or not cmd_id or ws is None:
        return False
    from sakura_core.registry import followup_for
    if followup_for(action) != "ack":
        return False
    p = _Pending(ws=ws, device_id=device_id, action=action, param=param)
    _pending[cmd_id] = p
    _armed_at[device_id] = p.armed_at
    p.timer = asyncio.get_running_loop().create_task(
        _pending_timer(cmd_id), name=f"ack-timer-{cmd_id}")
    log.info(f"[ack] ждём command_result: cmd={cmd_id} action={action} device={device_id}")
    return True


def closes_turn(device_id: str, since: float) -> bool:
    """Ход закроет фраза подтверждения (а не голосовой обработчик)."""
    return _armed_at.get(device_id, 0.0) >= since


async def _say(p: _Pending, phrase: str, t_ref: float | None = None) -> str:
    from modules import tts_cache
    lock = _speak_locks.setdefault(p.device_id, asyncio.Lock())
    async with lock:
        return await tts_cache.play(phrase, p.ws, p.device_id, t_ref=t_ref)


async def _pending_timer(cmd_id: str) -> None:
    await asyncio.sleep(config.ACK_PENDING_S)
    p = _pending.get(cmd_id)
    if p is None:
        return
    p.speaking = True
    try:
        log.info(f"[ack] cmd={cmd_id}: нет command_result за "
                 f"{config.ACK_PENDING_S:.1f}с → {PENDING!r}")
        await _say(p, PENDING)
        p.pending_said = True
    finally:
        p.speaking = False
    await asyncio.sleep(RESULT_TTL_S)
    _pending.pop(cmd_id, None)


async def on_result(cmd_id: str | None, ok: bool, detail: str | None = "") -> bool:
    """command_result по вооружённой команде: сказать подтверждение или ошибку.

    False — команда не ждала подтверждения (не голос, followup=llm, выключено)."""
    t_result = time.monotonic()
    p = _pending.pop(cmd_id, None) if cmd_id else None
    if p is None:
        return False
    if p.timer is not None and not p.speaking and not p.timer.done():
        p.timer.cancel()
    if ok:
        if p.pending_said or p.speaking:
            log.info(f"[ack] cmd={cmd_id}: успех после «Выполняю.» — молча")
            return True
        phrase = choose(p.action, p.device_id, p.param)
    else:
        phrase = error_phrase(detail)
    source = await _say(p, phrase, t_ref=t_result)
    log.info(f"[ack] cmd={cmd_id} action={p.action} ok={ok} → {phrase!r} ({source}), "
             f"от arm до result {(t_result - p.armed_at) * 1000:.0f}мс")
    return True
