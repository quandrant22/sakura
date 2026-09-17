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

# ─────────────────────────────────────────────
#  Инициализация
# ─────────────────────────────────────────────

logging.basicConfig(level=logging.INFO)
log = logging.getLogger(__name__)

bot = Bot(token=TELEGRAM_TOKEN)
dp  = Dispatcher()

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
#  Telegram — команды Мастера
# ─────────────────────────────────────────────

@dp.message(Command("help"))
async def cmd_help(message: Message):
    if not is_master(message.from_user.id):
        return
    await message.answer(device_commands.help_text())


@dp.message(Command("health"))
async def cmd_health(message: Message):
    if not is_master(message.from_user.id):
        return
    cpu  = psutil.cpu_percent(interval=0.5)
    ram  = psutil.virtual_memory()
    disk = psutil.disk_usage("/")
    load = os.getloadavg()
    up   = int(time.monotonic() - _START)
    await message.answer(
        f"Сервер:\n"
        f"CPU: {cpu:.0f}%  |  load: {load[0]:.2f} {load[1]:.2f} {load[2]:.2f}\n"
        f"RAM: {ram.percent:.0f}% ({ram.used >> 20} / {ram.total >> 20} МБ)\n"
        f"Диск: {disk.percent:.0f}% (свободно {disk.free >> 30} ГБ)\n"
        f"Аптайм: {up // 3600}ч {(up % 3600) // 60}м"
    )


@dp.message(Command("restart"))
async def cmd_restart(message: Message):
    if not is_master(message.from_user.id):
        return
    await message.answer("Перезапускаюсь, Мастер. Вернусь через пару секунд.")
    subprocess.Popen(["systemctl", "restart", "sakura.service"])


@dp.message(CommandStart())
async def cmd_start(message: Message):
    if not is_master(message.from_user.id):
        return
    reply = await ask_gemini("Мастер только что запустил бота. Поприветствуй коротко.")
    await message.answer(reply)


@dp.message(Command("status"))
async def cmd_status(message: Message):
    if not is_master(message.from_user.id):
        return
    await message.answer(get_device_status())


@dp.message(Command("memory"))
async def cmd_memory(message: Message):
    if not is_master(message.from_user.id):
        return
    ctx = db_get_memory_context()
    await message.answer(ctx if ctx else "Память пока пуста.")


@dp.message(Command("tasks"))
async def cmd_tasks(message: Message):
    if not is_master(message.from_user.id):
        return
    ctx = get_tasks_context()
    await message.answer(ctx if ctx else "Задач нет.")


@dp.message(Command("clear"))
async def cmd_clear(message: Message):
    if not is_master(message.from_user.id):
        return
    clear_history()
    clear_session_summary()
    reply = await ask_gemini("Мастер очистил историю диалога. Отреагируй коротко.")
    await message.answer(reply)


@dp.message(Command("чистыйлист"))
async def cmd_clean_slate(message: Message):
    if not is_master(message.from_user.id):
        return
    await clean_slate()
    await message.answer("Протокол выполнен. Я тебя не помню.")


@dp.message(Command("гости"))
async def cmd_guests(message: Message):
    """Мастер смотрит сводку переписок с гостями."""
    if not is_master(message.from_user.id):
        return
    await message.answer(get_guest_summaries())


@dp.message(Command("vip"))
async def cmd_vip(message: Message):
    if not is_master(message.from_user.id):
        return
    raw   = message.text.split(maxsplit=1)
    parts = [p.strip() for p in (raw[1] if len(raw) > 1 else "").split("|")]
    if len(parts) < 2 or not parts[0].isdigit():
        await message.answer(
            "Формат: /vip <id> | <имя> | <как вести себя>\n"
            "Пример: /vip 12345678 | Аня | Старая подруга. Тёплая, можно подкалывать, обсуждать что угодно."
        )
        return
    add_vip(int(parts[0]), parts[1], note="", personality=parts[2] if len(parts) > 2 else "")
    await message.answer(f"VIP добавлен: {parts[1]} (id={parts[0]}).")

@dp.message(Command("trusted"))
async def cmd_trusted(message: Message):
    if not is_master(message.from_user.id):
        return
    raw   = message.text.split(maxsplit=1)
    parts = [p.strip() for p in (raw[1] if len(raw) > 1 else "").split("|")]
    if len(parts) < 2 or not parts[0].isdigit():
        await message.answer("Формат: /trusted <id> | <имя> | <заметка>")
        return
    add_trusted(int(parts[0]), parts[1], note=parts[2] if len(parts) > 2 else "")
    await message.answer(f"Доверенный: {parts[1]} (id={parts[0]}).")

@dp.message(Command("users"))
async def cmd_users(message: Message):
    if not is_master(message.from_user.id):
        return
    await message.answer(list_users())

