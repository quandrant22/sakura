import asyncio
import inspect
import logging
import json
import base64
import hashlib
import os
import random
import re
import uuid
from modules.fuzzy import phrase_has_any as _fz, phrase_has as _fz1
import tempfile
import time
import subprocess
import psutil
import websockets
from datetime import datetime, date
from aiogram import Bot, Dispatcher, F
from aiogram.types import Message, BufferedInputFile, LinkPreviewOptions
from aiogram.filters import CommandStart, Command
from google import genai
from google.genai import types

from modules.calendar_module import get_urgent_event
from config import TELEGRAM_TOKEN, MASTER_ID, GROUP_CHAT_ID, get_active_key, mark_key_used, mark_key_exhausted, MAIN_MODEL, FALLBACK_MODEL  # noqa
from personality import get_system_prompt, get_time_context
from modules.web_search import needs_search, facts_prompt, format_sources
from memory.memory import (
    add_to_history, get_history, clear_history,
    needs_daily_analysis, mark_analysis_done,
    load_session_summary, save_session_summary,
    clear_session_summary, should_summarize
)
from modules.device_manager import (
    get_device_status,
    set_device_offline, parse_device_from_text,
    get_online_devices, load_devices,
    # get_active_device берётся из presence_sync (ниже) — версия device_manager не используется
)
from modules.context import get_full_context
from modules.jsonio import save_json
from modules.timeline import extract_and_save_from_dialogue
from modules.mood_vector import mark_interaction, auto_detect_mood_from_reply
from modules.proactive import (
    can_send_message, mark_sent, get_fact_trigger, update_master_status,
    get_silence_context, load_state, has_recent_semantic_duplicate,
)
from modules.tasks import (
    add_task, get_due_tasks, get_upcoming_tasks,
    mark_notified, get_tasks_context, extract_tasks_from_text
)
from modules import device_commands
from modules.tts_server import stream_tts_to_device, warmup_cache, strip_tone
from adapters.voice import stream_llm_to_tts  # v3: честный стриминг (этап 4)
from modules.state_arbiter import get_current_emotion
import modules.tts_server as tts_server


# _strip_tone перенесён в sakura_core/llm.py, реэкспорт
from sakura_core.llm import _strip_tone  # noqa: F811, E402
from modules.reflection import reflection_loop
from modules.intimacy_mode import reset_reflection_flag
from modules.mem_cache import apply_all_patches, get_json, set_json
from modules.ws_auth import check_token, is_master_device, reject, validate_secret_on_startup
from modules.rituals import (should_greet_device, get_greeting_prompt,
    should_farewell, get_farewell_prompt,
    mark_master_interaction, get_return_context)
from modules.mood_vector import (get_mood_context as get_mood_vector_context,
    auto_detect_from_llm, mark_interaction as mood_mark_interaction,
    get_orb_params, get_tts_params,
    update_master_mood, get_master_mood_hint)
from modules.mood_broadcast import broadcast_mood_after_reply
from modules.briefing import should_brief, run_briefing
from modules.window_watcher import update as watcher_update, is_quiet_mode
from modules.chains import (
    parse_chain, run_chain, parse_chain_from_llm,
    add_custom_chain, get_custom_chain, list_custom_chains, delete_custom_chain,
    add_voice_trigger, match_voice_trigger, list_voice_triggers, delete_voice_trigger,
)
from modules.presence_sync import (update as ps_update, set_offline as ps_offline,
    get_active_device, check_device_transfer, broadcast_transfer, get_context_for_device)
# ^ get_active_device — единственная используемая версия (presence_sync),
#   переопределяла бы версию из device_manager, поэтому там она убрана.
from modules.memory_honesty import enrich_memory_context
from modules.evening_pulse import should_send_pulse, mark_pulse_sent, get_pulse_prompt, check_pc_health
from modules.vps_monitor import start_monitor
from modules.threads import extract_threads
from sakura_core.llm import generate as _llm_generate, get_client
from modules.relationship import (check_milestone, increase_closeness, get_closeness_hint,
    track_topic, extract_topics_from_text,
    should_write_journal, get_growth_journal_prompt, mark_journal_written)
