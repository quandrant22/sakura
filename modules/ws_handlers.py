"""WebSocket message handlers for the Sakura server.

Each handler receives (websocket, data, ctx) where ctx is a dict
with shared dependencies from main.py (functions, bot, constants).
State dicts are accessed via modules.state.
"""
from __future__ import annotations

import asyncio
import json
import base64
import logging
import random
import re
import time as _time

import modules.state as st
from aiogram.types import BufferedInputFile
from config import MASTER_ID, get_active_key, mark_key_used, MAIN_MODEL
from sakura_core.llm import generate as _llm_generate
from modules.command_router import route_command, route_critical, is_irreversible, EXEC_THRESHOLD, GRAY_THRESHOLD
from modules.intent_classifier import classify_intent, is_command as _is_command_check
from modules.chains import match_voice_trigger, list_voice_triggers, list_custom_chains
from modules.tts_server import stream_tts_to_device, strip_tone
from modules.ws_auth import is_master_device
from modules.rituals import should_greet_device, get_greeting_prompt
from modules.briefing import should_brief, run_briefing
from modules.presence_sync import update as ps_update, check_device_transfer, broadcast_transfer
from modules.mood_vector import get_orb_params
from modules.evening_pulse import check_pc_health
from modules.window_watcher import update as watcher_update
from modules.proactive_recs import track_activity as track_rec_activity
from modules.steam_integration import get_current_game
from modules.autonomous import update_sprint
from modules.integrations import (
    should_comment_music, get_current_music_from_window,
    make_music_comment_prompt, mark_music_commented,
)
from modules.game_detector import detect_game_event, make_event_prompt
from modules.user_commands import parse_teaching, add as add_cmd, list_all as list_cmds
from modules.voice_info import is_info_action
from modules.voice_info import pending_forget_active, memory_forget_confirm
from modules.music_memory import (
    track_play, like_artist, dislike_artist,
    generate_taste_comment,
)
from modules.pranks import should_prank, choose_prank, record_prank
from modules.reactions import detect_reaction, get_random_gif, should_react
from modules.web_search import search_and_fetch, needs_search, search_image, download_bytes
from modules.youtube import youtube_command
from modules.notification_tracker import add_notification
from modules.intimacy_mode import mark as _im_mark
from modules.episodes import add_episode
from modules.disposition import current as _disp_current
from modules.app_launcher import record_launch
from modules.device_manager import update_device
from memory.db import get_memory_context as db_get_memory_context

log = logging.getLogger(__name__)

# Слова/фразы для чистки payload перед отправкой в Telegram/поиска.
# Вырезаются строго по границам слов — подстрочный replace калечил
# «мнение» → «ние», «задание» → «за ние» и т.п.
from adapters.telegram import (
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
    _DANGEROUS_SYSTEM_ACTIONS,
    _SYSTEM_CONFIRM_PROMPTS,
)

