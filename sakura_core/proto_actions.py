"""Протокол v2: запуск действия реестра кнопкой (телефон, окно).

  action_run {request_id, action, arg?, device?}
  → action_started {request_id, action, id}

Тот же путь, что у голоса: реестр → Executor → хендлер домена. Подтверждения
не обходятся: действия с confirm (в том числе питание — power_confirm) вместо
исполнения задают вопрос reply с kind="confirm"; ответ — voice_command «да»/
«нет» (channel:"text") с любого устройства Мастера.

device: целевой ПК для агентных действий; не указан — активный ПК. Для phone.*
телефон выбирается PHONE_DEVICES. Ошибки: bad_request (форма запроса),
not_found (нет такого действия / устройство не в сети), not_master (диспетчер
proto_v2). Класс не приватный: защищённый канал не требуется сверх прав master.
"""

from __future__ import annotations

import logging

import modules.state as st
from sakura_core import proto_v2
from sakura_core.proto_v2 import V2Error

log = logging.getLogger(__name__)

ARG_MAX = 2000


def _str_field(data: dict, name: str, *, required: bool = False) -> str | None:
    v = data.get(name)
    if v is None:
        if required:
            raise V2Error("bad_request", f"{name}: обязательное поле")
        return None
    if not isinstance(v, str) or (required and not v.strip()):
        raise V2Error("bad_request", f"{name}: нужна непустая строка" if required else f"{name}: нужна строка")
    if len(v) > ARG_MAX:
        raise V2Error("bad_request", f"{name}: длиннее {ARG_MAX} символов")
    return v


def _target_pc(device: str | None) -> str:
    """Целевой ПК агентного действия: указанный или активный; он должен быть онлайн."""
    from modules.presence_sync import get_active_device, is_pc
    dev = device or get_active_device()
    if not dev:
        raise V2Error("not_found", "нет активного ПК")
    if not is_pc(dev) or dev not in st.connected_devices:
        raise V2Error("not_found", f"{dev}: не в сети")
    return dev


async def _action_run(websocket, data: dict, ctx: dict) -> dict:
    from sakura_core import bridge, power_confirm, voice_turns
    from sakura_core.executor import ExecutionContext, get_handler

    requester = data["device_id"]
    action = _str_field(data, "action", required=True).strip()
    arg = _str_field(data, "arg")
    device = _str_field(data, "device")

    decl = next((d for d in bridge._declarations if d.id == action), None)
    if decl is None or get_handler(action) is None:
        raise V2Error("not_found", f"{action}: нет такого действия")

    if decl.executor == "agent":
        target = _target_pc(device)
        device_ws = st.connected_devices[target]
    elif decl.executor == "phone":
        target, device_ws = requester, None          # телефон выбирает сам хендлер
        if device is not None:
            from config import PHONE_DEVICES
            if device not in PHONE_DEVICES:
                raise V2Error("not_found", f"{device}: не телефон")
    else:
        target, device_ws = requester, websocket

    exec_ctx = ExecutionContext(
        device_ws=device_ws, device_id=target,
        register_command=ctx.get("_register_command"),
        param=arg,
        extra={"text": arg or "", "arg": arg, "source": requester, "confirmed": False,
               "via": "action_run"})
    try:
        result = await bridge.get_executor().execute(action, exec_ctx, param=arg)
    except V2Error:
        raise
    except Exception as e:
        log.warning(f"[v2] action_run {action}: {type(e).__name__}: {e}")
        raise V2Error("internal", f"{action}: не удалось запустить") from e

    cmd_id: str | None = None
    if isinstance(result, str) and result:
        cmd_id = result
    elif result is power_confirm.DELIVERED or result is None:
        pass                                          # вопрос/ответ уже ушли reply-ем
    elif isinstance(result, tuple) and len(result) == 2 and isinstance(result[0], str):
        text, ok = result
        pending = bridge.get_router().session.pending
        asking = (pending is not None and pending.kind == "confirm" and pending.action == action)
        kind = "confirm" if asking else ("ack" if ok else "error")
        await voice_turns.send_reply(websocket, requester, text, kind)
    log.info(f"[v2] action_run {action} от {requester} → {target}: id={cmd_id}")
    return {"type": "action_started", "action": action, "id": cmd_id}


proto_v2.register("action_run", _action_run)