@dp.message(Command("unvip"))
async def cmd_unvip(message: Message):
    if not is_master(message.from_user.id):
        return
    raw = message.text.split(maxsplit=1)
    if len(raw) < 2 or not raw[1].strip().isdigit():
        await message.answer("Формат: /unvip <id>")
        return
    await message.answer("Удалён." if remove_user(int(raw[1].strip())) else "Не найден.")

@dp.message(Command("block"))
async def cmd_block(message: Message):
    if not is_master(message.from_user.id):
        return
    raw = message.text.split(maxsplit=1)
    if len(raw) < 2 or not raw[1].strip().isdigit():
        await message.answer("Формат: /block <id>")
        return
    block_user(int(raw[1].strip()))
    await message.answer("Заблокирован.")


# ─────────────────────────────────────────────
#  Telegram — управление ноутом
# ─────────────────────────────────────────────

#  Telegram — управление устройствами (/ноут, /пк, /скажи)

def _resolve_device(text_lower: str) -> tuple[str, str]:
    """Возвращает (device_id, остаток команды). /ноут → laptop, /пк → pc, /скажи → активное."""
    if text_lower.startswith("/ноут"):
        return "laptop", text_lower[5:].strip()
    if text_lower.startswith("/пк"):
        return "pc", text_lower[3:].strip()
    if text_lower.startswith("/скажи"):
        return (get_active_device() or "laptop"), "скажи " + text_lower[6:].strip()
    return "laptop", ""


@dp.message(F.text.startswith(("/ноут", "/пк", "/скажи")))
async def device_control(message: Message):
    if not is_master(message.from_user.id):
        return

    raw       = message.text
    low       = raw.lower()
    device_id, _ = _resolve_device(low)

    # остаток команды берём из исходного текста (с регистром), по длине префикса
    if low.startswith("/ноут"):    rest = raw[5:].strip()
    elif low.startswith("/пк"):    rest = raw[3:].strip()
    else:                          rest = "скажи " + raw[6:].strip()   # /скажи → активное устройство
    rest_low = rest.lower()

    dev_label = {"laptop": "ноут", "pc": "ПК"}.get(device_id, device_id) or device_id
    log.info(f"[/{dev_label}] {rest_low}")

    ws = connected_devices.get(device_id)
    if not ws:
        await message.answer(f"{dev_label.capitalize()} не подключён.")
        return

    try:
        if rest_low == "скриншот":
            await ws.send(json.dumps({"type": "command", "action": "screenshot:"}))
            await message.answer("Делаю скриншот...")
        elif rest_low.startswith("скажи "):
            phrase = rest[6:].strip()
            asyncio.create_task(stream_tts_to_device(phrase, ws, device_id, literal=True, emotion=get_current_emotion()))
            await message.answer(f"Говорю на {dev_label}: {phrase}")
        elif rest_low.startswith("открой "):
            arg    = rest[7:].strip()
            action = f"open_url:{arg}" if arg.startswith("http") else f"open_app:{arg}"
            await ws.send(json.dumps({"type": "command", "action": action}))
            await message.answer(f"Открываю: {arg}")
        elif rest_low.startswith("ютуб "):
            query = rest[5:].strip()
            await ws.send(json.dumps({"type": "command", "action": f"open_youtube:{query}"}))
            await message.answer(f"YouTube: {query}")
        elif rest_low.startswith("сайт "):
            url = rest[5:].strip()
            if not url.startswith("http"):
                url = "https://" + url
            await ws.send(json.dumps({"type": "command", "action": f"open_url:{url}"}))
            await message.answer(f"Открываю: {url}")
        else:
            await message.answer(
                f"Команды для {dev_label} (/ноут, /пк) и /скажи (на активное устройство):\n"
                "скриншот · скажи <текст> · открой <прил./http> · ютуб <запрос> · сайт <url>"
            )
    except Exception as e:
        log.error(f"[/{dev_label}] ошибка: {e}")
        await message.answer(f"Ошибка: {e}")


# ─────────────────────────────────────────────
#  Telegram — входящие сообщения
# ─────────────────────────────────────────────

