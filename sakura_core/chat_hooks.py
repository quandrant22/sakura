"""Точки записи журнала чата (modules/chat_log) и пуш chat_message.

Пишется только то, что касается Мастера (master-устройства, личный чат
Мастера в Telegram):

  * голос и текст из окна — запрос (расшифровка) в начале хода, ответ
    Сакуры одной записью по завершении хода (voice_turns.Turn.spoken);
  * Telegram — входящие Мастера (медиа — заглушкой) и исходящие в его
    чат: ответ на сообщение — channel=telegram (reply_to), без входящего
    — channel=proactive. Внутри голосового хода исходящие в Telegram не
    пишутся — ход пишет себя сам;
  * подтверждения («Готово.», «Выполняю.») — только при CHAT_LOG_ACKS=1;
  * «не записывай» / «запись» — пауза и возобновление записи.

Любая ошибка журнала логируется и проглатывается: ответ Мастеру журнал
не ломает.
"""

from __future__ import annotations

import asyncio
import contextvars
import logging
import re

import config
from modules import chat_log
from sakura_core import voice_turns
from sakura_core.tasks import spawn

log = logging.getLogger(__name__)

# ── пауза записи ───────────────────────────────────────────────────

_PRIVACY_OFF = frozenset({
    "не записывай", "не записывай разговор", "не записывай чат",
    "не записывай это", "не записывай пока", "перестань записывать",
    "выключи запись", "останови запись", "пауза записи",
})
_PRIVACY_ON = frozenset({
    "запись", "записывай", "включи запись", "можно записывать",
    "снова записывай", "продолжай запись", "продолжай записывать",
})
PHRASE_PAUSED = "Хорошо, не записываю."
PHRASE_RESUMED = "Запись снова включена."
PHRASE_FORCED = "Запись выключена в настройках."


def _norm(text: str) -> str:
    t = (text or "").lower().replace("ё", "е")
    t = re.sub(r"[^\w\s]", " ", t)
    t = " ".join(t.split())
    for lead in ("сакура ", "пожалуйста "):
        if t.startswith(lead):
            t = t[len(lead):]
    return t


def privacy_command(text: str) -> str | None:
    """«off» — «не записывай», «on» — «запись»; иначе None. Только точная
    фраза: «не записывай это в календарь» командой не считается."""
    t = _norm(text)
    if t in _PRIVACY_OFF:
        return "off"
    if t in _PRIVACY_ON:
        return "on"
    return None


async def apply_privacy(text: str) -> str | None:
    """Команда паузы записи → фраза-ответ; не команда → None."""
    cmd = privacy_command(text)
    if cmd is None:
        return None
    try:
        await asyncio.to_thread(chat_log.set_paused, cmd == "off")
    except Exception as e:
        log.warning(f"[chat] пауза записи: {type(e).__name__}: {e}")
    log.info(f"[chat] запись журнала: {'пауза' if cmd == 'off' else 'включена'}")
    if cmd == "off":
        return PHRASE_PAUSED
    return PHRASE_FORCED if config.CHAT_LOG_PAUSED else PHRASE_RESUMED


# ── подтверждения ──────────────────────────────────────────────────

_EXTRA_ACKS = ("Готово, Мастер.",)


def _ack_patterns() -> list[re.Pattern]:
    from modules import acks
    phrases = [*sum(acks.PHRASES.values(), []), *acks.WIT, acks.PENDING, *_EXTRA_ACKS]
    out = []
    for p in phrases:
        rx = re.escape(p)
        rx = re.sub(r"\\\{\w+\\\}", r".{1,40}", rx)
        out.append(re.compile(rf"^{rx}$", re.IGNORECASE))
    return out


_ACKS: list[re.Pattern] | None = None


def is_ack(text: str | None) -> bool:
    """Короткое подтверждение команды («Готово.», «Громкость 70.»)."""
    global _ACKS
    if _ACKS is None:
        _ACKS = _ack_patterns()
    t = (text or "").strip()
    return bool(t) and any(p.match(t) for p in _ACKS)


