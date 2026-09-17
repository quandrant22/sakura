"""WebSocket device handler — extracted from adapters/voice.py.

ws_handler, _execute_plan, _register_command, _resolve_command_status,
speak_now_playing_result.
"""

from __future__ import annotations

import asyncio
import json
import logging
import time
import uuid

from modules.state import _pending_commands, connected_devices, _plan_cancel

log = logging.getLogger("sakura.ws")


def _cleanup_pending_commands():
    now = time.monotonic()
    expired = [k for k, v in _pending_commands.items() if now - v["ts"] > 300]
    for k in expired:
        del _pending_commands[k]


def _register_command(action: str, device: str) -> str:
    cmd_id = uuid.uuid4().hex[:12]
    _pending_commands[cmd_id] = {
        "action": action, "device": device,
        "ts": time.monotonic(), "status": "sent",
    }
    _cleanup_pending_commands()
    return cmd_id


def _resolve_command_status(device: str, ok: bool, detail: str) -> str:
    now = time.monotonic()
    best_id, best_ts = None, -1
    for cmd_id, cmd in _pending_commands.items():
        if cmd["status"] == "sent" and cmd["device"] == device and now - cmd["ts"] < 300:
            if cmd["ts"] > best_ts:
                best_ts, best_id = cmd["ts"], cmd_id
    if best_id:
        _pending_commands[best_id]["status"] = "executed" if ok else "failed"
        _pending_commands[best_id]["detail"] = detail
        return _pending_commands[best_id]["status"]
    return "executed" if ok else "failed"


PLAN_WAIT_ACK = True


async def _execute_plan(plan: dict, master_key: str, ws_dev, device_id) -> tuple[bool, str]:
    steps = plan.get("steps", [])
    summary = plan.get("summary", "задача")

    for i, step in enumerate(steps):
        if _plan_cancel.get(master_key):
            _plan_cancel.pop(master_key, None)
            return False, f"План остановлен на шаге {i + 1} по запросу Мастера."

        action = step.get("action", "")
        arg = step.get("arg", "")

        if action == "wait":
            try:
                wait_sec = min(int(arg), 10)
            except (ValueError, TypeError):
                wait_sec = 1
            await asyncio.sleep(wait_sec)
            continue

        if not ws_dev:
            return False, "Устройство offline, план не может быть выполнен."

        full_action = f"{action}:{arg}" if arg and ":" not in action else action
        _cmd_id = _register_command(full_action, device_id or "laptop")
        await ws_dev.send(json.dumps({"type": "command", "action": full_action, "id": _cmd_id}))

        if PLAN_WAIT_ACK:
            for _ in range(50):
                await asyncio.sleep(0.2)
                cmd = _pending_commands.get(_cmd_id, {})
                if cmd.get("status") in ("executed", "failed"):
                    if cmd["status"] == "failed":
                        return False, f"План остановлен на шаге {i + 1}: {full_action} — {cmd.get('detail', 'ошибка')}"
                    break
            else:
                return False, f"План остановлен на шаге {i + 1}: {full_action} — таймаут ожидания"
        else:
            await asyncio.sleep(1.0)

    return True, f"План выполнен: {summary}"


async def speak_now_playing_result(cmd_id: str, ws_dev, device_id: str, bot) -> None:
    import modules.state as st
    from modules.tts_server import stream_tts_to_device
    from config import MASTER_ID

    try:
        for _ in range(125):
            await asyncio.sleep(0.2)
            _cmd = st._pending_commands.get(cmd_id, {})
            if _cmd.get("spoken") or _cmd.get("status") in ("executed", "failed"):
                break
        _cmd    = st._pending_commands.get(cmd_id, {})
        _status = _cmd.get("status", "sent")
        _detail = (_cmd.get("detail") or "").strip()
        if _cmd.get("spoken"):
            return
        if _status == "executed" and _detail:
            _reply = _detail
        else:
            _reply = ("Не вижу, что сейчас играет — Яндекс Музыка не отвечает. "
                      "Похоже, она не запущена.")
        _cmd["answered"] = True
        log.info(f"[голос] ответ: {_reply!r}")
        if ws_dev:
            await stream_tts_to_device(_reply, ws_dev, device_id, literal=True)
        try:
            await bot.send_message(MASTER_ID, _reply)
        except Exception as e:
            log.debug(f"[music] now_playing tg: {type(e).__name__}: {e}")
    except Exception as e:
        log.debug(f"[music] now_playing: {type(e).__name__}: {e}")