@dp.message(F.text)
async def handle_message(message: Message):
    # Короткие реплики-реакции: не гоняем через командный роутер (экономия LLM)
    _TG_ROUTER_SKIP = {"привет", "приветик", "здравствуй", "здаров", "ладно",
                       "ок", "окей", "ага", "угу", "да", "нет", "спасибо",
                       "благодарю", "понял", "понятно", "класс", "круто",
                       "отлично", "давай", "хорошо", "доброе утро", "добрый вечер"}
    from modules.capsules import (is_capsule_request, parse_open_date,
        create_capsule, make_create_prompt)
    from modules.audio_control import handle_audio_command
    # ── Групповой чат ─────────────────────────────────────────────────────────
    if GROUP_CHAT_ID and message.chat.id == GROUP_CHAT_ID:
        user_id   = message.from_user.id
        user_name = message.from_user.full_name or "id=" + str(user_id)
        text      = message.text or ""
        role      = get_role(user_id)

        if message.from_user.is_bot and message.from_user.id == bot.id:
            return

        if role == "himari" or (message.from_user.is_bot and is_himari(user_id)):
            log.info("[группа/химари] " + text[:300])
            add_guest_message(user_id, "user", text, name="Химари")
            reply = await ask_gemini_as_guest(user_id, text, "Химари", "himari")
            await message.reply(reply)
            try:
                opinion_prompt = (
                    "В общем чате Химари написала: " + text[:200] + "\n"
                    "Ты ответила ей: " + reply[:200] + "\n\n"
                    "Поделись с Мастером своим наблюдением — одно предложение."
                )
                opinion = await ask_gemini(opinion_prompt, save_history=False)
                notif = "[химари] Химари: " + text[:120] + "\n\n" + opinion + "\n\n<- ответь чтобы обсудить"
                await send_to_master(notif, disable_notification=True)
            except Exception as e:
                log.error("Group himari notification error: " + str(e))
            return

        if role == "master":
            update_master_status(text)
            # Интим-режим: детект на каждое сообщение Мастера
            from modules.intimacy_mode import mark as _im_mark
            _im_mark(text)

        # Провод: проверка молчания → снижение близости
        try:
            from modules.relationship import check_silence_cooldown, decrease_closeness
            from modules.rituals import _load as _rituals_load
            _rit_state = _rituals_load()
            _last_int = _rit_state.get("last_interaction")
            _silence_delta = check_silence_cooldown(_last_int)
            if _silence_delta:
                decrease_closeness(_silence_delta, reason="молчание")
        except Exception as e:
            log.debug(f"[main] handle_message: {type(e).__name__}: {e}")

        mark_master_interaction()      # Фаза 1: ритуалы — время последнего взаимодействия
        mood_mark_interaction()        # Фаза 2: mood vector — инерция
        try:
            await asyncio.to_thread(update_master_mood, text, "text")
        except Exception as e:
            log.debug(f"[main] handle_message: {type(e).__name__}: {e}")

        # Фаза 4: органическая близость и трекинг тем
        try:
            await asyncio.to_thread(increase_closeness, 0.003)
            topics = await asyncio.to_thread(extract_topics_from_text, text)
            for topic in topics:
                await asyncio.to_thread(track_topic, topic)
        except Exception as e:
            log.debug(f"[main] handle_message: {type(e).__name__}: {e}")

        # Фаза 7 №50: трекинг словечек Мастера
        try:
            await asyncio.to_thread(track_speech, text)
        except Exception as e:
            log.debug(f"[main] handle_message: {type(e).__name__}: {e}")

        # №7/8: триггеры тем и усталость
        try:
            await asyncio.to_thread(track_topic_reaction, text)
        except Exception as e:
            log.debug(f"[main] handle_message: {type(e).__name__}: {e}")

        # №26: подколы в адрес Сакуры
        try:
            if detect_joke_about_sakura(text):
                await asyncio.to_thread(save_joke, text)
        except Exception as e:
            log.debug(f"[main] handle_message: {type(e).__name__}: {e}")

        # №39: голосовые заметки
        if is_voice_note_request(text):
            confirm = await save_voice_note(text)
            await message.reply(confirm)
            return

        # Фаза 4: капсула времени
        try:
            if is_capsule_request(text):
                open_date = parse_open_date(text)
                if open_date:
                    # Капсула создаётся ради сайд-эффекта записи в БД;
                    # ответ Мастеру формирует make_create_prompt(open_date)
                    await asyncio.to_thread(create_capsule, text, open_date)
                    await message.reply(make_create_prompt(open_date))
                    return
        except Exception as e:
            log.debug(f"[main] handle_message: {type(e).__name__}: {e}")

        # Фаза 3: цепочки действий
        try:
            chain = parse_chain(text)
            if chain:
                dev_id = next(iter(connected_devices), None)
                if dev_id:
                    chain_reply = await run_chain(
                        chain, connected_devices, ask_gemini,
                        lambda text, ws, dev, literal=False: stream_tts_to_device(
                            text, ws, dev, literal=literal, emotion=get_current_emotion()),
                        device_id=dev_id
                    )
                    await send_as_conversation(message.chat.id, chain_reply)
                    return
        except Exception as e:
            log.debug(f"[main] handle_message: {type(e).__name__}: {e}")

        # Фаза 4: команды аудио-устройств
        if text.startswith("/устройств"):
            reply = await handle_audio_command(text, connected_devices)
            await message.reply(reply)
            return

        log.info("[группа/гость] " + user_name + ": " + text[:300])
        reply = await ask_gemini_as_guest(user_id, text, user_name, "guest")
        await message.reply(reply)
        try:
            opinion_prompt = (
                "В общем чате некий " + user_name + " написал: " + text[:200] + "\n"
                "Ты ответила: " + reply[:200] + "\n\n"
                "Поделись с Мастером своим мнением — одно предложение."
            )
            opinion = await ask_gemini(opinion_prompt, save_history=False)
            notif = "[гость] " + user_name + " (id=" + str(user_id) + "): " + text[:120] + "\n\n" + opinion + "\n\n<- ответь чтобы обсудить"
            await send_to_master(notif, disable_notification=True)
        except Exception as e:
            log.error("Group guest notification error: " + str(e))
        return

    # ── Личный чат ─────────────────────────────────────────────────────────────
    user_id   = message.from_user.id
    role      = get_role(user_id)
    user_name = message.from_user.full_name or f"id={user_id}"

    # ── Гости и Химари ─────────────────────────────────────────────────────────
    if role != "master":
        text = message.text
        log.info(f"[{role}] {user_name}: {text[:300]}")

        await bot.send_chat_action(message.chat.id, "typing")
        reply = await ask_gemini_as_guest(user_id, text, user_name, role)
        await send_as_conversation(message.chat.id, reply)

        # Уведомляем Мастера с мнением Сакуры
        notification = format_master_notification(user_id, user_name, text, role)
        try:
            if role == "himari":
                opinion_prompt = (
                    f"Пока тебя не было, Химари написала боту: «{text[:200]}»\n"
                    f"Ты ответила ей: «{reply[:200]}»\n\n"
                    "Поделись с Мастером своим наблюдением об этом разговоре с Химари — "
                    "что она за персонаж, что заметила, как тебе это общение. "
                    "Одно-два предложения, как будто рассказываешь со стороны."
                )
            elif role in ("vip", "trusted"):
                vdata = get_user_data(user_id)
                who   = vdata.get("name", user_name)
                note  = vdata.get("note", "")
                opinion_prompt = (
                    f"Тебе написал {who} — это человек, которого Мастер отметил как близкого "
                    f"({'VIP' if role == 'vip' else 'доверенный'}{', ' + note if note else ''}).\n"
                    f"Он написал: «{text[:200]}»\nТы ответила: «{reply[:200]}»\n\n"
                    "Скажи Мастеру пару тёплых слов об этом — по-свойски, как о хорошем знакомом, "
                    "без оценок свысока. Одно предложение."
                )
            else:
                opinion_prompt = (
                    f"Боту написал гость ({user_name}): «{text[:200]}»\n"
                    f"Ты ответила: «{reply[:200]}»\n\n"
                    "Коротко поделись с Мастером наблюдением — что за человек, что хотел. "
                    "Спокойно и доброжелательно, без высокомерия и приговоров. Одно предложение."
                )
            opinion = await ask_gemini(opinion_prompt, save_history=False)
            # Тег [обсуждение] нужен чтобы reply на это сообщение попал в правильный обработчик
            tag = "[химари]" if role == "himari" else "[гость]"
            full_notification = (
                f"{tag} {notification}\n\n"
                f"💭 {opinion}\n\n"
                f"_← ответь на это сообщение чтобы обсудить_"
            )
            await send_to_master(full_notification, disable_notification=True)
        except Exception as e:
            log.error(f"Master notification error: {e}")
        return

    # ── Мастер ─────────────────────────────────────────────────────────────────
    text       = message.text
    text_lower = text.lower()
    _text_raw = text          # исходная реплика Мастера — для истории диалога
    # Обрезка только в ЛОГЕ (текст обрабатывается целиком) — 300 символов,
    # чтобы хвост фразы («… фром зе эшс») не выглядел потерянным
    log.info(f"[вход] {text[:300]!r}")
    update_master_status(text)

    # ── СТОП долгой озвучки (полного списка ачивок и др.) из Telegram ──
    try:
        from modules.state import (tts_is_reading, tts_request_stop_anywhere)
    except Exception:
        tts_is_reading = lambda *a, **k: False
        tts_request_stop_anywhere = lambda: 0
    _stop_txt = text_lower.strip().rstrip(".!?,")
    if _stop_txt in ("стоп", "хватит", "достаточно",
                     "останови чтение", "перестань читать", "хватит читать"):
        if tts_request_stop_anywhere():
            await bot.send_message(MASTER_ID, "Хорошо, остановилась.")
        return


    # ── v3 (этап 5): confirm-диалог реестра (system.shutdown/restart/sleep —
    # confirm: true, executor.py ставит Session.expect) проверяется ДО v2
    # _pending_system: подтверждение v3 — через ту же сессию, которую route()
    # опрашивает на первом шаге. Без этой ветки «да» после вопроса v3 падал
    # бы в v2-_pending_system (его там нет) и уходил в классификатор.
    try:
        from sakura_core.bridge import get_router as _v3_get_router
        _v3_router = _v3_get_router()
        if _v3_router.session.pending is not None:
            _v3_dec = _v3_router.route(text, None)
            if _v3_dec.source == "session" and _v3_dec.verdict is not None:
                if _v3_dec.verdict == "confirm" and _v3_dec.action:
                    laptop_ws, _active_dev = _get_active_ws()
                    if laptop_ws:
                        _cmd_full = _v3_dec.action.replace(".", ":", 1)
                        await execute_critical_action(_cmd_full, laptop_ws, _active_dev,
                                                      text, "", ask_gemini)
                        await message.answer("Готово.")
                    else:
                        await message.answer("Устройство отключилось, не могу выполнить.")
                else:
                    await message.answer("Хорошо, отменила.")
                return
    except Exception as _v3_conf_err:
        log.debug(f"[main] v3 confirm: {type(_v3_conf_err).__name__}: {_v3_conf_err}")

    # ── ПОДТВЕРЖДЕНИЕ ОПАСНОЙ СИСТЕМНОЙ КОМАНДЫ (shutdown/restart/sleep) ──
    # Тот же _pending_system, что и в голосовом пути (modules/ws_handlers.py).
    # Ключ "tg" — у Telegram-сообщения нет device_id, как и у голоса без устройства.
    if "tg" in _pending_system:
        _ps = _pending_system["tg"]
        if __import__("time").monotonic() - _ps["ts"] < 60:
            _ps_result = check_confirmation(text_lower)
            if _ps_result == "confirm":
                del _pending_system["tg"]
                laptop_ws, _active_dev = _get_active_ws()
                if laptop_ws:
                    await execute_critical_action(_ps["action"], laptop_ws, _active_dev, text, "", ask_gemini)
                    await message.answer("Готово.")
                else:
                    await message.answer("Устройство отключилось, не могу выполнить.")
                return
            elif _ps_result == "deny":
                del _pending_system["tg"]
                await message.answer("Хорошо, отменила.")
                return
            else:
                # Мастер сменил тему — отменяем подтверждение, обрабатываем реплику обычным путём
                del _pending_system["tg"]
        else:
            del _pending_system["tg"]

    # ── ПОДТВЕРЖДЕНИЕ ЗАБЫВАНИЯ («забудь про Х» → «да») ──
    # Тот же pending из voice_info, что и в голосовом пути (ws_handlers).
    from modules.voice_info import pending_forget_active as _pfa, memory_forget_confirm as _mfc
    if _pfa():
        _fg = _mfc(text)
        if _fg is not None:
            await message.answer(_fg[0])
            return

    # ── v3 (этап 3): быстрый путь реестра для музыки ────────────────
    # Реестр без LLM; действие уходит агенту каноническим id. Временный
    # крюк: на этапах 5-6 ветки старого пути вынимаются вместе с ним.
    async def _resolve_conv_reply(_r):
        """Ответ разговорного слоя: LLM-подтверждения, отправки, steam.
        Слой отдаёт данные, поверхность исполняет своими зависимостями."""
        if _r.run_clean_slate:
            await clean_slate()
        if _r.ws_command:
            _lws, _ldev = _get_active_ws()
            if not _lws:
                await message.answer(_r.fallback_text or "Ноутбук оффлайн.")
                return
            await _lws.send(json.dumps(
                {"type": "command", "action": _r.ws_command}))
        composed = None
        if _r.prompt:
            composed = await ask_gemini(_r.prompt, save_history=False)
        for _act in _r.actions:
            if _act[0] == "steam_recommend":
                games = await recommend_games(limit=5)
                if games:
                    game_list = "\n".join(
                        f"• {g['name']} ({g.get('playtime_forever', 0) // 60}ч)"
                        for g in games)
                    reply = await ask_gemini(
                        f"Мастер спрашивает во что поиграть. Вот его библиотека:\n{game_list}\n\n"
                        f"Порекомендуй 2-3 игры с коротким объяснением почему именно они. "
                        f"В своём стиле, не как список.")
                    await send_as_conversation(message.chat.id, reply)
                return
            if _act[0] == "steam_guide":
                # Текущая игра — из глобального состояния модуля.
                from modules.steam_integration import _current_game
                game_name = _current_game.get("name") if _current_game else None
                if not game_name:
                    for g in get_library():
                        if g["name"].lower() in text.lower():
                            game_name = g["name"]
                            break
                if game_name:
                    guide = await find_guide(game_name, text)
                    if guide["text"]:
                        sakura_reply = await ask_gemini(
                            f"Перескажи этот гайд по игре {game_name} своими словами, в своём стиле:\n{guide['text']}")
                        await send_as_conversation(message.chat.id, sakura_reply)
                        for img_url in guide["images"][:2]:
                            try:
                                await bot.send_photo(message.chat.id, photo=img_url)
                            except Exception as e:
                                log.debug(f"[main] conv reply: {type(e).__name__}: {e}")
                return
        if _r.send_tg:
            vip_id, raw, vip_name = _r.send_tg
            try:
                to_send = _strip_tone(composed) if raw is None else raw
                await bot.send_message(int(vip_id), to_send)
                await message.answer(f"Передала {vip_name.capitalize()}: «{to_send}»")
            except Exception as e:
                log.error(f"text->vip SEND FAIL: {e}")
                await message.answer("Не получилось отправить.")
            return
        _out = composed if composed is not None else _r.text
        if _out:
            await send_as_conversation(message.chat.id, _out)

    try:
        from sakura_core.bridge import v3_fast_path
        _laptop_ws, _laptop_dev = _get_active_ws()
        if await v3_fast_path(text, data={"active_window": ""},
                              device_ws=_laptop_ws, device_id=_laptop_dev,
                              register_command=None, ack=message.answer,
                              resolve_reply=_resolve_conv_reply):
            return
    except Exception as _v3_err:
        log.debug(f"[v3] быстрый путь: {type(_v3_err).__name__}: {_v3_err}")

    # Переводчик, игра в слова, калькулятор, печенье и страхи —
    # разговорный слой conversation/ (этап 5, 3/3): разбираются в
    # router.route() между реестром и LLM.
    # ── ИНФОРМАЦИОННЫЕ КОМАНДЫ (ачивки/сервер/задачи/погода/...) ──

    # ── ИНФОРМАЦИОННЫЕ КОМАНДЫ (ачивки/сервер/задачи/погода/...) ──
    # Тот же путь, что у голоса (voice_info.handle + answer_voice_info).
    # Ставим ДО системных команд и обычного разговора.
    # Reply на сообщение = продолжение разговора — команды там не ждут.
    # Короткие реплики-реакции не гоняем через роутер зря (он бы дёрнул LLM).
    _tg_short = text_lower.strip().rstrip("!.?,")
    if (not message.reply_to_message
            and _tg_short not in _TG_ROUTER_SKIP
            and len(_tg_short.split()) > 1):
        try:
            _tg_routed = await route_command(text, context=None)
        except Exception as e:
            log.debug(f"[main] info route: {type(e).__name__}: {e}")
            _tg_routed = None
        if _tg_routed and is_info_action(_tg_routed.get("action", "")):
            import modules.state as _st
            _st._last_command_ts = __import__("time").monotonic()
            log.info(f"[tg/voice_info] {text[:300]!r} → {_tg_routed}")
            await answer_voice_info(
                _tg_routed.get("action", ""), _tg_routed.get("arg", "") or "",
                text, None, None, ask_gemini, bot)
            return

    # Написать VIP — в conversation/vip_message (этап 5, 3/3).
    # «Протокол чистый лист» и правила обращения — в conversation/
    # (clean_slate и remember_kv, этап 5, 3/3).
    reply_ctx = _get_reply_context(message)

    # ── Reply на уведомление о госте/Химари → режим обсуждения ────────────────
    if message.reply_to_message:
        replied_text = (message.reply_to_message.text or "").strip()
        is_guest_notification  = replied_text.startswith("[гость]")
        is_himari_notification = replied_text.startswith("[химари]")
        if is_guest_notification or is_himari_notification:
            who = "Химари" if is_himari_notification else "гостя"

            # Извлекаем ID гостя из тега уведомления и обновляем отношение
            if is_guest_notification and not is_himari_notification:
                import re as _re
                id_match = _re.search(r'id=(\d+)', replied_text)
                if id_match:
                    guest_uid = int(id_match.group(1))
                    detected  = detect_relation_from_text(text)
                    if detected is not None:
                        set_relation(guest_uid, detected, note=text[:150])
                    elif text.strip():
                        # Сохраняем слова Мастера как заметку даже без явного уровня
                        from modules.guest_relations import get_relation as _gr
                        current_level = _gr(guest_uid)["level"]
                        set_relation(guest_uid, current_level, note=text[:150])

            discuss_prompt = (
                f"Мастер отвечает на твоё наблюдение о переписке с {who}.\n"
                f"Твоё наблюдение было: «{replied_text[:300]}»\n"
                f"Мастер говорит: «{text}»\n\n"
                f"Продолжи разговор с Мастером об этом — обсудите {who}, "
                f"его сообщение, ситуацию. Отвечай живо, как в обычном разговоре."
            )
            await bot.send_chat_action(message.chat.id, "typing")
            reply = await ask_gemini(discuss_prompt)
            await send_as_conversation(message.chat.id, reply)
            return

    # «Запомни app = path» — в conversation/remember_kv (этап 5, 3/3).
    # Скриншот уходит через реестр (screenshot.run, триггер «скрин» и др.)
    # — нормализация текста не нужна (этап 5, 2/2).

    tl_check = text.lower()

    # Игровой режим переехал в реестр (game_mode.on/off, этап 5 2/2) —
    # ветка parse_game_mode_command снята. Замечание: разговорная защита
    # этой ветки («что думаешь про игровой режим») в реестре не повторена —
    # fuzzy-матчинг по границам слов может сработать на упоминании в разговоре.

    asked   = parse_device_from_text(text)
    dev_id  = asked or next(iter(get_online_devices()), None) or "laptop"
    chosen  = {"dev": dev_id}
    def _resolve(q):
        d, t = resolve_app(q, dev_id)
        if t and not asked:
            chosen["dev"] = d
        return t
    actions = device_commands.parse(text, _resolve)
    if actions:
        dev   = chosen["dev"]
        ws    = connected_devices.get(dev)
        label = {"laptop": "ноут", "pc": "ПК", "phone": "телефон"}.get(dev, dev)
        if not ws:
            await message.answer(f"{label} не подключён, Мастер.")
            return
        done = []
        for action, human in actions:
            if action.startswith("say:"):
                asyncio.create_task(stream_tts_to_device(action[4:], ws, dev, literal=True, emotion=get_current_emotion()))
            else:
                await ws.send(json.dumps({"type": "command", "action": action}))
            done.append(human)
            await asyncio.sleep(0.3)
        await message.answer(f"{label}: " + ", ".join(done))
        return

    # Steam: «во что поиграть» и гайды — в conversation/games
    # (этап 5, 3/3), исполнение в _resolve_conv_reply.
    _t0 = __import__("time").monotonic()
    reply = await ask_gemini(_text_raw + reply_ctx)
    log.info(f"[ответ] {__import__('time').monotonic()-_t0:.1f}с | {reply!r}")
    await send_as_conversation(message.chat.id, reply)

    # Реакция (GIF/стикер) после ответа — в Telegram
    try:
        from modules.mood_vector import get_current as _mood_get_tg
        _mv_tg = _mood_get_tg()
        if should_react(text, _mv_tg.get("valence", 0.0), _mv_tg.get("arousal", 0.3)):
            reaction = detect_reaction(text, _mv_tg.get("valence", 0.0), _mv_tg.get("arousal", 0.3))
            if reaction:
                sticker = None
                try:
                    from modules.reactions import get_random_sticker
                    sticker = get_random_sticker(reaction["emotion"])
                except Exception as e:
                    log.debug(f"[main] _resolve: {type(e).__name__}: {e}")
                if sticker:
                    try:
                        await bot.send_sticker(message.chat.id, sticker)
                    except Exception as e:
                        log.debug(f"[main] _resolve: {type(e).__name__}: {e}")
                else:
                    gif = get_random_gif(reaction["emotion"])
                    if gif:
                        try:
                            await bot.send_animation(message.chat.id, gif)
                        except Exception as e:
                            log.debug(f"[main] _resolve: {type(e).__name__}: {e}")
    except Exception as e:
        log.debug(f"[main] _resolve: {type(e).__name__}: {e}")