# ── запись и пуш ───────────────────────────────────────────────────

def _is_master(device_id: str | None) -> bool:
    from modules.ws_auth import is_master_device
    return is_master_device(device_id)


async def record(role: str, channel: str, text: str, *, device: str | None = None,
                 client_msg_id: str | None = None, reply_to: int | None = None,
                 meta: dict | None = None, push: bool = True
                 ) -> tuple[dict | None, bool]:
    """Записать сообщение и разослать chat_message master-устройствам.

    (сообщение, created); пауза записи или ошибка — (None, False)."""
    if not (text or "").strip():
        return None, False
    try:
        if await asyncio.to_thread(chat_log.is_paused):
            return None, False
        msg, created = await asyncio.to_thread(
            chat_log.append, role, channel, text, device=device,
            client_msg_id=client_msg_id, reply_to=reply_to, meta=meta)
    except Exception as e:
        log.warning(f"[chat] запись не удалась ({role}/{channel}): {type(e).__name__}: {e}")
        return None, False
    if created and push:
        await push_message(msg)
    return msg, created


async def push_message(msg: dict) -> None:
    try:
        from sakura_core.proto_v2 import broadcast
        await broadcast({"type": "chat_message", "message": chat_log.to_wire(msg)})
    except Exception as e:
        log.debug(f"[chat] push chat_message: {type(e).__name__}: {e}")


# ── голосовой ход и текст из окна ──────────────────────────────────

async def on_voice_request(data: dict, speak) -> bool:
    """Начало хода (voice_command / chat_send): запрос — в журнал.

    speak(phrase) — озвучка ответа на команду паузы записи. True — это
    была команда паузы, ход на этом закончен."""
    turn = voice_turns.current()
    device = data.get("device_id") or "laptop"
    text = (data.get("text") or "").strip()
    if not _is_master(device):
        if turn is not None:
            turn.log = False
        return False
    phrase = await apply_privacy(text)
    if phrase is not None:
        if turn is not None:
            turn.log = False        # команда паузы и её ответ — не в журнал
        await speak(phrase)
        return True
    channel = "text" if data.get("channel") == "text" else "voice"
    if turn is not None:
        turn.channel = channel
    if data.get("_chat_msg_id") is not None:
        # chat_send: запрос уже записан до старта хода
        if turn is not None:
            turn.user_msg_id = data["_chat_msg_id"]
        return False
    if not text:
        return False
    msg, _ = await record("user", channel, text, device=device,
                          meta={"turn_id": voice_turns.current_id()})
    if msg is not None and turn is not None:
        turn.user_msg_id = msg["id"]
    return False


def note_spoken(text: str) -> None:
    """Сакура сказала text в текущем ходе: в журнал — по завершении хода
    (продолжение после хода — ответ на command_result — сразу)."""
    turn = voice_turns.current()
    if turn is None or not turn.log or turn.cancelled or not _is_master(turn.device_id):
        return
    if is_ack(text) and not config.CHAT_LOG_ACKS:
        return
    text = voice_turns.reply_text(text) if text else ""
    if not text:
        return
    if not turn.done:
        turn.spoken.append(text)
        return
    spawn(record("assistant", turn.channel, text, device=turn.device_id,
                 reply_to=turn.user_msg_id, meta={"turn_id": turn.turn_id}),
          name=f"chat-log-{turn.turn_id}")


async def on_turn_done(turn) -> None:
    """Ход завершён (или вытеснен): сказанное — одной записью."""
    if not turn.spoken or not turn.log or not _is_master(turn.device_id):
        return
    text = "\n".join(turn.spoken)
    turn.spoken = []
    meta = {"turn_id": turn.turn_id}
    if turn.cancelled:
        meta["interrupted"] = True
    await record("assistant", turn.channel, text, device=turn.device_id,
                 reply_to=turn.user_msg_id, meta=meta)


# ── Telegram ───────────────────────────────────────────────────────

