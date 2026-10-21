"""Протокол v2, порция 1: журнал чата и история (PROTOCOL.md клиента §1.3–1.4).

  chat_send {text, client_msg_id}      → chat_ack {client_msg_id, id};
                                         текст обрабатывается как запрос из окна
  history_request {before_id | before_ts, limit ≤ 100}
                                       → history {messages, has_more}
  chat_read {last_read_id}             → chat_read {last_read_id}
  chat_search {q, limit}               → chat_search {q, messages}
  chat_delete {id}                     → chat_delete {id}
  chat_clear {confirm: true}           → chat_clear {deleted}
  пуш chat_message {message}           — каждому master-устройству с proto 2

Приватные классы: на не-secure соединении сюда не доходят (adapters/ws,
secure_policy); если модуля политики нет — отказ (docs/DECISIONS.md S9).
"""

from __future__ import annotations

import asyncio
import json
import logging

from modules import chat_log
from sakura_core import chat_hooks, proto_v2, voice_turns
from sakura_core.proto_v2 import V2Error

log = logging.getLogger(__name__)

TEXT_MAX = 4000
CLIENT_MSG_ID_MAX = 64


async def _send(ws, obj: dict) -> None:
    await ws.send(json.dumps(obj, ensure_ascii=False))


def _id_arg(data: dict, key: str, required: bool = True) -> int | None:
    value = data.get(key)
    if value is None and not required:
        return None
    msg_id = chat_log.parse_id(value)
    if msg_id is None:
        raise V2Error("bad_request", f"{key}: нужен id сообщения")
    return msg_id


def _limit(data: dict, default: int, maximum: int) -> int:
    value = data.get("limit", default)
    if value is None:
        return default
    if isinstance(value, bool) or not isinstance(value, (int, float, str)):
        raise V2Error("bad_request", "limit: нужно число")
    try:
        n = int(value)
    except ValueError:
        raise V2Error("bad_request", "limit: нужно число") from None
    if n < 1:
        raise V2Error("bad_request", "limit: от 1")
    return min(n, maximum)


async def _chat_send(websocket, data: dict, ctx: dict) -> None:
    device_id = data["device_id"]
    text = data.get("text")
    if not isinstance(text, str) or not text.strip():
        raise V2Error("bad_request", "text: пустое сообщение")
    text = text.strip()
    if len(text) > TEXT_MAX:
        raise V2Error("bad_request", f"text: длиннее {TEXT_MAX} символов")
    cmid = data.get("client_msg_id")
    if cmid is not None and (not isinstance(cmid, str) or not cmid
                             or len(cmid) > CLIENT_MSG_ID_MAX):
        raise V2Error("bad_request", "client_msg_id: строка до 64 символов")
    rid = data.get("request_id")

    phrase = await chat_hooks.apply_privacy(text)
    if phrase is not None:
        await _send(websocket, {"type": "chat_ack", "request_id": rid,
                                "client_msg_id": cmid, "id": None})
        await voice_turns.send_reply(websocket, device_id, phrase)
        return None

    turn_id = voice_turns.new_turn_id()
    msg, created = await chat_hooks.record(
        "user", "text", text, device=device_id, client_msg_id=cmid,
        meta={"turn_id": turn_id}, push=False)
    await _send(websocket, {"type": "chat_ack", "request_id": rid,
                            "client_msg_id": cmid,
                            "id": str(msg["id"]) if msg else None})
    if msg is not None and not created:
        log.info(f"[v2] chat_send повтор client_msg_id={cmid} → id={msg['id']}")
        return None             # уже обработан — ответ не дублируем
    if msg is not None:
        await chat_hooks.push_message(msg)

    from adapters.ws import handle_voice_command
    turn_data = {
        "type": "voice_command", "device_id": device_id, "text": text,
        "channel": "text", "active_window": data.get("active_window", ""),
        "context": [], "_chat_msg_id": msg["id"] if msg else None,
    }
    voice_turns.start(device_id, websocket,
                      lambda: handle_voice_command(websocket, turn_data, ctx),
                      turn_id=turn_id)
    return None


async def _history_request(websocket, data: dict, ctx: dict) -> dict:
    before_id = _id_arg(data, "before_id", required=False)
    before_ts = data.get("before_ts")
    if before_ts is not None:
        if isinstance(before_ts, bool) or not isinstance(before_ts, (int, float)):
            raise V2Error("bad_request", "before_ts: нужно число")
    limit = _limit(data, 50, chat_log.HISTORY_MAX)
    messages, has_more = await asyncio.to_thread(
        chat_log.history, before_id, limit, before_ts)
    return {"type": "history", "messages": [chat_log.to_wire(m) for m in messages],
            "has_more": has_more}


async def _chat_read(websocket, data: dict, ctx: dict) -> dict:
    last = _id_arg(data, "last_read_id")
    n = await asyncio.to_thread(chat_log.mark_read, data["device_id"], last)
    return {"type": "chat_read", "last_read_id": str(n)}


async def _chat_search(websocket, data: dict, ctx: dict) -> dict:
    q = data.get("q")
    if not isinstance(q, str) or not q.strip():
        raise V2Error("bad_request", "q: пустой запрос")
    limit = _limit(data, 20, chat_log.SEARCH_MAX)
    found = await asyncio.to_thread(chat_log.search, q, limit)
    return {"type": "chat_search", "q": q,
            "messages": [chat_log.to_wire(m) for m in found]}


async def _chat_delete(websocket, data: dict, ctx: dict) -> dict:
    msg_id = _id_arg(data, "id")
    if not await asyncio.to_thread(chat_log.delete, msg_id):
        raise V2Error("not_found", "сообщение не найдено")
    log.info(f"[v2] chat_delete id={msg_id} ({data['device_id']})")
    return {"type": "chat_delete", "id": str(msg_id)}


async def _chat_clear(websocket, data: dict, ctx: dict) -> dict:
    if data.get("confirm") is not True:
        raise V2Error("bad_request", "chat_clear: нужно confirm: true")
    n = await asyncio.to_thread(chat_log.clear)
    log.info(f"[v2] chat_clear: удалено {n} ({data['device_id']})")
    return {"type": "chat_clear", "deleted": n}


for _kind, _fn in {
    "chat_send": _chat_send,
    "history_request": _history_request,
    "chat_read": _chat_read,
    "chat_search": _chat_search,
    "chat_delete": _chat_delete,
    "chat_clear": _chat_clear,
}.items():
    proto_v2.register(_kind, _fn)