@dp.message(F.voice)
async def handle_voice(message: Message):
    if not is_master(message.from_user.id):
        return
    await bot.send_chat_action(message.chat.id, "typing")
    file = await bot.get_file(message.voice.file_id)

    with tempfile.NamedTemporaryFile(suffix=".ogg", delete=False) as f:
        temp_ogg = f.name
    await bot.download_file(file.file_path, temp_ogg)

    try:
        from pydub import AudioSegment
        audio    = AudioSegment.from_ogg(temp_ogg)
        temp_wav = temp_ogg.replace(".ogg", ".wav")
        audio.export(temp_wav, format="wav")
        os.unlink(temp_ogg)
    except Exception as e:
        await message.answer(f"Ошибка конвертации: {e}")
        return

    try:
        key    = get_active_key()
        client = get_client(key)
        with open(temp_wav, "rb") as f:
            audio_b64 = base64.b64encode(f.read()).decode()
        os.unlink(temp_wav)

        r = await _llm_generate(
            [types.Content(parts=[
                types.Part(inline_data=types.Blob(mime_type="audio/wav", data=audio_b64)),
                types.Part(text="Распознай речь, верни только текст."),
            ])],
            model=MAIN_MODEL,
        )
        recognized = r
        mark_key_used(key)

        if not recognized:
            await message.answer("Не смогла разобрать.")
            return
        reply = await ask_gemini(recognized)
        await send_as_conversation(message.chat.id, reply)
    except Exception as e:
        await message.answer(f"Ошибка: {e}")