async def ws_handler(websocket):
    from adapters.telegram import bot, send_to_master, send_safe
    from modules.ws_handlers import (
        handle_register, handle_ping, handle_apps_list, handle_screen_context,
        handle_command_result, handle_kettle_ready, handle_notification,
        handle_tg_message, handle_voice_command, update_current_track,
    )
    from modules.ws_auth import check_token, is_master_device, reject
    from modules.device_manager import set_device_offline
    from modules.presence_sync import set_offline as ps_offline
    from modules.rituals import should_farewell, get_farewell_prompt
    from modules.app_mapping import find_vip_by_name
    from sakura_core.memory_tasks import clean_slate
    from sakura_core.apps import analyze_apps, analyze_screen_context
    from sakura_core.llm import ask_gemini, ask_gemini_voice
    from adapters.voice import _get_active_ws

    device_id = None
    try:
        async for raw in websocket:
            try:
                data     = json.loads(raw)
                msg_type = data.get("type")

                if not check_token(data):
                    await reject(websocket, reason=f"invalid token on '{msg_type}'")
                    return

                dev_from_msg = data.get("device_id")
                if msg_type in ("voice_command", "apps_list"):
                    if not is_master_device(dev_from_msg):
                        await reject(websocket, reason=f"'{msg_type}' denied: not master device ({dev_from_msg!r})")
                        return

                _ctx = {
                    "ask_gemini": ask_gemini,
                    "ask_gemini_voice": ask_gemini_voice,
                    "send_safe": send_safe,
                    "_find_vip_by_name": find_vip_by_name,
                    "_translate_en": None,
                    "_clean_slate": clean_slate,
                    "_execute_plan": _execute_plan,
                    "_register_command": _register_command,
                    "_resolve_command_status": _resolve_command_status,
                    "_get_active_ws": _get_active_ws,
                    "analyze_apps": analyze_apps,
                    "_analyze_screen_context": analyze_screen_context,
                    "_gemini_client": None,
                    "bot": bot,
                    "PLAN_WAIT_ACK": PLAN_WAIT_ACK,
                }

                HANDLERS = {
                    "register": handle_register,
                    "ping": handle_ping,
                    "apps_list": handle_apps_list,
                    "screen_context": handle_screen_context,
                    "command_result": handle_command_result,
                    "kettle_ready": handle_kettle_ready,
                    "notification": handle_notification,
                    "tg_message": handle_tg_message,
                    "voice_command": handle_voice_command,
                }
                handler = HANDLERS.get(msg_type)
                if handler:
                    await handler(websocket, data, _ctx)
                else:
                    log.warning(f"unknown msg_type: {msg_type}")

                if msg_type in ("register", "ping", "voice_command"):
                    device_id = data.get("device_id")

                update_current_track(data)

            except Exception as e:
                log.error(f"[ws_handler] {e}")

    except Exception as e:
        log.debug(f"[ws_handler] {type(e).__name__}: {e}")
    finally:
        if device_id:
            set_device_offline(device_id)
            connected_devices.pop(device_id, None)
            await asyncio.to_thread(ps_offline, device_id)
            log.info(f"Устройство отключено: {device_id}")

            if is_master_device(device_id) and should_farewell():
                farewell = await ask_gemini(get_farewell_prompt(), save_history=False)
                if farewell:
                    await send_to_master(farewell)