from modules.episodes import add_episode, get_recall
from modules.discord_bot      import start_bot as discord_start_bot, is_discord_priority, register_agent_request
from modules.command_router import route_command, route_critical, is_irreversible, EXEC_THRESHOLD, GRAY_THRESHOLD
from modules.intent_classifier import classify_intent, is_command, is_question, IntentResult
from modules.game_hub import get_game_context_for_device, set_game_mood  # noqa: F401 (используются в ws-путях)
from modules.reminders import (
    parse_reminder, add_reminder, format_reminders_list,
    set_callback as set_reminder_callback, check_loop as reminder_check_loop,
)
from modules.music_memory import (
    track_play, format_recent, format_top,
    get_recent, get_top_artists, get_top_tracks,
)
from modules.pranks import should_prank, choose_prank, record_prank
from modules.reactions import detect_reaction, get_random_gif, should_react
from modules.steam_integration import (
    load_library, get_current_game, recommend_games,
    find_guide,
    get_library, search_game,
    steam_library_loop,
    steam_achievements_loop, set_achievement_callback,
)
from modules.weather         import get_weather, apply_weather_to_mood, get_weather_context
from modules.game_detector   import detect_game_from_screenshot, get_game_context, get_cached_game, should_check_event, detect_game_event, make_event_prompt
from modules.secret_diary    import get_leak_hint, write_entry as diary_write
from modules.sakura_narrative import ensure_narrative
from modules.speech_style    import track_message as track_speech
from modules.proactive_recs  import track_activity as track_rec_activity
from modules.emotional_memory import (
    track_topic_reaction, detect_joke_about_sakura,
    save_joke
)
from modules.autonomous import (
    is_voice_note_request, save_voice_note, get_unreminded_notes,
    mark_reminded, update_sprint
)
from modules.integrations import (
    check_new_achievements, make_achievement_prompt,
    get_current_music_from_window, should_comment_music,
    make_music_comment_prompt, mark_music_commented
)
from memory.db import ensure_ready, add_to_category as db_add_to_category, get_memory_context as db_get_memory_context, add_to_self
from modules.users import (
    get_role, is_master, is_himari,
    get_guest_history, add_guest_message,
    get_guest_display_name, get_guest_summaries,
    format_master_notification, get_user_data,
    add_vip, add_trusted, remove_user, block_user, list_users,
)
from modules.user_prompts import get_role_system_addendum
from modules.guest_relations import (
    get_relation, set_relation, adjust_relation,
    detect_relation_from_text, get_relation_prompt,
)
# get_context_for_prompt (fortune_cookie) импортируется лениво внутри _build_system:
# сбой модуля не должен ронять сборку промпта
from modules.state import (
    connected_devices, _pending_event_check, _pending_describe,
    _pending_commands, _pending_clarify, _last_executed,
    _pending_plan, _plan_cancel, _last_command_ts, _current_track,
    _pending_system, check_confirmation,
)
from modules.ws_handlers import (
    handle_register, handle_ping, handle_apps_list, handle_screen_context,
    handle_command_result, handle_kettle_ready, handle_notification,
    handle_tg_message, handle_voice_command, update_current_track,
    execute_critical_action,
    answer_voice_info,
)
from modules.voice_info import is_info_action

# Новые модули (stage 7D)
from modules.app_mapping import find_in_mapping, resolve_app, find_vip_by_name
from sakura_core.memory_tasks import (
    extract_and_remember, summarize_session, daily_analysis, clean_slate,
)
from sakura_core.apps import analyze_apps, analyze_screen_context

