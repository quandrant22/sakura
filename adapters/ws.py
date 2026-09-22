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
import random

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


import modules.state as st
from config import MASTER_ID
from modules.chains import match_voice_trigger, list_voice_triggers, list_custom_chains
from modules.tts_server import stream_tts_to_device
from modules.user_commands import parse_teaching, add as add_cmd, list_all as list_cmds
from modules.voice_info import pending_forget_active
from modules.pranks import should_prank, choose_prank, record_prank
from modules.web_search import search_and_fetch, needs_search, search_image, download_bytes
from modules.intimacy_mode import mark as _im_mark

log = logging.getLogger(__name__)

# Слова/фразы для чистки payload перед отправкой в Telegram/поиска.
# Вырезаются строго по границам слов — подстрочный replace калечил
# «мнение» → «ние», «задание» → «за ние» и т.п.
from sakura_core.send import (
    strip_payload_words as _strip_payload_words,
    has_tg_trigger as _has_tg_trigger,
    voice_to_tg as _voice_to_tg,
)


# ── Протокольные хендлеры перенесены в sakura_core/ws_protocol.py (7C-1) ──
from sakura_core.ws_protocol import (
    handle_register,
    handle_ping,
    handle_apps_list,
    handle_screen_context,
    handle_kettle_ready,
    handle_notification,
    handle_tg_message,
    handle_command_result,
    update_current_track,
)

# ── execute_critical_action перенесён в sakura_core/executor.py (7C-2) ──
from sakura_core.pending_dialog import _handle_pending as _handle_pending_core



async def _handle_pending(text, text_lower, _mk, ws_dev, device_id, ctx, data) -> bool:
    """Обёртка: делегирует в sakura_core.pending_dialog."""
    return await _handle_pending_core(text, text_lower, _mk, ws_dev, device_id, ctx, data)


