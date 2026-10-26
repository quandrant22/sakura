"""Протокол v2 настольного клиента (desktop/docs/PROTOCOL.md, «Сервер ↔ ядро»).

Ядро без журнала чата (журнал — порция 1, выкатывается только после
wss://): регистрация, диспетчер запросов, пуши.

Регистрация: register с proto: 2 → {"type": "registered", "device_id",
"proto": 2, "master"}. Без proto (старые клиенты) — ответа нет, всё как в v1.

Запросы v2 несут request_id, ответ его повторяет; только master-устройства
(иначе error/not_master, соединение не закрывается). Обработчики порций
подключаются через register(); незарегистрированные запросы v2 —
error/unsupported. Пуши (device_update, status, …) уходят всем
master-устройствам, зарегистрированным с proto: 2.

PROTO_V2=0 — сервер ведёт себя как v1.
"""

from __future__ import annotations

import json
import logging
from typing import Awaitable, Callable

import config
import modules.state as st

log = logging.getLogger(__name__)

PROTO = 2

V2_REQUESTS = frozenset({
    "chat_send", "history_request", "chat_read", "chat_search",
    "chat_delete", "chat_clear",
    "devices_request", "status_request", "secure_devices",
    "scenarios_list", "scenario_get", "scenario_save", "scenario_delete",
    "scenario_run", "scenario_from_text",
    "memory_list", "memory_search", "memory_update", "memory_delete",
    "profile_get", "profile_set",
    "browser_step", "browser.resume",
})

Handler = Callable[[object, dict, dict], Awaitable[dict | None]]

# Приватные классы (чат, история, память, профиль, кадры browser agent):
# только secure-соединение (docs/security/PROTOCOL.md §5.1). Второй рубеж
# после adapters/ws.
PRIVATE_PREFIXES = ("chat_", "history_", "memory_", "profile_", "secure_", "browser")


def is_private(kind: str | None) -> bool:
    return (kind or "").startswith(PRIVATE_PREFIXES)


def connection_secure(websocket) -> bool:
    """Noise (обёртка с secure=True) или локальный источник по политике
    securechannel; без модуля политики — не secure (DECISIONS S9)."""
    if getattr(websocket, "secure", False) is True:
        return True
    try:
        # Модуль политики — из feat/securechannel; без него (выкатили раньше)
        # приватное не открывается (importlib — чтобы проверка ссылок не
        # требовала модуль, которого в этой ветке ещё нет).
        import importlib
        secure_policy = importlib.import_module("sakura_core.secure_policy")
    except ImportError:
        return False
    return secure_policy.is_local_peer(secure_policy.peer_ip(websocket))
_HANDLERS: dict[str, Handler] = {}


class V2Error(Exception):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code
        self.message = message


def register(kind: str, fn: Handler) -> None:
    """Подключить обработчик запроса v2 (порции 1–4)."""
    if kind not in V2_REQUESTS:
        raise ValueError(f"не запрос v2: {kind}")
    _HANDLERS[kind] = fn


def is_v2(msg_type: str | None) -> bool:
    return msg_type in V2_REQUESTS


def is_v2_device(device_id: str | None) -> bool:
    return st.device_proto.get(device_id) == PROTO


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
        if not is_v2_device(dev) or not _is_master(dev):
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
    if is_private(kind) and not connection_secure(websocket) \
            and getattr(config, "PRIVATE_REQUIRES_SECURE", True):
        await _send(websocket, {"type": "error", "request_id": rid,
                                "code": "secure_channel_required",
                                "message": "нужен защищённый канал",
                                "hint": "подключитесь через защищённый канал (Noise) или VPN"})
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


def _load_portions() -> None:
    """Порции протокола, выкатываемые без шифрования: устройства и статус."""
    from sakura_core import proto_devices  # noqa: F401
    from sakura_core import proto_chat  # noqa: F401
    from sakura_core import proto_memory  # noqa: F401
    from sakura_core import proto_profile  # noqa: F401
    from sakura_core import proto_scenarios  # noqa: F401
    from sakura_core import browser_step  # noqa: F401


_load_portions()