# Telegram: bot, dp, handlers — все перенесены в adapters/telegram.py
from adapters.telegram import (  # noqa: F811
    bot, dp, send_to_master, send_telegram_text, send_safe, send_as_conversation,
    _split_into_parts, voice_to_tg, strip_payload_words, has_tg_trigger,
    handle_message, handle_voice, handle_photo, handle_video, handle_video_note,
    cmd_help, cmd_health, cmd_restart, cmd_start, cmd_status, cmd_memory,
    cmd_tasks, cmd_clear, cmd_clean_slate, cmd_guests, cmd_vip, cmd_trusted,
    cmd_users, cmd_unvip, cmd_block, device_control,
)

# ─────────────────────────────────────────────
#  Инициализация
# ─────────────────────────────────────────────

logging.basicConfig(level=logging.INFO)
log = logging.getLogger(__name__)

PLAN_WAIT_ACK = True  # агент теперь шлёт ack для каждой команды

# WebSocket-команды перенесены в adapters/voice.py (commit 6, stage 6)
from adapters.voice import (  # noqa: F811, E402
    _cleanup_pending_commands,
    _register_command,
    _resolve_command_status,
    _get_active_ws,
)

# Основная модель задаётся в config.py (env MAIN_MODEL), здесь не дублируется

# _thinking, NO_SAFETY перенесены в sakura_core/llm.py (commit 2B)

# ─────────────────────────────────────────────
#  Плейлисты
# ─────────────────────────────────────────────

YANDEX_PLAYLISTS = {
    "japan":         {"kind": 1011, "title": "Japan"},
    "офф-роуд":      {"kind": 1009, "title": "Off-road"},
    "off-road":      {"kind": 1009, "title": "Off-road"},
    "долгая дорога": {"kind": 1008, "title": "Долгая дорога"},
    "наше лето":     {"kind": 1007, "title": "Наше Лето"},
    "избранное":     {"kind": 1006, "title": "Избранное"},
    "stim":          {"kind": 1005, "title": "Stim"},
    "постройки":     {"kind": 1004, "title": "Постройки"},
    "покатушки":     {"kind": 1003, "title": "Покатушки"},
    "граффити":      {"kind": 1000, "title": "Граффити с любимой"},
    "волна":         {"kind": None, "title": "Моя волна"},
}

YANDEX_UID = "adebtrern"

# ─────────────────────────────────────────────
#  Парсинг команд устройства
# ─────────────────────────────────────────────


# ─────────────────────────────────────────────
#  Утилиты
# ─────────────────────────────────────────────

# clean_reply перенесён в sakura_core/llm.py, реэкспорт
from sakura_core.llm import clean_reply  # noqa: F811, E402

# Telegram-утилиты перенесены в adapters/telegram.py (commit 5, stage 6)
from adapters.telegram import (  # noqa: F811, E402
    send_to_master,
    send_telegram_text,
    send_safe,
    _split_into_parts,
    send_as_conversation,
)


# _gemini_client → sakura_core/llm.get_client; _run → sakura_core/llm.generate


# ─────────────────────────────────────────────
#  Контекст reply (перенесено в sakura_core/prompt.py, реэкспорт)
# ─────────────────────────────────────────────
from sakura_core.prompt import _get_reply_context  # noqa: F811


# ─────────────────────────────────────────────
#  Веб / URL
# ─────────────────────────────────────────────
# maybe_fetch_web, maybe_read_url перенесены в sakura_core/llm.py
# ─────────────────────────────────────────────
from sakura_core.llm import maybe_fetch_web, maybe_read_url  # noqa: F811, E402


# ─────────────────────────────────────────────
#  Генерация изображений
# ─────────────────────────────────────────────



# _translate_en → adapters/voice.py
# analyze_apps, _analyze_screen_context → sakura_core/apps.py

_START = time.monotonic()

# find_in_mapping, resolve_app → modules/app_mapping.py
# _find_vip_by_name → modules/app_mapping.find_vip_by_name