async def handle_voice_command(websocket, data, ctx) -> None:
    ask_gemini = ctx["ask_gemini"]
    ask_gemini_voice = ctx["ask_gemini_voice"]
    send_safe = ctx["send_safe"]
    _find_vip_by_name = ctx["_find_vip_by_name"]
    _translate_en = ctx["_translate_en"]
    _clean_slate = ctx["_clean_slate"]
    _execute_plan = ctx["_execute_plan"]
    _register_command = ctx["_register_command"]
    _get_active_ws = ctx["_get_active_ws"]
    bot = ctx["bot"]

    device_id  = data.get("device_id")
    text       = data.get("text", "")
    context    = data.get("context", [])
    ctx_str    = f"\n\nПассивный контекст: {' | '.join(context)}" if context else ""
    ws_dev     = st.connected_devices.get(device_id)
    text_lower = text.lower()
    log.info(f"[voice] получено: {text!r}")

    # Интим-режим: детект на каждое сообщение Мастера
    _im_mark(text)

    # ── СТОП долгой озвучки («стоп», «хватит», «достаточно») ─────────
    # Если идёт чтение полного списка и Мастер просит остановить — ставим
    # флаг (чтение оборвётся между пакетами) и не даём «стоп» распознаться
    # как посторонняя команда.
    from sakura_core.tts_control import is_tts_stop
    if is_tts_stop(text_lower):
        try:
            from modules.state import tts_is_reading, tts_request_stop
            if tts_is_reading(device_id or "laptop"):
                tts_request_stop(device_id or "laptop")
                await stream_tts_to_device("Хорошо, остановилась.", ws_dev,
                                           device_id or "laptop", literal=True)
        except Exception:
            pass
        return

    # ── v3 (этап 5): confirm-диалог реестра проверяется ДО v2 _pending_system:
    try:
        from sakura_core.bridge import get_router as _v3_get_router
        _v3_r = _v3_get_router()
        if _v3_r.session.pending is not None:
            from sakura_core.bridge import handle_v3_confirm
            from sakura_core.executor import execute_critical_action as _exec_crit
            async def _v3_ws_execute(action):
                if ws_dev:
                    await _exec_crit(action.replace(".", ":", 1), ws_dev, device_id,
                                      text, data.get("active_window", ""), ask_gemini)
                else:
                    await bot.send_message(MASTER_ID, "Устройство отключилось, не могу выполнить.")
            async def _v3_ws_cancel():
                if ws_dev:
                    await stream_tts_to_device("Хорошо, отменила.", ws_dev,
                                               device_id or "laptop", literal=True)
                else:
                    await bot.send_message(MASTER_ID, "Хорошо, отменила.")
            if await handle_v3_confirm(text, on_execute=_v3_ws_execute, on_cancel=_v3_ws_cancel):
                return
    except Exception as _v3_conf_err:
        log.debug(f"[ws] v3 confirm: {type(_v3_conf_err).__name__}: {_v3_conf_err}")

    # ── PENDING-СОСТОЯНИЯ: проверяются раньше всего остального ──
    # Если Сакура ждёт подтверждения — короткий ответ Мастера принадлежит
    # этому диалогу, а не классификатору намерений.
    _mk = device_id or "tg"
    if (_mk in st._pending_system
            or _mk in st._pending_plan
            or _mk in st._pending_clarify
            or pending_forget_active()):
        _handled = await _handle_pending(text, text_lower, _mk, ws_dev, device_id, ctx, data)
        if _handled:
            return

    # ── v3 (этап 5): быстрый путь реестра — все домены ────────────────
    # Реестр без LLM; действие уходит агенту каноническим id. Временный
    # крюк: на этапе 6 ветки старого пути вынимаются вместе с ним.
    from sakura_core.bridge import resolve_conv_reply

    async def _ws_resolve_reply(_r):
        async def _speak(phrase):
            if ws_dev:
                await stream_tts_to_device(phrase, ws_dev, device_id or "laptop", literal=True)
        await resolve_conv_reply(
            _r, text=text,
            deliver=_speak,
            ask_gemini_fn=ask_gemini,
            get_active_ws_fn=_get_active_ws,
            clean_slate_fn=_clean_slate,
        )

    try:
        from sakura_core.bridge import v3_fast_path
        async def _v3_speak(phrase: str, listen=None):
            if ws_dev:
                await stream_tts_to_device(
                    phrase, ws_dev, device_id or "laptop", literal=True,
                    listen=listen)
        if await v3_fast_path(text, data=data, device_ws=ws_dev,
                              device_id=device_id,
                              register_command=ctx.get("_register_command"),
                              speak=_v3_speak,
                              resolve_reply=_ws_resolve_reply):
            return
    except Exception as _v3_err:
        log.debug(f"[v3] быстрый путь: {type(_v3_err).__name__}: {_v3_err}")

    # «Протокол чистый лист» — в conversation/clean_slate (этап 5, 3/3).
    # ── ГОЛОСОВЫЕ ТРИГГЕРЫ (проверяются первыми) ──────
    _trigger = match_voice_trigger(text)
    if _trigger and ws_dev:
        log.info(f"[trigger] сработал: '{_trigger['phrase']}'")
        for act in _trigger["actions"]:
            action = act.get("action", "")
            if action.startswith("say:"):
                await stream_tts_to_device(action[4:], ws_dev, device_id or "laptop", literal=True)
            elif action.startswith("volume:"):
                await ws_dev.send(json.dumps({"type": "command", "action": action}))
            elif action == "music:play_pause":
                await ws_dev.send(json.dumps({"type": "command", "action": "music:play_pause"}))
            elif action == "music:wave":
                await ws_dev.send(json.dumps({"type": "command", "action": "music:wave"}))
            elif action.startswith("open_app:"):
                await ws_dev.send(json.dumps({"type": "command", "action": action}))
            else:
                await ws_dev.send(json.dumps({"type": "command", "action": action}))
        return

    # ── ГОЛОСОВЫЕ ТРИГГЕРЫ (проверяются первыми) ──────
    _trigger = match_voice_trigger(text)
    if _trigger and ws_dev:
        log.info(f"[trigger] сработал: '{_trigger['phrase']}'")
        for act in _trigger["actions"]:
            action = act.get("action", "")
            if action.startswith("say:"):
                await stream_tts_to_device(action[4:], ws_dev, device_id or "laptop", literal=True)
            elif action.startswith("volume:"):
                await ws_dev.send(json.dumps({"type": "command", "action": action}))
            elif action == "music:play_pause":
                await ws_dev.send(json.dumps({"type": "command", "action": "music:play_pause"}))
            elif action == "music:wave":
                await ws_dev.send(json.dumps({"type": "command", "action": "music:wave"}))
            elif action.startswith("open_app:"):
                await ws_dev.send(json.dumps({"type": "command", "action": action}))
            else:
                await ws_dev.send(json.dumps({"type": "command", "action": action}))
        return

    # ── ОБУЧЕНИЕ НОВЫМ КОМАНДАМ (раньше всего) ───────────
    if any(w in text.lower() for w in ('покажи команды', 'список команд', 'мои команды')):
        cmds = list_cmds()
        cmd_list = ', '.join(list(cmds.keys())[:10]) if cmds else None
        if cmd_list:
            _lr = await ask_gemini(f'Скажи Мастеру его сохранённые команды: {cmd_list}. Коротко.', save_history=False)
        else:
            _lr = await ask_gemini('Скажи Мастеру что он ещё не добавил своих команд. Можно добавить голосом: "запомни: слово = действие".', save_history=False)
        if _lr:
            _active_ws, _ad = _get_active_ws()
            if _active_ws:
                await stream_tts_to_device(_lr, _active_ws, _ad or 'laptop', literal=True)
        return
    _teaching = parse_teaching(text)
    if _teaching:
        _trigger, _action = _teaching
        add_cmd(_trigger, _action)
        _tr = await ask_gemini(f'Запомнила команду "{_trigger}". Подтверди коротко.', save_history=False)
        if _tr:
            _active_ws, _ad = _get_active_ws()
            if _active_ws:
                await stream_tts_to_device(_tr, _active_ws, _ad or 'laptop', literal=True)
        return

    # ── ПОЛЬЗОВАТЕЛЬСКИЕ ЦЕПОЧКИ ────────────────────
    if any(w in text.lower() for w in ("создай цепочку", "новая цепочка", "добавь цепочку")):
        _chain_prompt = (
            "Мастер хочет создать цепочку команд. "
            "Попроси его описать что нужно сделать по порядку. "
            "Скажи коротко какие действия доступны: открыть приложение, громкость, музыка, сказать фразу."
        )
        _chain_reply = await ask_gemini(_chain_prompt, save_history=False)
        if _chain_reply and ws_dev:
            await stream_tts_to_device(_chain_reply, ws_dev, device_id or "laptop", literal=True)
        return

    if any(w in text.lower() for w in ("цепочки", "список цепочек", "мои цепочки")):
        _chain_list = list_custom_chains()
        if ws_dev:
            await stream_tts_to_device(_chain_list, ws_dev, device_id or "laptop", literal=True)
        return

    # ── ГОЛОСОВЫЕ ТРИГГЕРЫ: создание ──────────────────
    if "запомни триггер" in text.lower() or "создай триггер" in text.lower():
        _trig_prompt = (
            "Мастер хочет создать голосовой триггер. "
            "Попроси его сказать фразу-триггер и что делать при срабатывании. "
            "Доступные действия: остановить музыку, включить музыку, сказать фразу, "
            "выключить звук, включить приложение."
        )
        _trig_reply = await ask_gemini(_trig_prompt, save_history=False)
        if _trig_reply and ws_dev:
            await stream_tts_to_device(_trig_reply, ws_dev, device_id or "laptop", literal=True)
        return

    if any(w in text.lower() for w in ("триггеры", "список триггеров", "мои триггеры")):
        _trig_list = list_voice_triggers()
        if ws_dev:
            await stream_tts_to_device(_trig_list, ws_dev, device_id or "laptop", literal=True)
        return

    # Чтение активной страницы переехало в реестр (ext.page_content /
    # ext.page_content_youtube, этап 5 2/2) — ветка снята.
    # Написать VIP — в conversation/vip_message (этап 5, 3/3).
    # ── отправка в Telegram по голосу ──
    if _has_tg_trigger(text_lower):
        payload = _strip_payload_words(text_lower)

        async def _say(phrase):
            if ws_dev:
                await stream_tts_to_device(phrase, ws_dev, device_id or "laptop", literal=True)

        if not payload:
            await _say("Что прислать в телеграм, Мастер?")
            return

        aw = data.get("active_window", "")
        await _voice_to_tg(
            text, text_lower, payload, aw,
            ask_gemini, send_safe, search_image, download_bytes,
            search_and_fetch, needs_search, _translate_en, bot, MASTER_ID,
        )
        await _say("Готово, Мастер.")
        return

    active_win = data.get("active_window", "")
    # Обновляем контекст игрового хаба
    try:
        from modules.game_hub import get_game_context_for_device
        get_game_context_for_device(active_win)
    except Exception as e:
        log.debug(f"[voice] game_hub ctx: {e}")
    log.info(f"[voice] → ask_gemini_voice ws_dev={ws_dev is not None} device={device_id}")
    await ask_gemini_voice(
        user_message  = text + ctx_str,
        websocket     = ws_dev,
        device_id     = device_id or "laptop",
        active_window = active_win,
    )

    # ── ПРАНКИ + РЕАКЦИИ САКУРЫ (фоновая задача) ──────
    async def _maybe_prank_and_react():
        try:
            if should_prank(text):
                prank = choose_prank()
                record_prank()
                response = random.choice(prank.get("responses", ["Хаха"]))
                log.info(f"[pranks] выполняю: {prank['name']}")
                if ws_dev:
                    await stream_tts_to_device(response, ws_dev, device_id or "laptop", literal=True)

            from sakura_core.reactions import get_mood_reaction, get_sticker_or_gif
            reaction = get_mood_reaction(text)
            if reaction:
                sticker, gif = get_sticker_or_gif(reaction["emotion"])
                if sticker:
                    log.info(f"[reactions] {reaction['emotion']} → sticker")
                    try:
                        await bot.send_sticker(MASTER_ID, sticker)
                    except Exception as e:
                        log.debug(f"[ws] reaction sticker: {type(e).__name__}: {e}")
                elif gif:
                    log.info(f"[reactions] {reaction['emotion']} → GIF")
                    try:
                        await bot.send_animation(MASTER_ID, gif)
                    except Exception as e:
                        log.debug(f"[ws] reaction gif: {type(e).__name__}: {e}")
        except Exception as e:
            log.debug(f"[pranks/react] error: {e}")
    asyncio.create_task(_maybe_prank_and_react())