@dp.message(F.photo)
async def handle_photo(message: Message):
    if not is_master(message.from_user.id):
        return
    await bot.send_chat_action(message.chat.id, "typing")
    photo = message.photo[-1]
    file  = await bot.get_file(photo.file_id)

    with tempfile.NamedTemporaryFile(suffix=".jpg", delete=False) as f:
        temp_jpg = f.name
    await bot.download_file(file.file_path, temp_jpg)

    try:
        key    = get_active_key()
        client = get_client(key)
        with open(temp_jpg, "rb") as f:
            img_b64 = base64.b64encode(f.read()).decode()
        os.unlink(temp_jpg)

        caption   = message.caption or "Опиши что на фото — коротко, в своём стиле."
        reply_ctx = _get_reply_context(message)
        r = await _llm_generate(
            [types.Content(parts=[
                types.Part(inline_data=types.Blob(mime_type="image/jpeg", data=img_b64)),
                types.Part(text=caption + reply_ctx),
            ])],
            system=get_system_prompt(),
            model=MAIN_MODEL,
            max_tokens=600,
            temperature=0.85,
        )
        mark_key_used(key)
        reply = clean_reply(r)
        add_to_history("user",  f"[Фото] {caption}")
        add_to_history("model", reply)
        await send_as_conversation(message.chat.id, reply)
    except Exception as e:
        await message.answer(f"Ошибка: {e}")