TG_DEVICE = "telegram"
# Обработка входящего сообщения Мастера: {"reply_to": id} или {"skip": True}.
_tg_ctx: contextvars.ContextVar[dict | None] = contextvars.ContextVar(
    "chat_tg_ctx", default=None)

_IN_MEDIA = (("voice", "голосовое"), ("video_note", "кружок"), ("photo", "фото"),
             ("video", "видео"), ("animation", "GIF"), ("sticker", "стикер"),
             ("audio", "аудио"), ("document", "файл"), ("location", "геолокация"),
             ("contact", "контакт"))
_OUT_MEDIA = {"SendPhoto": "фото", "SendVideo": "видео", "SendVoice": "голосовое",
              "SendAudio": "аудио", "SendDocument": "файл", "SendAnimation": "GIF",
              "SendSticker": "стикер", "SendVideoNote": "кружок"}


def _media_text(kind: str, caption: str | None) -> str:
    caption = (caption or "").strip()
    return f"[{kind}] {caption}" if caption else f"[{kind}]"


def _incoming_text(message) -> tuple[str, str | None]:
    if getattr(message, "text", None):
        return message.text, None
    for attr, kind in _IN_MEDIA:
        if getattr(message, attr, None):
            return _media_text(kind, getattr(message, "caption", None)), kind
    return "", None


def _is_master_private(message) -> bool:
    try:
        from modules.users import is_master
        return (message.chat.type == "private" and message.from_user is not None
                and is_master(message.from_user.id))
    except Exception:
        return False


async def tg_incoming_middleware(handler, event, data):
    """Outer-middleware dp.message: входящие Мастера в личном чате."""
    if not _is_master_private(event):
        return await handler(event, data)
    text, media = _incoming_text(event)
    if text.startswith("/"):
        # Команды бота и их вывод — не разговор, в журнал не идут.
        tok = _tg_ctx.set({"skip": True})
        try:
            return await handler(event, data)
        finally:
            _tg_ctx.reset(tok)
    if media is None:
        phrase = await apply_privacy(text)
        if phrase is not None:
            tok = _tg_ctx.set({"skip": True})
            try:
                await event.answer(phrase)
            finally:
                _tg_ctx.reset(tok)
            return None
    msg = None
    if text:
        msg, _ = await record("user", "telegram", text, device=TG_DEVICE,
                              meta={"media": media} if media else None)
    tok = _tg_ctx.set({"reply_to": msg["id"] if msg else None})
    try:
        return await handler(event, data)
    finally:
        _tg_ctx.reset(tok)


async def on_tg_sent(method) -> None:
    """Исходящее сообщение бота ушло (session-middleware)."""
    from config import MASTER_ID
    if str(getattr(method, "chat_id", None)) != str(MASTER_ID):
        return
    name = type(method).__name__
    if name == "SendMessage":
        text, media = getattr(method, "text", "") or "", None
    elif name in _OUT_MEDIA:
        media = _OUT_MEDIA[name]
        text = _media_text(media, getattr(method, "caption", None))
    else:
        return
    ctx = _tg_ctx.get()
    if ctx is not None and ctx.get("skip"):
        return
    if voice_turns.current() is not None:
        return          # голосовой ход пишет себя сам
    if media is None and is_ack(text) and not config.CHAT_LOG_ACKS:
        return
    channel = "telegram" if ctx is not None else "proactive"
    await record("assistant", channel, text, device=TG_DEVICE,
                 reply_to=ctx.get("reply_to") if ctx else None,
                 meta={"media": media} if media else None)


def tg_session_middleware():
    """Middleware сессии бота: каждое исходящее — в on_tg_sent."""
    from aiogram.client.session.middlewares.base import BaseRequestMiddleware

    class _ChatLogMiddleware(BaseRequestMiddleware):
        async def __call__(self, make_request, bot, method):
            response = await make_request(bot, method)
            try:
                await on_tg_sent(method)
            except Exception as e:
                log.warning(f"[chat] исходящее Telegram: {type(e).__name__}: {e}")
            return response

    return _ChatLogMiddleware()
