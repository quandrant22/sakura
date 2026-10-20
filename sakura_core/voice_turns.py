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
import time
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
    # Хронометраж (sakura_core.turn_timing): мс от приёма до этапов.
    t_recv: float = field(default_factory=time.monotonic)
    marks: dict[str, float] = field(default_factory=dict)
    kind: str = "other"         # conversation | command | other
    flags: list[str] = field(default_factory=list)
    reported: bool = False
    # Сторож зависшего хода: момент последнего исходящего сообщения хода.
    last_activity: float = field(default_factory=time.monotonic)
    # Журнал чата (sakura_core.chat_hooks): канал запроса, id записи
    # Мастера (reply_to ответа), сказанное за ход — одной записью в конце.
    channel: str = "voice"
    user_msg_id: int | None = None
    spoken: list[str] = field(default_factory=list)
    log: bool = True


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
        t.last_activity = time.monotonic()
    return payload


def is_cancelled() -> bool:
    """Текущий ход вытеснен: его аудио и текст больше не отправляются."""
    t = _current.get()
    return t is not None and t.cancelled


def mark_ended() -> None:
    t = _current.get()
    if t is not None:
        t.ended = True
        from sakura_core import turn_timing
        turn_timing.mark("tts_end", t)
        turn_timing.maybe_report(t)


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


# Виды ответов в reply.kind (feat/reply-kinds):
#   llm       — ответ модели (потоковый голосовой, по command_result, LLM-фразы)
#   ack       — подтверждение команды («Готово.», «Громкость 70.», «Выполняю.»)
#   template  — готовые и кэшированные фразы, ответы реестра
#   error     — «Не получилось: <detail>»
#   proactive — напоминания, брифинги, уведомления (всем master-устройствам)
REPLY_KINDS = ("llm", "ack", "template", "error", "proactive")


async def send_reply(websocket, device_id: str, text: str, kind: str = "llm") -> bool:
    """Текст ответа устройству (type=reply): {text, kind, turn_id, ts}.

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
    if kind not in REPLY_KINDS:
        log.warning(f"[turn] reply: неизвестный kind={kind!r} — template")
        kind = "template"
    import json
    try:
        await websocket.send(json.dumps(tag({
            "type": "reply", "device_id": device_id, "text": text,
            "kind": kind, "ts": round(time.time(), 3),
        })))
    except Exception as e:
        log.debug(f"[turn] reply не отправлен: {type(e).__name__}: {e}")
        return False
    return True


async def broadcast_reply(text: str, kind: str = "proactive") -> int:
    """reply всем подключённым master-устройствам (проактивные сообщения).
    Возвращает, скольким ушло."""
    from modules.state import connected_devices
    if kind == "proactive":
        from modules.presence_sync import pc_voice_allowed
        if not pc_voice_allowed():
            log.info("[turn] Мастер не у ПК — проактив не шлю на ПК (только Telegram)")
            return 0
    sent = 0
    for dev, ws in list(connected_devices.items()):
        if await send_reply(ws, dev, text, kind):
            sent += 1
    return sent


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
    # Закрываем от старых к новым — клиент видит tts_end в порядке ходов.
    for t in reversed(list(_chain(prev))):
        if not t.ended:
            await _send_end_for(t)
    for t in list(_chain(prev)):
        t.prev = None           # цепочку дальше не держим


TIMEOUT_REPLY = "Не получилось ответить, повтори."
WATCH_POLL_S = 1.0          # как часто сторож проверяет ход


def _timeout_due(turn: Turn, now: float) -> bool:
    """Ход завис: дольше TURN_TIMEOUT_S без завершения. Пока звук ещё
    идёт (сообщения хода моложе TURN_ACTIVE_GRACE_S) — длинный ответ, не
    зависание; но не дольше TURN_TIMEOUT_MAX_S от приёма."""
    import config
    age = now - turn.t_recv
    if age < config.TURN_TIMEOUT_S:
        return False
    if age >= config.TURN_TIMEOUT_MAX_S:
        return True
    return now - turn.last_activity >= config.TURN_ACTIVE_GRACE_S


async def _watched(turn: Turn, factory: Callable[[], Awaitable[None]]) -> None:
    """Обработчик хода под сторожем: завис — «Не получилось ответить,
    повтори» (reply kind=error), задача снята, клиенту tts_end."""
    import config
    if config.TURN_TIMEOUT_S <= 0:
        await factory()
        return
    child = asyncio.ensure_future(factory())
    try:
        while True:
            done, _ = await asyncio.wait({child}, timeout=WATCH_POLL_S)
            if done:
                child.result()          # исключение обработчика — наружу
                return
            if _timeout_due(turn, time.monotonic()):
                break
    except asyncio.CancelledError:
        # Ход вытеснен: обработчик снимается и дорабатывает свой finally
        # (tts_end хода) до того, как вытесняющий ход начнёт говорить.
        child.cancel()
        await asyncio.wait({child}, timeout=CANCEL_WAIT_S)
        raise
    age = time.monotonic() - turn.t_recv
    log.warning(f"[turn] {turn.device_id}: ход {turn.turn_id} завис ({age:.0f}с) — "
                f"«{TIMEOUT_REPLY}»")
    from sakura_core import turn_timing
    turn_timing.flag("timeout", turn)
    # Сначала текст (ход ещё не вытеснен — reply уходит), потом снять задачу:
    # её finally закроет ход tts_end; не закрыл — закрываем сами.
    await send_reply(turn.ws, turn.device_id, TIMEOUT_REPLY, kind="error")
    child.cancel()
    await asyncio.wait({child}, timeout=CANCEL_WAIT_S)
    turn.cancelled = True           # запоздавшее аудио зависшего хода — не уходит
    if not turn.ended:
        await _send_end_for(turn)


async def _run(turn: Turn, factory: Callable[[], Awaitable[None]]) -> None:
    try:
        if turn.prev is not None:
            await _supersede(turn.prev)
        _current.set(turn)
        log.info(f"[turn] {turn.device_id}: ход {turn.turn_id} начат")
        await _watched(turn, factory)
    except asyncio.CancelledError:
        log.info(f"[turn] {turn.device_id}: ход {turn.turn_id} отменён")
        raise
    except Exception as e:
        log.error(f"[turn] {turn.device_id}: ход {turn.turn_id}: {type(e).__name__}: {e}")
    finally:
        turn.done = True
        from sakura_core import turn_timing
        turn_timing.on_done(turn)
        try:
            from sakura_core.chat_hooks import on_turn_done
            await on_turn_done(turn)
        except Exception as e:
            log.warning(f"[turn] журнал хода {turn.turn_id}: {type(e).__name__}: {e}")


def start(device_id: str, ws, factory: Callable[[], Awaitable[None]],
          *, turn_id: str | None = None) -> Turn:
    """Начать ход устройства задачей; предыдущий — вытесняется.

    Вызывается синхронно из цикла сокета: следующее сообщение того же
    устройства читается сразу, и новый ход может вытеснить этот."""
    turn = Turn(turn_id=turn_id or new_turn_id(), device_id=device_id, ws=ws,
                prev=_last.get(device_id))
    _last[device_id] = turn
    # Свой контекст: задача хода не наследует turn вызывающего.
    ctx = contextvars.copy_context()
    ctx.run(_current.set, None)
    turn.task = asyncio.get_running_loop().create_task(
        _run(turn, factory), name=f"voice-turn-{device_id}-{turn.turn_id}",
        context=ctx)
    return turn