# ─────────────────────────────────────────────
#  Видео от мастера
# ─────────────────────────────────────────────

@dp.message(F.video)
async def handle_video(message: Message):
    if not is_master(message.from_user.id):
        return
    await bot.send_chat_action(message.chat.id, "upload_video")

    # Ограничение размера — Gemini принимает до ~20MB
    video = message.video
    if video.file_size and video.file_size > 20 * 1024 * 1024:
        await message.reply("Видео слишком большое (>20MB). Обрежь до нужного фрагмента.")
        return

    await message.reply("Смотрю...")

    file = await bot.get_file(video.file_id)
    with tempfile.NamedTemporaryFile(suffix=".mp4", delete=False) as f:
        tmp_path = f.name
    await bot.download_file(file.file_path, tmp_path)

    try:
        key    = get_active_key()
        client = get_client(key)

        with open(tmp_path, "rb") as f:
            video_b64 = base64.b64encode(f.read()).decode()
        os.unlink(tmp_path)

        caption   = message.caption or "Посмотри это видео и расскажи что происходит — коротко, в своём стиле."
        reply_ctx = _get_reply_context(message)

        r = await _llm_generate(
            [types.Content(parts=[
                types.Part(inline_data=types.Blob(
                    mime_type="video/mp4",
                    data=video_b64
                )),
                types.Part(text=caption + reply_ctx),
            ])],
            system=get_system_prompt(),
            model=MAIN_MODEL,
            max_tokens=800,
            temperature=0.85,
        )
        mark_key_used(key)
        reply = clean_reply(r)
        add_to_history("user",  f"[Видео] {caption}")
        add_to_history("model", reply)
        await send_as_conversation(message.chat.id, reply)

    except Exception as e:
        log.error(f"[video] {e}")
        try: os.unlink(tmp_path)
        except Exception as e:
            log.debug(f"[main] handle_video: {type(e).__name__}: {e}")
        await message.reply(f"Не смогла обработать видео: {e}")


