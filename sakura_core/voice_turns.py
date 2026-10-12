"""Голосовые ходы: turn_id и «один поток озвучки на устройство».

Каждый голосовой запрос устройства — ход с turn_id (uuid4 hex[:12]).
turn_id лежит в ContextVar: его видят все отправщики хода — tts_chunk,
tts_end, reply, в том числе дочерние задачи (prefetch-стрим, стадии
синтеза, таймер подтверждения), — и добавляют необязательное поле
turn_id (старые клиенты лишние поля игнорируют).

Новый ход того же устройства, пока предыдущий не завершён, ОТМЕНЯЕТ
предыдущий до своего начала: задача хода снимается (вместе с ней стрим
LLM и предсинтез TTS), запоздавшие аудиопакеты отменённого хода
отбрасываются, клиент получает tts_end с turn_id старого хода. Два
хода одного устройства никогда не идут параллельно.
"""

from __future__ import annotations

import asyncio
import contextvars
import logging
import uuid
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field

log = logging.getLogger(__name__)

# Предел текста reply (символов).
REPLY_MAX_CHARS = 4000

# Сколько ждать, пока отменённый ход доберёт finally (закрытие стрима,
# предконнекта). Дольше — новый ход стартует всё равно: аудио старого
# к этому моменту уже отбрасывается (cancelled).
CANCEL_WAIT_S = 3.0


@dataclass
class Turn:
    turn_id: str
    device_id: str
    ws: object
    task: asyncio.Task | None = None
    cancelled: bool = False     # вытеснен новым ходом — аудио не уходит
    ended: bool = False         # tts_end этого хода уже ушёл
    done: bool = False          # обработчик хода завершился
    prev: Turn | None = field(default=None, repr=False)


_current: contextvars.ContextVar[Turn | None] = contextvars.ContextVar(
    "voice_turn", default=None)
# Последний ход устройства. Завершённый тоже: его поздние продолжения
# (подтверждение по command_result, ответ по результату музыки) несут
# его turn_id и отбрасываются, когда начался новый ход.
_last: dict[str, Turn] = {}


def new_turn_id() -> str:
    return uuid.uuid4().hex[:12]


def current() -> Turn | None:
    return _current.get()


def current_id() -> str | None:
    t = _current.get()
    return t.turn_id if t is not None else None


def active(device_id: str) -> Turn | None:
    """Незавершённый ход устройства (или None)."""
    t = _last.get(device_id)
    if t is None or t.done:
        return None
    return t


def tag(payload: dict) -> dict:
    """Добавить turn_id текущего хода (если он есть) в исходящее сообщение."""
    t = _current.get()
    if t is not None:
        payload["turn_id"] = t.turn_id
    return payload


def is_cancelled() -> bool:
    """Текущий ход вытеснен: его аудио и текст больше не отправляются."""
    t = _current.get()
    return t is not None and t.cancelled


def mark_ended() -> None:
    t = _current.get()
    if t is not None:
        t.ended = True


def use(turn: Turn | None) -> contextvars.Token:
    """Сделать turn текущим (продолжение хода вне его задачи: обработка
    command_result, подтверждение). Вернуть токен для reset()."""
    return _current.set(turn)


def reset(token: contextvars.Token) -> None:
    _current.reset(token)


def reply_text(text: str) -> str:
    """Текст ответа для окна: как ушёл в озвучку, без тегов [ТОН: …]."""
    from modules.tts_server import strip_tone
    text = strip_tone(text or "")[1].strip()
    return text[:REPLY_MAX_CHARS]


async def send_reply(websocket, device_id: str, text: str) -> bool:
    """Полный текст голосового ответа устройству-источнику (type=reply).

    Только master-устройствам; вытесненный ход текст не шлёт. Ошибка
    отправки не ломает ход. True — сообщение ушло."""
    if websocket is None or is_cancelled():
        return False
    from modules.ws_auth import is_master_device
    if not is_master_device(device_id):
        return False
    text = reply_text(text)
    if not text:
        return False
    import json
    try:
        await websocket.send(json.dumps(tag({
            "type": "reply", "device_id": device_id, "text": text,
        })))
    except Exception as e:
        log.debug(f"[turn] reply не отправлен: {type(e).__name__}: {e}")
        return False
    return True


async def _send_end_for(turn: Turn) -> None:
    from modules.tts_server import _send_end
    tok = _current.set(turn)
    try:
        await _send_end(turn.ws, turn.device_id)
    finally:
        _current.reset(tok)


def _chain(turn: Turn | None):
    while turn is not None:
        yield turn
        turn = turn.prev


async def _supersede(prev: Turn) -> None:
    """Вытеснить предыдущие ходы устройства и дождаться их завершения.

    Незавершённый ход отменяется (задача, стрим LLM, предсинтез TTS);
    завершённый, но не закрытый (ждёт подтверждения команды) — его
    поздняя озвучка отбрасывается. Каждому вытесненному незакрытому
    ходу — tts_end с его turn_id."""
    waiting = []
    for t in _chain(prev):
        if not t.cancelled and not t.ended:
            log.info(f"[turn] {t.device_id}: ход {t.turn_id} вытеснен — отмена")
        t.cancelled = True
        if t.task is not None and not t.task.done():
            t.task.cancel()
            waiting.append(t.task)
    if waiting:
        _, pending = await asyncio.wait(waiting, timeout=CANCEL_WAIT_S)
        if pending:
            log.warning(f"[turn] {prev.device_id}: {len(pending)} ход(а) не "
                        f"завершились за {CANCEL_WAIT_S:.0f}с — аудио отбрасывается")
    for t in _chain(prev):
        if not t.ended:
            await _send_end_for(t)
    for t in list(_chain(prev)):
        t.prev = None           # цепочку дальше не держим


async def _run(turn: Turn, factory: Callable[[], Awaitable[None]]) -> None:
    try:
        if turn.prev is not None:
            await _supersede(turn.prev)
        _current.set(turn)
        log.info(f"[turn] {turn.device_id}: ход {turn.turn_id} начат")
        await factory()
    except asyncio.CancelledError:
        log.info(f"[turn] {turn.device_id}: ход {turn.turn_id} отменён")
        raise
    except Exception as e:
        log.error(f"[turn] {turn.device_id}: ход {turn.turn_id}: {type(e).__name__}: {e}")
    finally:
        turn.done = True


def start(device_id: str, ws, factory: Callable[[], Awaitable[None]]) -> Turn:
    """Начать ход устройства задачей; предыдущий — вытесняется.

    Вызывается синхронно из цикла сокета: следующее сообщение того же
    устройства читается сразу, и новый ход может вытеснить этот."""
    turn = Turn(turn_id=new_turn_id(), device_id=device_id, ws=ws,
                prev=_last.get(device_id))
    _last[device_id] = turn
    # Свой контекст: задача хода не наследует turn вызывающего.
    ctx = contextvars.copy_context()
    ctx.run(_current.set, None)
    turn.task = asyncio.get_running_loop().create_task(
        _run(turn, factory), name=f"voice-turn-{device_id}-{turn.turn_id}",
        context=ctx)
    return turn