# _clean_slate, extract_and_remember → sakura_core/memory_tasks.py




# ─────────────────────────────────────────────
#  Проактивные сообщения
# ─────────────────────────────────────────────
# ЗАКРЫТЫЙ СПИСОК ПОВОДОВ (решение Мастера): только факты из
# get_fact_trigger() — ачивка, диск/память/нагрузка сервера, устройство
# offline, долгая сессия. Свободные размышления удалены, поиск в
# проактиве запрещён: инициатора запроса нет — искать нечего.
# Напоминания (задачи/календарь) — не проактив, живут здесь же.

# Проактивный цикл перенесён в sakura_core/proactive.py (commit 3, stage 6)
from sakura_core.proactive import proactive_loop  # noqa: F811


# ─────────────────────────────────────────────
#  LLM — Мастер (перенесено в sakura_core/prompt.py, реэкспорт)
# ─────────────────────────────────────────────
from sakura_core.prompt import (  # noqa: F811
    build_identity_core,
    _build_voice_system,
    _build_system,
    _build_system_cache,
    _build_system_lock,
    _BUILD_SYSTEM_TTL,
    _voice_system_cache,
)

# Функции LLM перенесены в sakura_core/llm.py, реэкспорт
from sakura_core.llm import (  # noqa: F811
    _build_contents,
    _build_guest_contents,
    ask_gemini,
    ask_gemini_voice,
    ask_gemini_as_guest,
    _handle_gemini_error,
)


# ─────────────────────────────────────────────
#  WebSocket — устройства
# ─────────────────────────────────────────────

async def send_command_to_device(device_id: str, command: dict) -> bool:
    ws = connected_devices.get(device_id)
    if not ws:
        return False
    try:
        await ws.send(json.dumps(command))
        return True
    except Exception:
        return False


async def _execute_plan(plan: dict, master_key: str, ws_dev, device_id) -> tuple[bool, str]:
    """Исполняет план по шагам. Возвращает (успех, сообщение)."""
    import time as _pt
    steps = plan.get("steps", [])
    summary = plan.get("summary", "задача")

    for i, step in enumerate(steps):
        # Проверка отмены
        if _plan_cancel.get(master_key):
            _plan_cancel.pop(master_key, None)
            return False, f"План остановлен на шаге {i + 1} по запросу Мастера."

        action = step.get("action", "")
        arg = step.get("arg", "")

        # wait — пауза на сервере
        if action == "wait":
            try:
                wait_sec = min(int(arg), 10)
            except (ValueError, TypeError):
                wait_sec = 1
            await asyncio.sleep(wait_sec)
            continue

        # Отправка команды на агент
        if not ws_dev:
            return False, "Устройство offline, план не может быть выполнен."

        full_action = f"{action}:{arg}" if arg and ":" not in action else action
        _cmd_id = _register_command(full_action, device_id or "laptop")
        await ws_dev.send(json.dumps({"type": "command", "action": full_action, "id": _cmd_id}))

        # Ожидание ack (оптимистичный режим или реальный)
        if PLAN_WAIT_ACK:
            for _ in range(50):  # 10 сек / 0.2
                await asyncio.sleep(0.2)
                cmd = _pending_commands.get(_cmd_id, {})
                if cmd.get("status") in ("executed", "failed"):
                    if cmd["status"] == "failed":
                        return False, f"План остановлен на шаге {i + 1}: {full_action} — {cmd.get('detail', 'ошибка')}"
                    break
            else:
                return False, f"План остановлен на шаге {i + 1}: {full_action} — таймаут ожидания"
        else:
            # Оптимистичный режим — пауза 1с между шагами
            await asyncio.sleep(1.0)

    return True, f"План выполнен: {summary}"



