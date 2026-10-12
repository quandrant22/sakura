"""Протокол v2 настольного клиента (desktop/docs/PROTOCOL.md, «Сервер ↔ ядро»).

Регистрация: register с proto: 2 → {"type": "registered", "device_id",
"proto": 2, "master"}. Без proto (старые клиенты) — ответа нет, всё как в v1.

Запросы v2 несут request_id, ответ его повторяет; только master-устройства
(иначе error/not_master, соединение не закрывается). Реализованы:

  chat_send {text, client_msg_id}      → chat_ack {client_msg_id, id};
                                         текст обрабатывается как запрос из окна
  history_request {before_id | before_ts, limit ≤ 100}
                                       → history {messages, has_more}
  chat_read {last_read_id}             → chat_read {last_read_id}
  chat_search {q, limit}               → chat_search {q, messages}
  chat_delete {id}                     → chat_delete {id}
  chat_clear {confirm: true}           → chat_clear {deleted}

Остальные запросы v2 (devices, status, сценарии, память, профиль) —
error/unsupported, пока не реализованы. Пуш chat_message уходит всем
master-устройствам, зарегистрированным с proto: 2.
"""

from __future__ import annotations

import asyncio
import json
import logging

import config
import modules.state as st
from modules import chat_log
from sakura_core import chat_hooks, voice_turns

log = logging.getLogger(__name__)

PROTO = 2
TEXT_MAX = 4000
CLIENT_MSG_ID_MAX = 64

V2_REQUESTS = frozenset({
    "chat_send", "history_request", "chat_read", "chat_search",
    "chat_delete", "chat_clear",
    "devices_request", "status_request",
    "scenarios_list", "scenario_get", "scenario_save", "scenario_delete",
    "scenario_run", "scenario_from_text",
    "memory_list", "memory_search", "memory_update", "memory_delete",
    "profile_get", "profile_set",
})


class V2Error(Exception):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code
        self.message = message


def is_v2(msg_type: str | None) -> bool:
    return msg_type in V2_REQUESTS


def _is_master(device_id: str | None) -> bool:
    from modules.ws_auth import is_master_device
    return is_master_device(device_id)


async def _send(ws, obj: dict) -> None:
    await ws.send(json.dumps(obj, ensure_ascii=False))


# ── регистрация ────────────────────────────────────────────────────

async def on_register(websocket, data: dict) -> None:
    """register: proto ≥ 2 → registered; иначе устройство считается v1."""
    device_id = data.get("device_id")
    try:
        proto = int(data.get("proto") or 1)
    except (TypeError, ValueError):
        proto = 1
    if not config.PROTO_V2 or proto < PROTO or not device_id:
        st.device_proto.pop(device_id, None)
        return
    st.device_proto[device_id] = PROTO
    try:
        await _send(websocket, {"type": "registered", "device_id": device_id,
                                "proto": PROTO, "master": _is_master(device_id)})
    except Exception as e:
        log.debug(f"[v2] registered не отправлен: {type(e).__name__}: {e}")
    log.info(f"[v2] {device_id}: proto {PROTO}, master={_is_master(device_id)}")


def forget(device_id: str | None) -> None:
    st.device_proto.pop(device_id, None)


async def broadcast(obj: dict) -> None:
    """Пуш всем master-устройствам с proto 2."""
    for dev, ws in list(st.connected_devices.items()):
        if st.device_proto.get(dev) != PROTO or not _is_master(dev):
            continue
        try:
            await _send(ws, obj)
        except Exception as e:
            log.debug(f"[v2] пуш {obj.get('type')} → {dev}: {type(e).__name__}: {e}")


# ── диспетчер ──────────────────────────────────────────────────────

async def handle(websocket, data: dict, ctx: dict) -> None:
    kind = data.get("type")
    rid = data.get("request_id")
    device_id = data.get("device_id")

    async def error(code: str, message: str) -> None:
        await _send(websocket, {"type": "error", "request_id": rid,
                                "code": code, "message": message})

    if not config.PROTO_V2:
        await error("unsupported", f"{kind}: сервер не поддерживает proto 2")
        return
    if not _is_master(device_id):
        await error("not_master", f"{kind}: только для master-устройств")
        return
    fn = _HANDLERS.get(kind)
    if fn is None:
        await error("unsupported", f"{kind}: пока не поддерживается")
        return
    try:
        reply = await fn(websocket, data, ctx)
    except V2Error as e:
        await error(e.code, e.message)
        return
    except Exception as e:
        log.error(f"[v2] {kind}: {type(e).__name__}: {e}")
        await error("internal", f"{kind}: ошибка сервера")
        return
    if reply is not None:
        reply["request_id"] = rid
        await _send(websocket, reply)


# ── журнал чата ────────────────────────────────────────────────────

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


_HANDLERS = {
    "chat_send": _chat_send,
    "history_request": _history_request,
    "chat_read": _chat_read,
    "chat_search": _chat_search,
    "chat_delete": _chat_delete,
    "chat_clear": _chat_clear,
}