# ── execute_critical_action перенесён в sakura_core/executor.py (7C-2) ──
from sakura_core.executor import execute_critical_action
from adapters.voice import speak_now_playing_result
from modules.voice_info import answer_voice_info
from sakura_core.send import split_tg as _split_tg
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
        async def _v3_speak(phrase: str):
            if ws_dev:
                await stream_tts_to_device(
                    phrase, ws_dev, device_id or "laptop", literal=True)
        if await v3_fast_path(text, data=data, device_ws=ws_dev,
                              device_id=device_id,
                              register_command=ctx.get("_register_command"),
                              speak=_v3_speak,
                              resolve_reply=_ws_resolve_reply):
            return
    except Exception as _v3_err:
        log.debug(f"[v3] быстрый путь: {type(_v3_err).__name__}: {_v3_err}")

    # ── СЕМАНТИЧЕСКИЙ КЛАССИФИКАТОР НАМЕРЕНИЙ ──────────
    # Быстро определяем тип: команда, запрос или разговор
    _intent = await classify_intent(text)
    log.info(f"[intent] тип={_intent.type}, намерение={_intent.intent}, длина={_intent.length}, уверенность={_intent.confidence:.2f}")

    # Если это разговор и уверенность высокая — пропускаем командный роутер
    if _intent.type == "conversation" and _intent.confidence >= 0.8:
        log.info(f"[intent] разговор → ask_gemini_voice (len={_intent.length})")
        active_win = data.get("active_window", "")
        await ask_gemini_voice(
            user_message  = text + ctx_str,
            websocket     = ws_dev,
            device_id     = device_id or "laptop",
            active_window = active_win,
            length        = _intent.length,
        )
        return

    # ── МАРШРУТИЗАЦИЯ ПО INTENT ──────────────────────────
    # Если intent classifier определил конкретное действие — выполняем
    _is_send_tg = (
        _intent.type == "command" and
        _intent.confidence >= 0.7 and
        ("tg" in _intent.intent.lower() or "telegram" in _intent.intent.lower()
         or "send" in _intent.intent.lower())
    )
    # Погода переехала в реестр (weather.now, этап 5 2/2) — интент-ветка снята.

    _is_web_search = (
        _intent.type in ("command", "request") and
        _intent.confidence >= 0.7 and
        any(k in _intent.intent.lower() for k in ("search", "find", "recipe", "info", "news"))
    )

    if _is_send_tg or _is_web_search:
        log.info(f"[intent] {_intent.intent} → TG/web search")
        # Извлекаем что именно отправлять
        _tg_payload = _strip_payload_words(text_lower)
        if not _tg_payload:
            _tg_payload = text  # fallback — весь текст

        async def _say_tg(phrase):
            if ws_dev:
                await stream_tts_to_device(phrase, ws_dev, device_id or "laptop", literal=True)

        try:
            # Погода переехала в реестр (weather.now, этап 5 2/2) — ветка снята.
            # Любой другой запрос → РЕАЛЬНЫЙ поиск в интернете → ТГ
            search_res = await search_and_fetch(_tg_payload)
            if search_res:
                await send_safe(MASTER_ID, search_res)
                await _say_tg("Нашла в интернете и отправила, Мастер.")
            else:
                # Если поиск ничего не дал — через Gemini как fallback
                answer = await ask_gemini(_tg_payload, save_history=False)
                if answer:
                    await send_safe(MASTER_ID, answer)
                    await _say_tg("Отправила в телеграм, Мастер.")
                else:
                    await _say_tg("Не нашла ничего, Мастер.")
        except Exception as e:
            log.error(f"[intent] TG send error: {e}")
            await _say_tg("Не получилось отправить, Мастер.")
        return

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

    # ── написать VIP по голосу ──
    # Поиск VIP перенесён в conversation/vip_message (этап 5, 3/3).
    # ── ГОЛОСОВЫЕ КОМАНДЫ МОДУЛЕЙ (voice_router) ──────────
    _module_handled = False
    try:
        from modules.voice_router import handle_voice as _voice_handle
        _result = _voice_handle(text)
        if _result:
            log.info(f"[voice/router] {_result[:50]}")
            if ws_dev:
                await stream_tts_to_device(_result, ws_dev, device_id or "laptop", literal=True)
            _module_handled = True
    except Exception as _vre:
        log.debug(f"[voice/router] Ошибка: {_vre}")

    if _module_handled:
        return

    # ── КОДИНГ ПО ГОЛОСУ ────────────────────────────────────
    voice_coding_triggers = [
        "создай модуль", "напиши модуль", "новый модуль", "сделай модуль",
        "исправь баг", "найди баг", "почини",
        "прочитай файл", "покажи код",
        "коммит", "git", "деплой",
    ]
    if any(t in text_lower for t in voice_coding_triggers):
        try:
            from modules.coding import mimo_fix, auto_integrate, read_file, git_commit
            from modules.prompt_builder import build_module_prompt

            if any(t in text_lower for t in ("создай модуль", "напиши модуль", "новый модуль", "сделай модуль")):
                prompt = f"Создай новый модуль по запросу Мастера: {text}. Автоматически интегрируй в main.py через auto_integrate()."
                log.info(f"[voice/coding] Создаю модуль: {text[:50]}")
                result = await mimo_fix(prompt)
                reply = result.get("output", "")[:1500] if result.get("ok") else f"Ошибка: {result.get('error', 'неизвестно')}"
                if ws_dev:
                    await stream_tts_to_device(reply, ws_dev, device_id or "laptop", literal=True)
                return

            elif any(t in text_lower for t in ("исправь баг", "найди баг", "почини")):
                prompt = f"Найди и исправь проблему: {text}"
                log.info(f"[voice/coding] Исправляю баг: {text[:50]}")
                result = await mimo_fix(prompt)
                reply = result.get("output", "")[:1500] if result.get("ok") else f"Ошибка: {result.get('error')}"
                if ws_dev:
                    await stream_tts_to_device(reply, ws_dev, device_id or "laptop", literal=True)
                return

            elif any(t in text_lower for t in ("коммит", "git commit")):
                msg = re.sub(r"(?<!\w)git commit(?!\w)", " ", text)
                msg = re.sub(r"(?<!\w)коммит(?!\w)", " ", msg).strip()
                if not msg:
                    msg = "Обновление от Сакуры"
                result = await git_commit(msg)
                reply = f"Коммит выполнен: {result[:200]}" if isinstance(result, str) else "Коммит выполнен"
                if ws_dev:
                    await stream_tts_to_device(reply, ws_dev, device_id or "laptop", literal=True)
                return

        except Exception as e:
            log.error(f"[voice/coding] Ошибка: {e}")
            if ws_dev:
                await stream_tts_to_device(f"Ошибка кодинга: {str(e)[:100]}", ws_dev, device_id or "laptop", literal=True)
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

    # Переводчик, игра в слова, калькулятор, печенье и страхи —
    # разговорный слой conversation/ (этап 5, 3/3): разбираются в
    # router.route() между реестром и LLM.
    # ── КРИТИЧЕСКИЕ КОМАНДЫ (точный матчинг, без LLM) ────
    _critical = route_critical(text)
    if _critical and ws_dev:
        if _critical in _DANGEROUS_SYSTEM_ACTIONS:
            # Опасная системная команда — не выполняем сразу, спрашиваем подтверждение
            _sys_mk = device_id or "tg"
            st._pending_system[_sys_mk] = {
                "action": _critical,
                "device": device_id,
                "ts": __import__("time").monotonic(),
            }
            _sys_q = _SYSTEM_CONFIRM_PROMPTS.get(_critical, "Выполняю системную команду. Подтверждаешь?")
            await stream_tts_to_device(_sys_q, ws_dev, device_id or "laptop", literal=True)
            return
        await execute_critical_action(_critical, ws_dev, device_id, text, data.get("active_window", ""), ask_gemini)
        return

    # ── ПОДТВЕРЖДЕНИЕ ПЛАНА ─────────────────────────────
    _mk = device_id or "tg"
    _now_ts = __import__("time").monotonic()


    # ── ДЕТЕКТОР КОРРЕКЦИИ (шаг 6) ─────────────────────────
    if _mk in st._last_executed:
        _le = st._last_executed[_mk]
        if _now_ts - _le["ts"] < 90:
            _tlow = text.lower().strip()
            if (_tlow.startswith("нет") or
                any(p in _tlow for p in ("я имел в виду", "не то", "я просил", "неправильно"))):
                try:
                    _router_ctx = {
                        "active_window": data.get("active_window", ""),
                        "current_track": st._current_track,
                    }
                    _fix = await route_command(text, context=_router_ctx)
                    if _fix and _fix.get("action") and _fix.get("confidence", 0) >= 0.5:
                        from modules.user_commands import add as _uc_add
                        _uc_add(_le["text"], _fix, source="auto")
                        if ws_dev:
                            _fix_action = _fix.get("action", "")
                            _fix_arg = _fix.get("arg", "")
                            if _fix_arg and ":" not in _fix_action:
                                _fix_full = f"{_fix_action}:{_fix_arg}"
                            else:
                                _fix_full = _fix_action
                            _cmd_id = _register_command(_fix_full, device_id or "laptop")
                            await ws_dev.send(json.dumps({"type": "command", "action": _fix_full, "id": _cmd_id}))
                        st._last_executed.pop(_mk, None)
                        return
                except Exception as e:
                    log.debug(f"[ws] _say: {type(e).__name__}: {e}")
        st._last_executed.pop(_mk, None)

    # ── LLM-РОУТЕР (все остальные команды) ──────────────
    _router_ctx = {
        "active_window": data.get("active_window", ""),
        "current_track": st._current_track,
    }
    _routed = await route_command(text, context=_router_ctx)
    _confidence = _routed.get("confidence", 0.7) if _routed else 0.0
    log.info(f"[router] {text!r} → {_routed} | routed={bool(_routed)} ws_dev={bool(ws_dev)} device={device_id} connected={list(st.connected_devices)}")

    if _routed:
        _is_irrev = is_irreversible(_routed.get("action", ""))

        # Зона 1: высокая уверенность — исполнять
        if _confidence >= EXEC_THRESHOLD:
            pass  # ниже по коду

        # Зона 2: серая зона + обратимое — исполнять
        elif GRAY_THRESHOLD <= _confidence < EXEC_THRESHOLD and not _is_irrev:
            pass  # ниже по коду

        # Зона 3: серая зона + необратимое — уточнение
        elif GRAY_THRESHOLD <= _confidence < EXEC_THRESHOLD and _is_irrev:
            _alt = _routed.get("alt")
            if _alt and _alt.get("action"):
                try:
                    from modules.disposition import current as _dc
                    _d = _dc()
                    _q_prompt = (
                        f"Мастер сказал: {text}. "
                        f"Вариант 1: {_routed.get('action','')} {_routed.get('arg','')}. "
                        f"Вариант 2: {_alt.get('action','')} {_alt.get('arg','')}. "
                        f"Спроси коротко: какой вариант он имел в виду? Одно предложение."
                    )
                    _q = await ask_gemini(_q_prompt, save_history=False)
                    if _q:
                        if ws_dev:
                            await stream_tts_to_device(_q, ws_dev, device_id or "laptop", literal=True)
                        else:
                            await bot.send_message(MASTER_ID, _q)
                    st._pending_clarify[_mk] = {
                        "text": text,
                        "main": _routed,
                        "alt": _alt,
                        "ts": __import__("time").monotonic(),
                    }
                except Exception as e:
                    log.debug(f"[ws] _say: {type(e).__name__}: {e}")
            else:
                try:
                    _action = _routed.get("action", "")
                    _arg = _routed.get("arg", "")
                    _q_prompt = (
                        f"Мастер сказал: {text}. Ты думаешь, он хочет: {_action} {_arg}, "
                        f"но не уверена. Переспроси коротко, одно предложение."
                    )
                    _q = await ask_gemini(_q_prompt, save_history=False)
                    if _q:
                        if ws_dev:
                            await stream_tts_to_device(_q, ws_dev, device_id or "laptop", literal=True)
                        else:
                            await bot.send_message(MASTER_ID, _q)
                    st._pending_clarify[_mk] = {
                        "text": text,
                        "main": _routed,
                        "alt": None,
                        "ts": __import__("time").monotonic(),
                    }
                except Exception as e:
                    log.debug(f"[ws] _say: {type(e).__name__}: {e}")
            return

        # Зона 4: низкая уверенность — честный отказ, планировщик НЕ строит
        else:
            try:
                _deny_prompt = (
                    f"Мастер сказал: {text}. Ты не поняла, какое действие он хочет. "
                    f"Скажи это честно, одним коротким предложением, попроси сказать иначе."
                )
                _deny = await ask_gemini(_deny_prompt, save_history=False)
                if _deny:
                    if ws_dev:
                        await stream_tts_to_device(
                            _deny, ws_dev, device_id or "laptop", literal=True)
                    else:
                        await bot.send_message(MASTER_ID, _deny)
            except Exception as e:
                log.debug(f"[ws] _say: {type(e).__name__}: {e}")
            return

    # ── ПЛАНИРОВЩИК: route_command вернул None ──────────
    # Не строить план если уверенность роутера низкая — текст мусорный
    if not _routed:
        if _is_command_check(text) and len(text.split()) <= 4:
            from modules.planner import build_plan
            _plan = await build_plan(text, _router_ctx,
                                     source="voice", sender_id=device_id)
            if _plan:
                if _plan["risky"]:
                    try:
                        _q_prompt = (
                            f"Сделаю так: {_plan['summary']}. "
                            f"Это включает действия которые нельзя отменить. Давай?"
                        )
                        _q = await ask_gemini(_q_prompt, save_history=False)
                        if _q:
                            if ws_dev:
                                await stream_tts_to_device(
                                    _q, ws_dev, device_id or "laptop", literal=True)
                            else:
                                await bot.send_message(MASTER_ID, _q)
                        st._pending_plan[_mk] = {
                            "text": text,
                            "plan": _plan,
                            "ts": __import__("time").monotonic(),
                        }
                    except Exception as e:
                        log.debug(f"[ws] _say: {type(e).__name__}: {e}")
                else:
                    _plan_result, _plan_msg = await _execute_plan(
                        _plan, _mk, ws_dev, device_id)
                    if _plan_result:
                        from modules.user_commands import add as _uc_add
                        _uc_add(text, {
                            "plan": _plan["steps"],
                            "summary": _plan["summary"],
                            "source": "plan",
                            "risky": _plan["risky"],
                            "uses": 1,
                        }, source="plan")
                    if ws_dev:
                        await stream_tts_to_device(
                            _plan_msg, ws_dev, device_id or "laptop", literal=True)
                    else:
                        await bot.send_message(MASTER_ID, _plan_msg)
                return

    # ── ИНФОРМАЦИОННЫЕ КОМАНДЫ (steam/vps/задачи/погода/...) ──
    # Не требуют устройства: данные с сервера, ответ голосом или в ТГ.
    if _routed and is_info_action(_routed.get("action", "")):
        st._last_command_ts = __import__('time').monotonic()
        await answer_voice_info(
            _routed.get("action", ""), _routed.get("arg", "") or "",
            text, ws_dev, device_id, ask_gemini, bot)
        return

    if _routed and ws_dev:
        # ── Навык-план: выполнять через _execute_plan ──────
        if "plan" in _routed:
            _skill_plan = {
                "steps": _routed["plan"],
                "summary": _routed.get("summary", "выполнить сохранённый план"),
                "risky": _routed.get("risky", False),
            }
            _plan_result, _plan_msg = await _execute_plan(
                _skill_plan, _mk, ws_dev, device_id)
            if _plan_msg:
                log.info(f"[голос] ответ: {_plan_msg!r}")
            if ws_dev:
                await stream_tts_to_device(
                    _plan_msg, ws_dev, device_id or "laptop", literal=True)
            else:
                await bot.send_message(MASTER_ID, _plan_msg)
            return

        st._last_command_ts = __import__('time').monotonic()
        action  = _routed.get("action", "")
        arg     = _routed.get("arg", "")
        is_agent= _routed.get("agent", False)

        # Полный action с arg если нужно
        if arg and ":" not in action:
            full_action = f"{action}:{arg}"
        else:
            full_action = action

        # Запомнить последнюю команду для детектора коррекции
        st._last_executed[_mk] = {
            "text": text,
            "action": full_action,
            "ts": __import__("time").monotonic(),
        }

        # Скриншот с описанием → запоминаем флаг, отправляем screenshot:
        if full_action == "screenshot:describe":
            st._pending_describe[device_id or "laptop"] = True
            _cmd_id = _register_command("screenshot:", device_id or "laptop")
            await ws_dev.send(json.dumps({"type": "command", "action": "screenshot:", "id": _cmd_id}))
            log.info(f"[vision] запрос скриншота с описанием для {device_id}")
        elif is_agent:
            # Команды для агента (YouTube через расширение и т.д.)
            _cmd_id = _register_command(full_action, device_id or "laptop")
            await ws_dev.send(json.dumps({"type": "command", "action": full_action, "id": _cmd_id}))
        elif action.startswith("youtube_"):
            # YouTube Data API (поиск, плейлисты)
            yt_result = await youtube_command(full_action)
            yt_open = yt_result.get("open_youtube_url") or yt_result.get("open_url")
            if yt_open:
                _cmd_id = _register_command(f"open_youtube_url:{yt_open}", device_id or "laptop")
                await ws_dev.send(json.dumps({"type": "command", "action": f"open_youtube_url:{yt_open}", "id": _cmd_id}))
            if yt_result.get("items"):
                items_str = ", ".join(yt_result["items"][:3])
                _yt_reply = await ask_gemini(f"Нашла на YouTube: {items_str}. Скажи коротко.", save_history=False)
                if _yt_reply:
                    log.info(f"[голос] ответ: {_yt_reply!r}")
                    await stream_tts_to_device(_yt_reply, ws_dev, device_id or "laptop", literal=True)
        elif action.startswith("ext:") or action.startswith("browser:"):
            # Браузерные команды через агент
            _cmd_id = _register_command(full_action, device_id or "laptop")
            await ws_dev.send(json.dumps({"type": "command", "action": full_action, "id": _cmd_id}))
        elif action.startswith("music_") or action.startswith("music:"):
            # Яндекс Музыка через SMTC+API (на агенте)
            _cmd_id = _register_command(full_action, device_id or "laptop")
            await ws_dev.send(json.dumps({"type": "command", "action": full_action, "id": _cmd_id}))
            # «что сейчас играет» — не выдумываем: ждём результат агента и
            # озвучиваем реальные данные либо честное «не вижу, что играет»
            if action == "music:now_playing":
                await speak_now_playing_result(
                    _cmd_id, ws_dev, device_id or "laptop", bot)
                return
        elif full_action.startswith("open_app:") or full_action.startswith("close_window:"):
            dev = device_id or "laptop"
            tws = st.connected_devices.get(dev, ws_dev)
            _cmd_id = _register_command(full_action, dev)
            await tws.send(json.dumps({"type": "command", "action": full_action, "id": _cmd_id}))
            # запись запуска для умных дефолтов
            if full_action.startswith("open_app:"):
                try:
                    app_query = full_action.split(":", 1)[1]
                    await asyncio.to_thread(record_launch, app_query.lower())
                except Exception as e:
                    log.debug(f"[ws] _say: {type(e).__name__}: {e}")
        else:
            # Все остальные команды — на агент
            dev = device_id or "laptop"
            tws = st.connected_devices.get(dev, ws_dev)
            _cmd_id = _register_command(full_action, dev)
            await tws.send(json.dumps({"type": "command", "action": full_action, "id": _cmd_id}))

        # Провод 2: подтверждение команды с учётом статуса
        # Для music_, screenshot и music:now_playing — пропускаем
        # (ответ приходит отдельно: command_result → реальные данные/честный отказ)
        if (not full_action.startswith("screenshot:")
                and not full_action.startswith("music_")
                and full_action != "music:now_playing"):
            try:
                _disp = _disp_current()
                _cmd_status = st._pending_commands.get(_cmd_id, {}).get("status", "sent")
                _cmd_detail = st._pending_commands.get(_cmd_id, {}).get("detail", "")

                if _cmd_status == "executed":
                    _status_text = "Команда выполнена. Отреагируй одним предложением."
                elif _cmd_status == "failed":
                    _status_text = f"Команда не выполнена: {_cmd_detail}. Скажи честно, одним предложением."
                else:
                    _status_text = (
                        "Команда отправлена на устройство, результат ещё не известен. "
                        "Отреагируй естественно, одним коротким предложением, "
                        "НЕ утверждая что уже сделано (нельзя: \"открыла\", \"сделала\"; "
                        "можно: \"сейчас\", \"открываю\")."
                    )

                _cmd_confirm = (
                    f"Мастер попросил: {text}. Команда: {full_action}. "
                    f"СТАТУС КОМАНДЫ: {_status_text} "
                    f"Твоя диспозиция: {_disp['stance']}, "
                    f"valence={_disp['valence']}, arousal={_disp['arousal']}."
                )
                _creply = await ask_gemini(_cmd_confirm, save_history=False)
                if _creply:
                    log.info(f"[голос] ответ: {_creply!r}")
                    await stream_tts_to_device(
                        _creply, ws_dev, device_id or "laptop", literal=True)
            except Exception as e:
                log.debug(f"[ws] _say: {type(e).__name__}: {e}")

        # Провод 3: действие становится эпизодом
        try:
            from modules.disposition import current as _disp_ep
            _dep = _disp_ep()
            add_episode(
                text=f"Выполнила команду: {text[:80]} → {full_action}",
                emotion=_dep["stance"],
                valence=_dep["valence"],
                arousal=_dep["arousal"],
                context=data.get("active_window", ""),
            )
        except Exception as e:
            log.debug(f"[ws] _say: {type(e).__name__}: {e}")

        return

    elif _routed and not ws_dev:
        _offline_action = _routed.get("action", "")
        if _offline_action and not _offline_action.startswith("screenshot:") and not _offline_action.startswith("music_"):
            try:
                _disp = _disp_current()
                _cmd_confirm = (
                    f"Мастер попросил: {text}. Команда: {_offline_action}. "
                    f"СТАТУС КОМАНДЫ: Устройство offline, выполнить нельзя. "
                    f"Скажи честно, без обещаний повторить. "
                    f"Твоя диспозиция: {_disp['stance']}, "
                    f"valence={_disp['valence']}, arousal={_disp['arousal']}."
                )
                _creply = await ask_gemini(_cmd_confirm, save_history=False)
                if _creply:
                    log.info(f"[голос] ответ: {_creply!r}")
                    await bot.send_message(MASTER_ID, _creply)
            except Exception as e:
                log.debug(f"[ws] _say: {type(e).__name__}: {e}")

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