async def ws_handler(websocket):
    from modules.web_search import search_and_fetch, needs_search, search_image, download_bytes
    from modules.youtube import youtube_command
    device_id = None
    try:
        async for raw in websocket:
            try:
                data     = json.loads(raw)
                msg_type = data.get("type")

                # Фаза 0: проверка токена на каждом сообщении
                if not check_token(data):
                    await reject(websocket, reason=f"invalid token on '{msg_type}'")
                    return

                # Фаза 0: деструктивные команды только от master-устройств
                dev_from_msg = data.get("device_id")
                if msg_type in ("voice_command", "apps_list"):
                    if not is_master_device(dev_from_msg):
                        await reject(websocket, reason=f"'{msg_type}' denied: not master device ({dev_from_msg!r})")
                        return

                # Собираем ctx для хендлеров
                _ctx = {
                    "ask_gemini": ask_gemini,
                    "ask_gemini_voice": ask_gemini_voice,
                    "send_safe": send_safe,
                    "_find_vip_by_name": find_vip_by_name,
                    "_translate_en": None,  # moved to adapters/voice.py
                    "_clean_slate": clean_slate,
                    "_execute_plan": _execute_plan,
                    "_register_command": _register_command,
                    "_resolve_command_status": _resolve_command_status,
                    "_get_active_ws": _get_active_ws,
                    "analyze_apps": analyze_apps,
                    "_analyze_screen_context": analyze_screen_context,
                    "_gemini_client": None,  # use sakura_core.llm.get_client
                    "bot": bot,
                    "PLAN_WAIT_ACK": PLAN_WAIT_ACK,
                }

                # Диспетчер: вызываем нужный хендлер
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

                # Трек device_id для finally-блока
                if msg_type in ("register", "ping", "voice_command"):
                    device_id = data.get("device_id")

                # Обновляем текущий трек из любого сообщения агента (независимо от типа)
                update_current_track(data)

            except Exception as e:
                log.error(f"[ws_handler] {e}")

    except websockets.exceptions.ConnectionClosed as e:
        log.debug(f"[main] ws_handler: {type(e).__name__}: {e}")
    finally:
        if device_id:
            set_device_offline(device_id)
            connected_devices.pop(device_id, None)
            await asyncio.to_thread(ps_offline, device_id)
            log.info(f"Устройство отключено: {device_id}")

            # Фаза 1: прощание
            if is_master_device(device_id) and should_farewell():
                farewell = await ask_gemini(get_farewell_prompt(), save_history=False)
                if farewell:
                    await send_to_master(farewell)


# ─────────────────────────────────────────────
#  Точка входа
# ─────────────────────────────────────────────

async def _init_japanese_vocab():
    """Инициализирует словарь японских слов."""
    await asyncio.sleep(5)
    try:
        from modules.learn_japanese import init_vocabulary
        await asyncio.to_thread(init_vocabulary)
    except Exception as e:
        log.error(f"[japanese] Ошибка инициализации: {e}")

async def _init_weather():
    """Загружает погоду при старте и применяет к mood."""
    await asyncio.sleep(3)
    # Устанавливаем координаты из конфига (не по IP сервера!)
    from modules.weather import set_location
    from config import MASTER_LAT, MASTER_LON
    if MASTER_LAT and MASTER_LON:
        set_location(MASTER_LAT, MASTER_LON)
    weather = await get_weather()
    if weather:
        await asyncio.to_thread(apply_weather_to_mood, weather)
        log.info(f"[weather] {weather['temp']}°C, {weather['desc']}")


def _guarded_add(cat: str, item: str):
    """Обёртка для reflection_loop: два барьера."""
    from modules.intimacy_mode import consume_check, is_intimate_content
    if consume_check():
        log.info("[memory] reflection write skipped: intimacy in window")
        return False
    if is_intimate_content(item):
        log.info(f"[memory] интимный фильтр (reflection): {item[:40]}")
        return False
    return db_add_to_category(cat, item)