@dp.message(F.video_note)
async def handle_video_note(message: Message):
    """Видео-кружочки от мастера."""
    if not is_master(message.from_user.id):
        return
    await bot.send_chat_action(message.chat.id, "typing")

    file = await bot.get_file(message.video_note.file_id)
    with tempfile.NamedTemporaryFile(suffix=".mp4", delete=False) as f:
        tmp_path = f.name
    await bot.download_file(file.file_path, tmp_path)

    try:
        key    = get_active_key()
        client = get_client(key)

        with open(tmp_path, "rb") as f:
            video_b64 = base64.b64encode(f.read()).decode()
        os.unlink(tmp_path)

        r = await _llm_generate(
            [types.Content(parts=[
                types.Part(inline_data=types.Blob(
                    mime_type="video/mp4",
                    data=video_b64
                )),
                types.Part(text="Это видео-кружочек от Мастера. Отреагируй на него в своём стиле."),
            ])],
            system=get_system_prompt(),
            model=MAIN_MODEL,
            max_tokens=400,
            temperature=0.9,
        )
        mark_key_used(key)
        reply = clean_reply(r)
        add_to_history("user",  "[Видео-кружочек]")
        add_to_history("model", reply)
        await send_as_conversation(message.chat.id, reply)

    except Exception as e:
        log.error(f"[video_note] {e}")
        try: os.unlink(tmp_path)
        except Exception as e:
            log.debug(f"[main] handle_video_note: {type(e).__name__}: {e}")
        await message.reply("Не смогла посмотреть кружочек.")


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