async def main():
    validate_secret_on_startup()
    await asyncio.to_thread(ensure_ready)
    asyncio.create_task(ensure_narrative())        # Фаза 7: нарратив Сакуры
    asyncio.create_task(_init_japanese_vocab())    # Инициализация словаря японского
    asyncio.create_task(_init_weather())
    asyncio.create_task(load_library())            # Steam: загрузка библиотеки
    await start_monitor()                          # VPS мониторинг
    apply_all_patches()                   # Кэш: JSON-файлы читаются из памяти

    # Проверяем вехи отношений при старте
    milestone = await asyncio.to_thread(check_milestone)
    if milestone:
        async def _send_milestone():
            await asyncio.sleep(30)
            reply = await ask_gemini(milestone["prompt"], save_history=False)
            if reply:
                await send_to_master(reply)
        asyncio.create_task(_send_milestone())

    tts_server.start()
    asyncio.create_task(warmup_cache())   # Фаза 6: прогрев TTS-кэша

    # Напоминания: callback для голосового оповещения
    async def _reminder_cb(msg: str):
        ws, dev = _get_active_ws()
        if ws:
            await stream_tts_to_device(msg, ws, dev or "laptop", literal=True, emotion=get_current_emotion())
        await send_to_master(msg)
    set_reminder_callback(_reminder_cb)
    asyncio.create_task(reminder_check_loop())

    # Telegram User API мониторинг
    async def _tg_notif_cb(chat_name, sender, text, urgent):
        """Callback от tg_monitor → уведомление Мастеру."""
        import time as _t
        from modules.notification_tracker import add_notification
        add_notification("telegram", f"{sender} в {chat_name}", text)
        if urgent:
            ws, dev = _get_active_ws()
            if ws:
                prompt = (
                    f"Поступило важное сообщение в Telegram от {sender} в {chat_name}: «{text[:80]}». "
                    "Скажи Мастеру одной короткой фразой обратить внимание."
                )
                reply = await ask_gemini(prompt, save_history=False)
                if reply:
                    await stream_tts_to_device(reply, ws, dev or "laptop", literal=True, emotion=get_current_emotion())

    try:
        from modules.tg_monitor import get_monitor
        tg_mon = get_monitor()
        tg_mon.set_callback(_tg_notif_cb)
        asyncio.create_task(tg_mon.start())
    except Exception as e:
        log.warning(f"[tg_monitor] Не удалось запустить: {e}")

    ws_server = await websockets.serve(ws_handler, "0.0.0.0", 8765, max_size=None)

    # Steam ачивки: факт в Telegram (формат из закрытого списка поводов)
    async def _achievement_cb(game_name: str, ach: dict):
        """Новая ачивка — только факт, без LLM-реакции и без голоса."""
        ach_name = ach.get("name") or ach.get("apiname") or "достижение"
        text = f"Выбито достижение: {ach_name} ({game_name})."
        await send_telegram_text(MASTER_ID, text)
        mark_sent(topic="achievement", text=text)
    set_achievement_callback(_achievement_cb)

    # Discord бот в основном event loop (discord.py + voice_recv)
    asyncio.create_task(discord_start_bot())
    log.info("WebSocket сервер запущен на порту 8765")
    await asyncio.gather(
        dp.start_polling(bot),
        ws_server.wait_closed(),
        daily_analysis(),
        proactive_loop(),
        steam_library_loop(),
        steam_achievements_loop(),
        reflection_loop(
            bot                     = bot,
            master_id               = MASTER_ID,
            ask_gemini_fn           = ask_gemini,
            add_to_category_fn      = _guarded_add,
            clear_history_fn        = clear_history,
            save_session_summary_fn = save_session_summary,
            load_session_summary_fn = load_session_summary,
            get_history_fn          = get_history,
            on_night_done           = reset_reflection_flag,
        ),
    )


if __name__ == "__main__":
    asyncio.run(main())