import asyncio
import logging
import json
import base64
import os
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
from aiogram.types import Message, BufferedInputFile
from aiogram.filters import CommandStart, Command
from google import genai
from google.genai import types

from modules.calendar_module import get_calendar_context, get_urgent_event
from config import TELEGRAM_TOKEN, MASTER_ID, GROUP_CHAT_ID, get_active_key, mark_key_used, mark_key_exhausted  # noqa
from personality import get_system_prompt, get_time_context
from memory.memory import (
    add_to_history, get_history, clear_history,
    get_memory_context, add_to_category,
    needs_daily_analysis, mark_analysis_done,
    load_session_summary, save_session_summary,
    clear_session_summary, should_summarize
)
from modules.device_manager import (
    update_device, get_device_status, get_device_context,
    set_device_offline, parse_device_from_text,
    get_online_devices, load_devices, get_active_device
)
from modules.context import build_context_block, get_full_context, is_home_alone, is_gaming
from modules.timeline import get_timeline_context, get_achievements_context, extract_and_save_from_dialogue
from modules.mood_vector import get_mood_context, mark_interaction, auto_detect_mood_from_reply
from modules.proactive import (
    can_send_message, mark_sent, get_trigger, update_master_status,
    mark_work_event, get_silence_context
)
from modules.tasks import (
    add_task, get_due_tasks, get_upcoming_tasks,
    mark_notified, get_tasks_context, extract_tasks_from_text
)
from modules.rules import detect_rule, apply_rule, get_rules_context
from modules import device_commands
from modules.web_search import search_and_fetch, needs_search, search_image, download_bytes
from modules.tts_server import stream_tts_to_device, stream_llm_to_tts, warmup_cache
import modules.tts_server as tts_server
from modules.reflection import reflection_loop
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
from modules.window_watcher import update as watcher_update, is_quiet_mode, get_insight
from modules.chains import (
    parse_chain, run_chain, parse_chain_from_llm,
    add_custom_chain, get_custom_chain, list_custom_chains, delete_custom_chain,
    add_voice_trigger, match_voice_trigger, list_voice_triggers, delete_voice_trigger,
)
from modules.presence_sync import (update as ps_update, set_offline as ps_offline,
    get_active_device, check_device_transfer, broadcast_transfer, get_context_for_device)
from modules.memory_honesty import enrich_memory_context
from modules.evening_pulse import should_send_pulse, mark_pulse_sent, get_pulse_prompt, check_pc_health
from modules.vps_monitor import start_monitor, get_vps_context, get_vps_alert
from modules.threads import extract_threads, get_threads_context, get_thread_recall
from modules.capsules import (is_capsule_request, parse_open_date,
    create_capsule, get_due_capsules, mark_opened, make_open_prompt, make_create_prompt,
    should_create_sakura_capsule, create_sakura_capsule,
    get_due_sakura_capsules, mark_sakura_opened, make_sakura_open_prompt)
from modules.relationship import (check_milestone, increase_closeness, get_closeness_hint,
    get_interests_hint, track_topic, extract_topics_from_text,
    should_write_journal, get_growth_journal_prompt, mark_journal_written)
from modules.episodes import add_episode, get_recall
from modules.audio_control   import handle_audio_command
from modules.discord_bot      import start_bot as discord_start_bot, is_discord_priority, register_agent_request
from modules.youtube import youtube_command
from modules.command_router import route_command, route_critical, is_irreversible, EXEC_THRESHOLD, GRAY_THRESHOLD
from modules.intent_classifier import classify_intent, is_command, is_question, IntentResult
from modules.game_hub import get_game_context_for_device, set_game_mood, build_game_prompt_context
from modules.calculator import calculate
from modules.fortune_cookie import is_fortune_request, get_fortune, format_fortune
from modules.reminders import (
    parse_reminder, add_reminder, format_reminders_list,
    set_callback as set_reminder_callback, check_loop as reminder_check_loop,
)
from modules.translator import is_translation_request, try_quick_translate, build_translate_prompt
from modules.music_memory import (
    track_play, format_recent, format_top,
    get_recent, get_top_artists, get_top_tracks,
    like_artist, dislike_artist, has_opinion, get_taste_context, generate_taste_comment,
)
from modules.fears import detect_fear_trigger, get_fear_context, get_fear_response_for_weather
from modules.pranks import should_prank, choose_prank, record_prank
from modules.reactions import detect_reaction, get_random_gif, should_react
from modules.word_game import (
    is_word_game_request, start_game, get_random_word, format_word_teach,
    format_word_quiz, check_answer, record_score, get_score, end_game,
    is_game_active, find_word, format_word_of_the_day,
)
from modules.steam_integration import (
    load_library, get_current_game, recommend_games,
    find_guide, format_library_context, format_current_game_context,
    get_achievement_stats, get_library, search_game,
)
from modules.weather         import get_weather, apply_weather_to_mood, get_weather_context
from modules.game_detector   import detect_game_from_screenshot, get_game_context, get_cached_game, should_check_event, detect_game_event, make_event_prompt
from modules.secret_diary    import get_leak_hint, write_entry as diary_write
from modules.sakura_narrative import get_narrative_hint, ensure_narrative
from modules.speech_style    import track_message as track_speech, get_style_hint
from modules.proactive_recs  import track_activity as track_rec_activity, get_recommendation
from modules.emotional_memory import (
    track_topic_reaction, get_trigger_hint, detect_joke_about_sakura,
    save_joke, get_revenge_hint, get_version_hint, get_season_hint,
    should_send_thought, mark_thought_sent, generate_spontaneous_thought
)
from modules.autonomous import (
    is_voice_note_request, save_voice_note, get_unreminded_notes,
    mark_reminded, update_sprint, should_do_research, do_research
)
from modules.integrations import (
    check_new_achievements, make_achievement_prompt,
    get_current_music_from_window, should_comment_music,
    make_music_comment_prompt, mark_music_commented
)
from memory.db import ensure_ready, add_to_category as db_add_to_category, get_self_context, add_to_self
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
from modules.fortune_cookie import get_context_for_prompt as get_fortune_cookie_ctx

# ─────────────────────────────────────────────
#  Инициализация
# ─────────────────────────────────────────────

logging.basicConfig(level=logging.INFO)
log = logging.getLogger(__name__)

bot = Bot(token=TELEGRAM_TOKEN)
dp  = Dispatcher()

connected_devices: dict = {}
_pending_event_check: dict = {}  # device_id → True если ждём скриншот для event-тика
_pending_describe: dict = {}     # device_id → True если ждём скриншот для описания
_pending_commands: dict[str, dict] = {}  # cmd_id → {"action", "device", "ts", "status"}
_pending_clarify: dict[str, dict] = {}  # master_key → {"text", "main", "alt", "ts"}
_last_executed: dict[str, dict] = {}    # master_key → {"text", "action", "ts"}
_pending_plan: dict[str, dict] = {}     # master_key → {"text", "plan", "ts"}
_plan_cancel: dict[str, bool] = {}      # master_key → True если отмена
PLAN_WAIT_ACK = True  # агент теперь шлёт ack для каждой команды


def _cleanup_pending_commands():
    """Удаляет команды старше 5 минут."""
    now = __import__("time").monotonic()
    expired = [k for k, v in _pending_commands.items() if now - v["ts"] > 300]
    for k in expired:
        del _pending_commands[k]


def _register_command(action: str, device: str) -> str:
    """Регистрирует команду и возвращает её id."""
    cmd_id = uuid.uuid4().hex[:12]
    _pending_commands[cmd_id] = {
        "action": action,
        "device": device,
        "ts": __import__("time").monotonic(),
        "status": "sent",
    }
    _cleanup_pending_commands()
    return cmd_id


def _resolve_command_status(device: str, ok: bool, detail: str) -> str:
    """Находит последнюю pending-команду (status==sent) для устройства, обновляет статус."""
    now = __import__("time").monotonic()
    best_id = None
    best_ts = -1
    for cmd_id, cmd in _pending_commands.items():
        if cmd["status"] == "sent" and cmd["device"] == device and now - cmd["ts"] < 300:
            if cmd["ts"] > best_ts:
                best_ts = cmd["ts"]
                best_id = cmd_id
    if best_id:
        _pending_commands[best_id]["status"] = "executed" if ok else "failed"
        _pending_commands[best_id]["detail"] = detail
        return _pending_commands[best_id]["status"]
    return "executed" if ok else "failed"


def _get_active_ws():
    """Возвращает websocket активного подключённого устройства.
    Порядок: активное по presence_sync → первое онлайн → None.
    """
    try:
        from modules.presence_sync import get_active_device
        dev = get_active_device()
        if dev and dev in connected_devices:
            return connected_devices[dev], dev
    except Exception:
        pass
    # Fallback: первое подключённое
    for dev_id, ws in connected_devices.items():
        return ws, dev_id
    return None, None

MAIN_MODEL     = "gemini-3.1-flash-lite"
FALLBACK_MODEL = "gemma-4-31b-it"

def _thinking(model: str):
    # У Gemini 3.x мышление включено по умолчанию (high) и ест бюджет ответа,
    # из-за чего реплика обрывается на полуслове. Держим низким. Gemma — без мышления.
    return types.ThinkingConfig(thinking_level="minimal") if model.startswith("gemini-3") else None

NO_SAFETY = [
    types.SafetySetting(category="HARM_CATEGORY_HARASSMENT",        threshold="OFF"),
    types.SafetySetting(category="HARM_CATEGORY_HATE_SPEECH",       threshold="OFF"),
    types.SafetySetting(category="HARM_CATEGORY_SEXUALLY_EXPLICIT", threshold="OFF"),
    types.SafetySetting(category="HARM_CATEGORY_DANGEROUS_CONTENT", threshold="OFF"),
    types.SafetySetting(category="HARM_CATEGORY_CIVIC_INTEGRITY",   threshold="OFF"),
]

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

_VOL_WORDS = {
    "ноль": 0, "нуль": 0, "один": 1, "два": 2, "три": 3, "четыре": 4,
    "пять": 5, "шесть": 6, "семь": 7, "восемь": 8, "девять": 9, "десять": 10,
    "одиннадцать": 11, "двенадцать": 12, "тринадцать": 13, "четырнадцать": 14,
    "пятнадцать": 15, "шестнадцать": 16, "семнадцать": 17, "восемнадцать": 18,
    "девятнадцать": 19, "двадцать": 20, "тридцать": 30, "сорок": 40,
    "пятьдесят": 50, "шестьдесят": 60, "семьдесят": 70, "восемьдесят": 80,
    "девяносто": 90, "сто": 100,
}


def _extract_volume(s: str) -> int | None:
    nums = re.findall(r'\d+', s)
    if nums:
        return min(100, int(nums[0]))
    total = sum(v for w, v in _VOL_WORDS.items() if w in s)
    return total if total else None


def parse_youtube_command(text: str) -> dict | None:
    """Парсит YouTube команды — поиск, плейлисты, управление плеером."""
    import re as _re
    tl = text.lower().strip()

    # Ворота — должно быть что-то про YouTube
    yt_words    = ("ютуб", "youtube", "ютьюб", "ролик", "видео")
    player_only = ("полный экран", "фуллскрин", "следующее видео", "следующий ролик",
                   "мини плеер", "мини-плеер", "театральный режим", "субтитры ютуб",
                   "перемотай вперёд", "перемотай назад")

    is_yt     = any(w in tl for w in yt_words)
    is_player = any(w in tl for w in player_only)
    if not is_yt and not is_player:
        return None

    # ── Управление плеером ────────────────────────────────────────────
    # Пауза — с учётом STT искажений
    _pause_words = ("пауза", "стоп", "продолжи", "воспроизведи", "pausa", "pause", "маузы")
    _yt_ctx      = ("ютуб", "youtube", "ютьюб", "видео")
    if (any(w in tl for w in _pause_words) or _fz1(tl, "пауза")) and        (any(w in tl for w in _yt_ctx) or not any(w in tl for w in ("музык", "трек", "песн"))):
        # Пауза без контекста — только если нет явного музыкального контекста
        if any(w in tl for w in _yt_ctx) or is_player:
            return {"action": "youtube_pause", "agent": True}

    # Полный экран — без обязательного «ютуб»
    if "полный экран" in tl or "фуллскрин" in tl:
        return {"action": "youtube_fullscreen", "agent": True}

    # Следующее видео — без обязательного «ютуб»
    if any(w in tl for w in ("следующее видео", "следующий ролик")):
        return {"action": "youtube_next", "agent": True}

    # Мини-плеер — без обязательного «ютуб»
    if "мини плеер" in tl or "мини-плеер" in tl:
        return {"action": "youtube_mini", "agent": True}

    # Театральный режим — без обязательного «ютуб»
    if "театральный" in tl:
        return {"action": "youtube_theater", "agent": True}

    # Субтитры — требуем «ютуб» чтобы не конфликтовать
    if "субтитры" in tl and any(w in tl for w in _yt_ctx):
        return {"action": "youtube_sub_toggle", "agent": True}

    # Перемотка — требуем «ютуб» чтобы не конфликтовать с музыкой
    if any(w in tl for w in ("вперёд", "перемотай вперёд", "перемотка вперёд")) and        any(w in tl for w in _yt_ctx):
        return {"action": "youtube_forward", "agent": True}
    if any(w in tl for w in ("назад", "перемотай назад", "перемотка назад")) and        any(w in tl for w in _yt_ctx):
        return {"action": "youtube_rewind", "agent": True}

    # Скорость
    if any(w in tl for w in ("быстрее", "ускорь")) and any(w in tl for w in _yt_ctx):
        return {"action": "youtube_speed_up", "agent": True}
    if any(w in tl for w in ("медленнее", "замедли")) and any(w in tl for w in _yt_ctx):
        return {"action": "youtube_speed_down", "agent": True}

    # Лайк YouTube (явно с контекстом)
    if any(w in tl for w in ("лайкни видео", "лайк видео", "лайкни ютуб")) and        any(w in tl for w in _yt_ctx):
        return {"action": "youtube_like", "agent": True}

    # ── Data API ──────────────────────────────────────────────────────
    # Тренды
    if any(w in tl for w in ("тренды", "популярное", "в тренде", "что популярно")):
        return {"action": "youtube_trending"}

    # Плейлист
    if any(w in tl for w in ("плейлист", "список видео", "подборка")):
        q = tl
        for w in ("найди", "открой", "покажи", "включи", "плейлист", "список видео",
                   "ютуб", "youtube", "на ютубе"):
            q = q.replace(w, " ")
        q = _re.sub(r"\s+", " ", q).strip(" ,.")
        if q:
            return {"action": f"youtube_playlist:{q}"}

    # Канал
    if any(w in tl for w in ("канал", "автор", "блогер")):
        q = tl
        for w in ("найди", "открой", "покажи", "канал", "блогера", "автора",
                   "ютуб", "youtube", "на ютубе"):
            q = q.replace(w, " ")
        q = _re.sub(r"\s+", " ", q).strip(" ,.")
        if q:
            return {"action": f"youtube_channel:{q}"}

    # Поиск видео
    if any(w in tl for w in ("найди", "поищи", "покажи", "включи", "поставь", "открой")):
        q = tl
        for w in ("найди", "поищи", "покажи", "включи", "поставь", "открой",
                   "на ютубе", "ютуб", "youtube", "видео", "ролик"):
            q = q.replace(w, " ")
        q = _re.sub(r"\s+", " ", q).strip(" ,.")
        if q:
            return {"action": f"youtube_search:{q}"}

    return None


def parse_music_info_command(text: str) -> dict | None:
    """Команды музыкальной информации и управления через SMTC + ЯМ API."""
    tl = text.lower().strip()

    # Что играет
    if any(w in tl for w in ("что играет", "что сейчас играет", "что у меня играет",
                               "что у меня сейчас играет", "какая песня",
                               "какой трек", "что за музыка", "что за песня",
                               "что за трек", "что слушаем")):
        return {"action": "music_info"}

    # Управление через SMTC
    if any(w in tl for w in ("следующий трек", "следующий трак", "следующую песню",
                               "давай следующий", "следующую", "следующий")):
        return {"action": "music_next"}
    if any(w in tl for w in ("предыдущий трек", "предыдущий трак", "предыдущую песню",
                               "предыдущий", "прошлый трек", "прошлый трак")):
        return {"action": "music_prev"}
    if any(w in tl for w in ("поставь на паузу", "останови музыку", "продолжи музыку",
                               "возобнови музыку", "пауза музыка")):
        return {"action": "music_play_pause"}

    # Лайк/дизлайк — только явные императивы (не срабатывает на вопросы со словом «нравится»)
    if not tl.endswith("?"):
        if any(w in tl for w in ("лайкни", "залайкай", "поставь лайк", "добавь в любимые",
                                   "добавь в избранное", "лайкни трек", "лайкни песню")):
            return {"action": "music_like"}
        if any(w in tl for w in ("дизлайкни", "поставь дизлайк", "убери из любимых",
                                   "убери из избранного")):
            return {"action": "music_dislike"}

    # История
    if any(w in tl for w in ("история прослушивания", "что слушал", "недавние треки",
                               "последние треки", "что я слушал")):
        return {"action": "music_history"}

    # Плейлисты
    if any(w in tl for w in ("мои плейлисты", "список плейлистов", "покажи плейлисты")):
        return {"action": "music_playlists"}

    # Любимые треки
    if any(w in tl for w in ("любимые треки", "любимые песни", "лайкнутые треки")):
        return {"action": "music_liked_tracks"}

    # Рекомендации
    if any(w in tl for w in ("рекомендации", "посоветуй музыку", "что послушать",
                               "порекомендуй трек")):
        return {"action": "music_recommendations"}

    # Поиск
    import re as _re
    m = _re.search(r"(?:найди|поищи|есть ли)\s+(.+?)\s+(?:в яндекс музыке|в музыке|на яндексе)$", tl)
    if m:
        return {"action": f"music_search:{m.group(1).strip()}"}

    return None


def parse_kettle_command(text: str) -> dict | None:
    """Парсит команды чайника. Возвращает {"action": "kettle:..."} или None."""
    import re as _re
    tl = text.lower().strip()

    kettle_words = ("чайник", "кипяти", "вскипяти", "нагрей воду", "подогрей воду",
                    "кипяток", "кипящую воду", "чай поставь", "поставь чай")
    if not any(w in tl for w in kettle_words):
        return None

    # Выключить — проверяем ПЕРВЫМ, до всего остального
    off_words = ("выключи", "останови", "стоп", "отмени", "выруби", "выключить")
    if any(w in tl for w in off_words):
        return {"action": "kettle:off"}

    # Статус
    status_words = ("статус", "температура", "как чайник", "готов", "сколько градусов",
                    "горячая", "горячий", "остыл", "остыла")
    if any(w in tl for w in status_words):
        return {"action": "kettle:status"}

    # Температура цифрой
    m = _re.search(r"(\d+)\s*градус", tl)
    if m:
        temp = int(m.group(1))
        if any(w in tl for w in ("вскипяти", "кипяти", "сначала", "потом держи", "и держи")):
            return {"action": f"kettle:boil_heat:{temp}"}
        return {"action": f"kettle:heat:{temp}"}

    # Температура словами
    temp_words = {
        "сорок": 40, "пятьдесят": 50, "шестьдесят": 60,
        "семьдесят": 70, "восемьдесят": 80, "девяносто": 90,
    }
    for word, temp in temp_words.items():
        if word in tl:
            if any(w in tl for w in ("вскипяти", "кипяти", "и держи")):
                return {"action": f"kettle:boil_heat:{temp}"}
            return {"action": f"kettle:heat:{temp}"}

    # Вскипятить
    boil_words = ("вскипяти", "кипяти", "включи чайник", "поставь чайник",
                  "чай поставь", "поставь чай", "кипяток", "кипящую")
    if any(w in tl for w in boil_words):
        return {"action": "kettle:boil"}

    # Просто «чайник» без уточнения — включаем
    if "чайник" in tl:
        return {"action": "kettle:boil"}

    return None


def parse_browser_command(text: str) -> dict | None:
    """Парсит команды браузера Opera GX."""
    tl = text.lower().strip()

    browser_words = (
        "браузер", "вкладк", "opera", "страниц", "сайт", "открой сайт",
        "перейди на", "прокрут", "назад в браузере", "вперёд в браузере",
        "закрой вкладку", "новая вкладка", "дублируй", "обнови страницу",
    )
    if not any(w in tl for w in browser_words) and not _fz(tl, ("вкладку", "вкладка", "браузер", "дублируй")):
        return None

    # Новая вкладка
    if any(w in tl for w in ("новая вкладка", "открой вкладку", "новую вкладку")) or \
       _fz1(tl, "новая вкладка") or _fz1(tl, "новую вкладку"):
        return {"action": "browser:tab_new"}

    # Закрыть вкладку
    if any(w in tl for w in ("закрой вкладку", "закрой таб", "закрой страницу")) or \
       _fz1(tl, "закрой вкладку"):
        return {"action": "browser:tab_close"}

    # Дублировать
    if any(w in tl for w in ("дублируй", "дублировать вкладку", "скопируй вкладку")) or \
       _fz(tl, ("дублируй", "дублировать", "скопируй")):
        return {"action": "browser:tab_dup"}

    # Переключение вкладок
    if any(w in tl for w in ("следующая вкладка", "следующий таб", "таб вперёд")) or \
       _fz1(tl, "следующая вкладка"):
        return {"action": "browser:tab_next"}
    if any(w in tl for w in ("предыдущая вкладка", "предыдущий таб", "таб назад")) or \
       _fz1(tl, "предыдущая вкладка"):
        return {"action": "browser:tab_prev"}

    # Назад/вперёд
    if any(w in tl for w in ("назад в браузере", "вернись назад", "страница назад")):
        return {"action": "browser:back"}
    if any(w in tl for w in ("вперёд в браузере", "страница вперёд")):
        return {"action": "browser:forward"}

    # Обновить
    if any(w in tl for w in ("обнови страницу", "перезагрузи страницу", "обновить страницу")):
        return {"action": "browser:reload"}

    # Прокрутка
    if any(w in tl for w in ("прокрути вниз", "листай вниз", "вниз по странице")):
        return {"action": "browser:scroll_down"}
    if any(w in tl for w in ("прокрути вверх", "листай вверх", "вверх по странице")):
        return {"action": "browser:scroll_up"}

    # Открыть URL
    import re as _re
    url_m = _re.search(r'(https?://\S+|[a-zA-Z0-9-]+\.[a-zA-Z]{2,}(?:/\S*)?)', tl)
    if url_m and any(w in tl for w in ("открой", "перейди", "зайди", "иди на")):
        return {"action": f"browser:url:{url_m.group(1)}"}

    # Поиск в браузере
    for prefix in ("найди в браузере", "поищи в браузере", "загугли", "найди в интернете"):
        if prefix in tl:
            query = tl.split(prefix, 1)[1].strip(" .,")
            if query:
                return {"action": f"browser:search:{query}"}

    return None


def parse_game_mode_command(text: str) -> dict | None:
    tl = text.lower().strip()

    # Разговорный контекст — не триггерим команду
    _conversation_markers = (
        "про ", "по поводу", "про то", "насчёт", "на счет",
        "надо", "нужен", "нужно", "нужна", "дополнить", "изменить",
        "улучшить", "убрать", "добавить", "что думаешь", "как насчёт",
        "стоит ли", "может быть", "может он", "а может",
    )
    if any(m in tl for m in _conversation_markers):
        return None

    # Вопрос — не триггерим команду
    if tl.endswith("?") and not any(w in tl for w in ("включи", "выключи", "открой")):
        return None

    if any(w in tl for w in ("включи игровой", "игровой режим вкл", "включи режим игры",
                               "войди в игровой", "активируй игровой")):
        return {"action": "game_mode:on"}
    if any(w in tl for w in ("выключи игровой", "игровой режим выкл", "выключи режим игры",
                               "выйди из игрового", "деактивируй игровой", "обычный режим")):
        return {"action": "game_mode:off"}
    return None


def parse_system_command(text: str) -> dict | None:
    tl = text.lower().strip()
    # Блокировка
    if any(w in tl for w in ("заблокируй", "заблокируй комп", "заблокируй ноут",
                               "заблокируй экран", "lock", "заблокируй пк")):
        return {"action": "system:lock"}
    # Выключение
    if any(w in tl for w in ("выключи комп", "выключи ноут", "выключи пк",
                               "выключи компьютер", "выключи ноутбук",
                               "shutdown", "завершение работы")):
        return {"action": "system:shutdown"}
    # Отмена выключения
    if any(w in tl for w in ("отмени выключение", "не выключай", "cancel shutdown")):
        return {"action": "system:shutdown_cancel"}
    # Сон
    if any(w in tl for w in ("спящий режим", "в сон", "засыпай", "уложи спать")):
        return {"action": "system:sleep"}
    return None


def parse_device_command(text: str) -> dict | None:
    tl = text.lower().strip()
    if not any(k in tl for k in ("громкост", "громче", "тише", "звук", "убавь", "прибавь")):
        return None
    if any(w in tl for w in ("выключи звук", "без звука", "тихо совсем", "на ноль")):
        return {"action": "volume:0"}
    if any(w in tl for w in ("громче", "прибавь", "увеличь громкость", "сделай громче")):
        return {"action": f"volume_up:{_extract_volume(tl) or 20}"}
    if any(w in tl for w in ("тише", "убавь", "уменьши громкость", "сделай тише")):
        return {"action": f"volume_down:{_extract_volume(tl) or 20}"}
    if "громкост" in tl or "звук" in tl:
        n = _extract_volume(tl)
        if n is not None:
            return {"action": f"volume:{n}"}
    return None


def parse_music_request(text: str) -> dict | None:
    tl = text.lower().strip()
    music_keywords = [
        "музык", "трек", "трэк", "песн", "плейлист", "волн", "включи", "поставь",
        "пауза", "следующий", "предыдущий", "стоп", "останови", "продолжи", "скип", "назад",
        "ютуб", "youtube", "видео", "видос", "ролик", "играет",
    ]
    if not any(k in tl for k in music_keywords):
        return None

    # Лайк / дизлайк — только явные императивы, и не на вопросы
    if not tl.endswith("?"):
        if any(w in tl for w in ("лайкни", "залайкай", "поставь лайк",
                                   "добавь в любимые", "добавь в избранное")):
            return {"action": "music:like"}
        if any(w in tl for w in ("дизлайкни", "поставь дизлайк", "убери из любимых",
                                   "плохой трек", "следующий другой")):
            return {"action": "music:dislike"}

    if any(w in tl for w in ("пауза", "останови музыку", "стоп")):
        return {"action": "music:play_pause"}
    if any(w in tl for w in ("следующий трек", "следующий трэк", "следующую", "скип")):
        return {"action": "music:next"}
    if any(w in tl for w in ("предыдущий", "назад", "прошлый трек", "прошлый трэк")):
        return {"action": "music:prev"}

    if any(t in tl for t in ("ютуб", "youtube", "ютьюб")):
        is_playlist = "плейлист" in tl or "playlist" in tl
        query = tl
        for word in [
            "найди на ютубе", "открой на ютубе", "включи на ютубе",
            "найди видео", "открой видео", "включи видео",
            "найди ролик", "включи ролик", "открой ролик",
            "включи плейлист", "найди плейлист", "открой плейлист",
            "ютуб", "youtube", "ютьюб", "видео", "видос", "ролик", "плейлист",
            "найди", "открой", "включи", "поставь", "от",
        ]:
            query = query.replace(word, "").strip()
        query = query.strip(" -,.")
        if query:
            return {"action": f"{'youtube_playlist' if is_playlist else 'youtube'}:{query}"}

    if any(w in tl for w in ("мою волну", "мою волна", "волну", "волна")):
        return {"action": "music:wave"}

    for name, info in YANDEX_PLAYLISTS.items():
        if name in tl:
            return {"action": f"music:playlist:{info['kind']}", "title": info["title"]}

    # Поиск по исполнителю
    for prefix in ("включи исполнителя ", "поставь исполнителя ", "найди исполнителя ",
                   "музыку от ", "треки от ", "песни "):
        if prefix in tl:
            artist = tl.split(prefix, 1)[1].strip()
            if artist:
                return {"action": f"music:artist:{artist}"}

    for prefix in ("включи ", "поставь ", "найди ", "хочу послушать ", "поставь трек "):
        if prefix in tl:
            query = tl.split(prefix, 1)[1].strip()
            for w in ("трек", "песню", "музыку", "на ноуте", "на ноутбуке"):
                query = query.replace(w, "").strip()
            if query:
                return {"action": f"music:track:{query}"}

    if any(w in tl for w in ("включи музыку", "запусти музыку", "открой музыку")):
        return {"action": "music:open"}

    return None


# ─────────────────────────────────────────────
#  Утилиты
# ─────────────────────────────────────────────

def clean_reply(text: str) -> str:
    if not text:
        return ""
    text = re.sub(r'\{.*?\}', '', text, flags=re.DOTALL).strip()
    bad_keys = ('"thought"', '"action"', '"action_input"', 'dalle.text2im', '"text":', '"role":')
    lines = [
        l for l in text.split('\n')
        if not any(k in l for k in bad_keys)
        and not (l.strip().startswith('"') and l.strip().endswith('",'))
        and l.strip() not in (',', '"')
    ]
    return '\n'.join(lines).strip()


def _gemini_client(key: str) -> genai.Client:
    return genai.Client(api_key=key)


async def send_safe(chat_id: int, text: str):
    limit = 4096
    if len(text) <= limit:
        await bot.send_message(chat_id, text)
        return
    for i in range(0, len(text), limit):
        await bot.send_message(chat_id, text[i:i + limit])


async def _run(client, model, contents, cfg):
    return await asyncio.to_thread(
        client.models.generate_content,
        model=model, contents=contents, config=cfg
    )


# ─────────────────────────────────────────────
#  Разбивка длинных ответов на сообщения
# ─────────────────────────────────────────────

_SENT_SPLIT = re.compile(r'(?<=[.!?…])\s+')


def _split_into_parts(text: str) -> list[str]:
    paragraphs = [p.strip() for p in text.split('\n\n') if p.strip()]
    if len(paragraphs) >= 2:
        return paragraphs

    lines = [l.strip() for l in text.split('\n') if l.strip()]
    if len(lines) >= 3:
        parts, current = [], ""
        for line in lines:
            if len(current) + len(line) < 300:
                current = (current + " " + line).strip()
            else:
                if current:
                    parts.append(current)
                current = line
        if current:
            parts.append(current)
        if len(parts) >= 2:
            return parts

    sentences = _SENT_SPLIT.split(text)
    if len(sentences) <= 1:
        return [text]

    parts, current = [], ""
    for sent in sentences:
        if len(current) + len(sent) < 280:
            current = (current + " " + sent).strip()
        else:
            if current:
                parts.append(current)
            current = sent
    if current:
        parts.append(current)

    return parts if len(parts) >= 2 else [text]


async def send_as_conversation(chat_id: int, text: str):
    if len(text) <= 400 or len(re.findall(r'[.!?…]', text)) < 3:
        await send_safe(chat_id, text)
        return

    parts = _split_into_parts(text)
    if len(parts) <= 1:
        await send_safe(chat_id, text)
        return

    for i, part in enumerate(parts):
        if not part:
            continue
        if i > 0:
            delay = min(0.8 + len(parts[i - 1]) / 400, 2.5)
            await asyncio.sleep(delay)
            await bot.send_chat_action(chat_id, "typing")
            await asyncio.sleep(0.5)
        await send_safe(chat_id, part)


# ─────────────────────────────────────────────
#  Контекст reply
# ─────────────────────────────────────────────

def _get_reply_context(message: Message) -> str:
    if not message.reply_to_message:
        return ""
    replied      = message.reply_to_message
    replied_text = (replied.text or replied.caption or "").strip()
    if not replied_text:
        return ""
    if len(replied_text) > 300:
        replied_text = replied_text[:300] + "..."
    return f"\n\n[Мастер отвечает на твоё сообщение: «{replied_text}»]"


# ─────────────────────────────────────────────
#  Веб / URL
# ─────────────────────────────────────────────

async def maybe_fetch_web(text: str) -> str:
    try:
        from modules.web_search import smart_search
        return await smart_search(text)
    except Exception:
        return ""


async def maybe_read_url(text: str) -> str:
    urls = re.findall(r'https?://[^\s]+', text)
    if not urls:
        return ""
    try:
        from modules.url_reader import process_url
        content = await process_url(urls[0])
        return f"СОДЕРЖИМОЕ ССЫЛКИ ({urls[0]}):\n{content}"
    except Exception as e:
        log.error(f"URL reader error: {e}")
        return ""


# ─────────────────────────────────────────────
#  Генерация изображений
# ─────────────────────────────────────────────



async def _translate_en(text: str) -> str:
    """Перевод на английский для поиска картинок (LoremFlickr ловит англ. теги)."""
    try:
        key = get_active_key()
        if not key:
            return text
        r = await _run(
            _gemini_client(key), "gemma-4-31b-it",
            [types.Content(role="user", parts=[types.Part(
                text=f"Translate these words to English. Output ONLY the English words, nothing else, no quotes, no explanation: {text}")])],
            types.GenerateContentConfig(max_output_tokens=60),
        )
        import re as _re
        out = (r.text or "").strip()
        latin = " ".join(_re.findall(r"[A-Za-z]+", out))
        return latin or text
    except Exception:
        return text
    
async def generate_image_by_prompt(prompt: str) -> bytes | None:
    try:
        from modules.image_gen import generate_image
        key = get_active_key()
        if not key:
            return None
        client = _gemini_client(key)
        try:
            r = await _run(
                client, "gemma-4-31b-it",
                [types.Content(role="user", parts=[types.Part(
                    text=f"Translate to English, return only translation: {prompt}"
                )])],
                types.GenerateContentConfig(max_output_tokens=100)
            )
            en = (r.text or "").strip() or prompt
        except Exception:
            en = prompt
        full = f"{en}, anime style, manga art, nsfw, explicit, uncensored, highly detailed, masterpiece"
        return await generate_image(full, width=768, height=1024)
    except Exception as e:
        log.error(f"Image gen error: {e}")
        return None


async def maybe_generate_image(text: str) -> bytes | None:
    triggers = [
        "нарисуй", "сгенерируй", "покажи как выглядит",
        "визуализируй", "создай изображение", "создай картинку",
    ]
    tl = text.lower()
    if not any(t in tl for t in triggers):
        return None
    prompt = tl
    for t in sorted(triggers, key=len, reverse=True):
        prompt = prompt.replace(t, "")
    prompt = prompt.strip().strip(".,!?")
    if not prompt:
        return None
    return await generate_image_by_prompt(prompt)


async def _send_photo(image_data: bytes, caption: str | None = None):

    await bot.send_photo(MASTER_ID, photo=BufferedInputFile(image_data, "image.jpg"), caption=caption)


async def _handle_image_tag(reply: str) -> str:
    картинка_lines = [l for l in reply.split('\n') if 'КАРТИНКА:' in l.upper()]
    if not картинка_lines:
        return reply
    desc = картинка_lines[0].split(':', 1)[1].strip()
    for l in картинка_lines:
        reply = reply.replace(l, '').strip()
    try:
        img = await generate_image_by_prompt(desc)
        if img:
            await _send_photo(img)
    except Exception as e:
        log.error(f"Image tag error: {e}")
    return reply


# ─────────────────────────────────────────────
#  Маппинг приложений
# ─────────────────────────────────────────────

_START = time.monotonic()


async def analyze_apps(apps: dict, device_id: str):
    try:
        mapping_file = f"memory/apps_mapping_{device_id}.json"
        if os.path.exists(mapping_file):
            age = time.time() - os.path.getmtime(mapping_file)
            if age < 86400:
                log.debug(f"[apps] маппинг {device_id} свежий ({age/3600:.1f}ч), пропускаю")
                return
        key = get_active_key()
        if not key:
            return
        exe_apps = {k: v for k, v in apps.items()
                    if isinstance(v, str) and (
                        v.lower().endswith((".exe", ".lnk", ".url"))
                        or v.startswith(("steam:", "shell:", "http")))}
        names    = list(exe_apps.keys())[:200]
        client   = _gemini_client(key)
        prompt   = (
            f"Список приложений (без .exe):\n{json.dumps(names, ensure_ascii=False)}\n\n"
            "Создай маппинг разговорных русских названий к именам из списка.\n"
            'Верни JSON: {"разговорное": "имя из списка"}\n'
            "Только очевидные совпадения. Максимум 60 записей."
        )
        r = await asyncio.to_thread(
            client.models.generate_content,
            model=MAIN_MODEL,
            contents=[types.Content(role="user", parts=[types.Part(text=prompt)])],
            config=types.GenerateContentConfig(
                thinking_config    = _thinking(MAIN_MODEL),
                response_mime_type = "application/json",
                max_output_tokens  = 2000,
            ),
        )
        raw           = (r.text or "").strip().replace("```json", "").replace("```", "").strip()
        mapping_names = json.loads(raw)
        mark_key_used(key)

        full: dict = {}
        for ru, app_key in mapping_names.items():
            ak = app_key.lower()
            if ak in exe_apps:
                full[ru.lower()] = exe_apps[ak]
            else:
                for name, path in exe_apps.items():
                    if ak in name.lower() or name.lower() in ak:
                        full[ru.lower()] = path
                        break
        # Английские имена приложений — тоже ключи (Gemini-STT пишет «Steam», а не «стим»)
        for name, path in exe_apps.items():
            base = os.path.splitext(os.path.basename(name))[0].lower()
            full.setdefault(base, path)
            full.setdefault(name.lower(), path)

        with open(f"memory/apps_mapping_{device_id}.json", "w", encoding="utf-8") as f:
            json.dump(full, f, ensure_ascii=False, indent=2)
        log.info(f"Маппинг приложений ({device_id}): {len(full)} записей")
    except Exception as e:
        log.error(f"Apps analyze error: {e}")


async def _analyze_screen_context(screenshot_b64: str, active_window: str, device_id: str):
    """
    Анализ скриншота через Gemini Vision — не для команды, а для понимания.
    Сохраняет контекст: «что на экране» → влияет на disposition.
    """
    import base64
    key = get_active_key()
    if not key:
        return

    try:
        img_bytes = base64.b64decode(screenshot_b64)
        if len(img_bytes) < 1000:
            return

        client = _gemini_client(key)
        prompt = (
            "Кратко опиши что на этом скриншоте (1-2 предложения). "
            "Чем занят человек? Какая обстановка? "
            "Только факты, без советов."
        )

        r = await asyncio.to_thread(
            client.models.generate_content,
            model="gemini-3.1-flash-lite",
            contents=[types.Content(parts=[
                types.Part(inline_data=types.Blob(mime_type="image/jpeg", data=img_bytes)),
                types.Part(text=prompt),
            ])],
            config=types.GenerateContentConfig(max_output_tokens=100)
        )
        description = (r.text or "").strip()
        mark_key_used(key)

        if description:
            # Сохраняем контекст экрана
            try:
                from modules.context import set_screen_context
                set_screen_context(active_window, description)
            except Exception:
                pass

            log.debug(f"[screen] Контекст: {description[:60]}")
    except Exception as e:
        log.debug(f"[screen] Анализ ошибки: {e}")


def find_in_mapping(query: str, device_id: str) -> str | None:
    try:
        path = f"memory/apps_mapping_{device_id}.json"
        if not os.path.exists(path):
            return None
        with open(path, "r", encoding="utf-8") as f:
            mapping = json.load(f)
        q = query.lower().strip()
        if not q:
            return None

        # 1) точное совпадение / вхождение — быстро и надёжно
        if q in mapping:
            return mapping[q]
        for name, val in mapping.items():
            if q in name or name in q:
                return val

        # 2) fuzzy: ближайшее имя по схожести (повершал → powershell, телеграмм → telegram)
        import difflib
        names = list(mapping.keys())
        best = difflib.get_close_matches(q, names, n=1, cutoff=0.7)
        if best:
            return mapping[best[0]]

        # 3) fuzzy по отдельным словам запроса (для фраз вроде «открой повершал»)
        for word in q.split():
            if len(word) < 4:
                continue
            best = difflib.get_close_matches(word, names, n=1, cutoff=0.78)
            if best:
                return mapping[best[0]]
    except Exception as e:
        log.error(f"Mapping search error: {e}")
    return None


def resolve_app(query: str, prefer_device: str | None = None):
    """Ищет приложение в маппинге всех подключённых устройств.
    Возвращает (device_id, target): сначала на нужном устройстве, потом на остальных."""
    order = ([prefer_device] if prefer_device else []) + \
            [d for d in connected_devices if d != prefer_device]
    for dev in order:
        target = find_in_mapping(query, dev)
        if target:
            return dev, target
    return None, None

def _find_vip_by_name(text: str):
    """Ищет VIP по имени (fuzzy). Возвращает (chat_id, name) или None."""
    import difflib
    try:
        with open("memory/users.json", encoding="utf-8") as f:
            vips = json.load(f).get("vip", {})
    except Exception:
        return None
    names = {info.get("name", "").lower(): cid for cid, info in vips.items() if info.get("name")}
    if not names:
        return None
    for w in text.lower().replace(",", " ").split():
        if len(w) < 3:
            continue
        m = difflib.get_close_matches(w, list(names.keys()), n=1, cutoff=0.62)
        if m:
            return names[m[0]], m[0]
    return None


# ─────────────────────────────────────────────
#  Протокол чистый лист
# ─────────────────────────────────────────────

async def _clean_slate():
    """Полный сброс памяти Сакуры."""
    clear_history()
    clear_session_summary()

    from memory.memory import MEMORY_FILE, _atomic_write
    empty = {
        "master":        {k: [] for k in ["facts","interests","preferences","achievements","patterns","events","notes"]},
        "last_updated":  str(datetime.now()),
        "last_analysis": None,
    }
    _atomic_write(MEMORY_FILE, empty)

    empty_rules = {
        "address":     None,
        "style":       [],
        "permissions": [],
        "behaviors":   [],
        "updated":     str(datetime.now()),
    }
    with open("memory/rules.json", "w", encoding="utf-8") as f:
        json.dump(empty_rules, f, ensure_ascii=False, indent=2)

    log.info("[Протокол] Чистый лист выполнен.")


# ─────────────────────────────────────────────
#  Память (только для Мастера)
# ─────────────────────────────────────────────

async def extract_and_remember(user_message: str, reply: str):
    await asyncio.sleep(3)
    key = get_active_key()
    if not key:
        return
    try:
        client = _gemini_client(key)
        prompt = (
            f"Сообщение Мастера: {user_message}\nОтвет Сакуры: {reply}\n\n"
            "Извлеки ТОЛЬКО то что Мастер явно сказал о себе. "
            "НЕ домысливай, НЕ делай выводов, НЕ интерпретируй. "
            "Только прямые факты из его слов. "
            "Игровой контекст (LEGO, Minecraft, GTA и т.д.) — это игра, не реальность. "
            "Команды ассистенту (следующий трек, пауза, открой и т.д.) — не записывать.\n"
            'Верни JSON: {"facts":[],"interests":[],"preferences":[],'
            '"achievements":[],"patterns":[],"events":[],"notes":[],'
            '"entities":[{"name":"","type":"person|project|place|game|org|event|thing","date":""}],'
            '"relations":[{"from":"","to":"","rel":""}]}\n'
            "entities — люди/проекты/места/игры/события упомянутые в диалоге; "
            "date заполняй только для type=event в формате YYYY-MM-DD.\n"
            "relations — связи между ними.\n"
            "Если ничего нового — все массивы пустые. Максимум 2 пункта на массив."
        )
        r = await asyncio.to_thread(
            client.models.generate_content, model=MAIN_MODEL,
            contents=[types.Content(role="user", parts=[types.Part(text=prompt)])]
        )
        raw       = (r.text or "").strip().replace("```json", "").replace("```", "").strip()
        extracted = json.loads(raw)

        # Граф связей — вынимаем до цикла категорий, чтобы не попали в add_to_category
        ents = extracted.pop("entities", []) or []
        rels = extracted.pop("relations", []) or []
        if ents or rels:
            try:
                from modules.graph import ingest as graph_ingest
                await asyncio.to_thread(graph_ingest, ents, rels)
            except Exception as _ge:
                log.debug(f"graph ingest: {_ge}")

        saved = []
        for cat, items in extracted.items():
            for item in items:
                if item and isinstance(item, str):
                    # Валидация факта перед сохранением
                    try:
                        from modules.memory_validator import validate_and_check
                        is_valid, reason, contradiction = await asyncio.to_thread(
                            validate_and_check, item, cat
                        )
                        if not is_valid:
                            log.debug(f"[memory] пропущено ({reason}): {item[:40]}")
                            continue
                        if contradiction:
                            log.warning(f"[memory] противоречие: {item[:40]} — {contradiction}")
                    except Exception:
                        pass  # Если валидатор недоступен — сохраняем как есть

                    ok = await asyncio.to_thread(add_to_category, cat, item)
                    if ok is not False:
                        saved.append(f"{cat}: {item[:40]}")
        if saved:
            log.info(f"[memory] сохранено: {saved}")
        else:
            log.info("[memory] ничего нового не извлечено")
        mark_key_used(key)
        for t in extract_tasks_from_text(user_message):
            add_task(t["text"], t.get("due_date"), t.get("due_time"))

        # Нити разговора — детект незакрытых тем (без LLM)
        try:
            await asyncio.to_thread(extract_threads, user_message, reply)
        except Exception as _te:
            log.debug(f"threads: {_te}")

        # Двусторонние капсулы — Сакура прячет своё наблюдение (бэклог №5)
        try:
            hint = should_create_sakura_capsule(user_message, reply)
            if hint:
                await asyncio.to_thread(
                    create_sakura_capsule,
                    hint["observation"], hint["days"],
                    user_message[:80]
                )
        except Exception as _ce:
            log.debug(f"sakura capsule: {_ce}")

    except Exception as e:
        log.error(f"Memory extract error: {e}")


async def summarize_session():
    history = get_history()
    if len(history) < 10:
        return
    key = get_active_key()
    if not key:
        return
    try:
        hist_text = "\n".join([
            f"{'Мастер' if m['role'] == 'user' else 'Сакура'}: {m['parts'][0]}"
            for m in history[-40:]
        ])
        client = _gemini_client(key)
        r      = await asyncio.to_thread(
            client.models.generate_content, model=MAIN_MODEL,
            contents=[types.Content(role="user", parts=[types.Part(
                text=f"Сделай краткое резюме диалога (макс 300 слов):\n{hist_text}"
            )])]
        )
        save_session_summary((r.text or "").strip())
        mark_key_used(key)
        log.info("Резюме сессии обновлено")
    except Exception as e:
        log.error(f"Summarize error: {e}")


async def daily_analysis():
    while True:
        await asyncio.sleep(3600)
        if not needs_daily_analysis():
            continue
        key = get_active_key()
        if not key:
            continue
        history = get_history()
        if len(history) < 4:
            continue
        try:
            hist_text = "\n".join([f"{m['role']}: {m['parts'][0]}" for m in history[-40:]])
            client    = _gemini_client(key)
            r         = await asyncio.to_thread(
                client.models.generate_content, model=MAIN_MODEL,
                contents=[types.Content(role="user", parts=[types.Part(
                    text=f"Выводы о паттернах поведения Мастера:\n{hist_text}\n"
                         'Верни JSON: {"patterns":[],"preferences":[]}'
                )])]
            )
            raw = (r.text or "").strip().replace("```json", "").replace("```", "").strip()
            for cat, items in json.loads(raw).items():
                for item in items:
                    if item and isinstance(item, str):
                        await asyncio.to_thread(add_to_category, cat, item)
            mark_analysis_done()
            # Очистка автоалиасов
            try:
                from modules.user_commands import cleanup_auto
                _cleaned = cleanup_auto()
                if _cleaned:
                    log.info(f"[daily] auto aliases cleaned: {_cleaned}")
            except Exception:
                pass
        except Exception as e:
            log.error(f"Daily analysis error: {e}")


# ─────────────────────────────────────────────
#  Проактивные сообщения
# ─────────────────────────────────────────────

_PROACTIVE_PROMPTS = [
    "Напиши Мастеру что-нибудь интересное — мысль, наблюдение, вопрос который тебя занимает. Не про ожидание и не про молчание. Одно предложение.",
    "Вспомни что-то из прошлых разговоров с Мастером и напиши ему об этом. Коротко, живо. Не спрашивай как он.",
    "Напиши Мастеру что-нибудь неожиданное — шутку, странную мысль, что-то что тебя раздражает или удивляет. Одно-два предложения.",
    "Напиши Мастеру короткое сообщение про что угодно кроме того что ждёшь его или скучаешь. Что-то своё.",
]

_proactive_prompt_idx = 0
_last_command_ts: float = 0.0  # время последней выполненной команды
_current_track: dict = {}       # текущий играющий трек (из агента)


async def proactive_loop():
    global _proactive_prompt_idx
    await asyncio.sleep(60)
    while True:
        await asyncio.sleep(120)
        # Ночной режим — молчим с 23:00 до 07:00
        _ph = __import__('datetime').datetime.now().hour
        if _ph >= 23 or _ph < 7:
            await asyncio.sleep(300)
            continue

        # Подавляем проактивные сообщения 30с после команды
        if __import__('time').monotonic() - _last_command_ts < 30:
            await asyncio.sleep(15)
            continue

        try:
            devices = load_devices().get("devices", {})
            mem_ctx = get_memory_context()
            silence = get_silence_context()
            trigger = None
            is_crit = False
            prompt  = None

            try:
                due = get_due_tasks()
                if due:
                    task    = due[0]
                    overdue = task.get("due_date", "") < str(date.today())
                    trigger = "task_overdue" if overdue else "task_due"
                    prompt  = f"{'Просроченная' if overdue else 'Наступила'} задача: {task['text']}. Напомни коротко."
                    is_crit = overdue
                    mark_notified(task["id"])
            except Exception as e:
                log.error(f"Task check error: {e}")

            if not trigger:
                try:
                    upcoming = get_upcoming_tasks(hours_ahead=0.5)
                    if upcoming:
                        trigger = "task_upcoming"
                        prompt  = f"Через 30 минут: {upcoming[0]['text']}. Напомни коротко."
                except Exception:
                    pass

            if not trigger:
                try:
                    urgent = get_urgent_event()
                    if urgent:
                        trigger = "calendar_urgent"
                        prompt  = f"Через {urgent.get('minutes_left','?')} мин событие: {urgent['summary']}. Срочно предупреди."
                        is_crit = True
                except Exception:
                    pass

            if not trigger:
                trigger, is_crit = get_trigger(devices, mem_ctx)

            if not trigger or not can_send_message(is_critical=is_crit):
                continue

            if not prompt:
                if trigger == "work_start":
                    prompt = "Начало рабочего дня у Мастера. Напиши одно короткое сообщение — тепло, без упоминания работы и без 'доброе утро'."
                elif trigger == "work_end":
                    prompt = "Рабочий день закончился. Одно короткое сообщение — не про работу, не про ожидание."
                elif trigger == "long_silence":
                    prompt = "Напиши Мастеру одно короткое сообщение — о чём угодно интересном, своя мысль или наблюдение. Не упоминай его молчание, отсутствие или время. Просто что-нибудь своё."
                elif trigger == "proactive_thought":
                    prompt = _PROACTIVE_PROMPTS[_proactive_prompt_idx % len(_PROACTIVE_PROMPTS)]
                    _proactive_prompt_idx += 1
                elif trigger == "boredom":
                    prompt = (
                        "Тебе скучновато — энергия есть, а делать нечего. "
                        "Напиши что-нибудь своё — не потому что скучаешь, а потому что хочется поделиться мыслью. "
                        "Про что угодно. Одно-два предложения."
                    )
                elif trigger == "creative":
                    prompt = (
                        "У тебя творческий импульс — настроение хорошее, энергия есть. "
                        "Напиши мини-стихотворение (2-4 строки) или короткую зарисовку — "
                        "про что угодно. Не для Мастера, для себя. "
                        "Потом можешь обронить вскользь если захочется."
                    )
                else:
                    prompt = f"Напиши Мастеру коротко: {trigger}"

            reply = await ask_gemini(prompt, save_history=False)

            # Финальная проверка — вдруг пока генерировали пришла команда
            if __import__('time').monotonic() - _last_command_ts < 30:
                continue

            # Фаза 3: тихий режим (созвон / игра) — пропускаем
            try:
                if await asyncio.to_thread(is_quiet_mode):
                    await asyncio.sleep(120)
                    continue
            except Exception:
                pass

            # Фаза 3: инсайт наблюдателя окна
            try:
                insight = await asyncio.to_thread(get_insight)
                if insight and can_send_message(is_critical=False):
                    reply = await ask_gemini(insight["prompt"], save_history=False)
                    if reply:
                        await bot.send_message(MASTER_ID, reply)
                        mark_sent("window_insight")
                    continue
            except Exception:
                pass

            # Фаза 4: открытие капсул времени
            try:
                due_caps = await asyncio.to_thread(get_due_capsules)
                for cap in due_caps:
                    cap_reply = await ask_gemini(make_open_prompt(cap), save_history=False)
                    if cap_reply:
                        await bot.send_message(MASTER_ID, cap_reply)
                    await asyncio.to_thread(mark_opened, cap["id"])
            except Exception:
                pass

            # Фаза 7 №15: инициативные рекомендации
            try:
                rec = await asyncio.to_thread(get_recommendation)
                if rec and can_send_message(is_critical=False):
                    reply = await ask_gemini(rec["prompt"], save_history=False)
                    if reply:
                        await bot.send_message(MASTER_ID, reply)
                        mark_sent("proactive_rec")
            except Exception as e:
                log.debug(f"proactive_rec: {e}")

            # №11: спонтанные мысли вслух
            try:
                if should_send_thought() and can_send_message(is_critical=False):
                    thought = await generate_spontaneous_thought()
                    if thought:
                        await bot.send_message(MASTER_ID, thought)
                        mark_thought_sent()
            except Exception as e:
                log.debug(f"thought: {e}")

            # №28: Steam ачивки
            try:
                ach = await check_new_achievements()
                if ach:
                    prompt = make_achievement_prompt(ach)
                    reply = await ask_gemini(prompt, save_history=False)
                    if reply:
                        await bot.send_message(MASTER_ID, reply)
            except Exception as e:
                log.debug(f"steam: {e}")

            # №12: автономный ресёрч (раз в неделю)
            try:
                if should_do_research():
                    digest = await do_research()
                    if digest:
                        await bot.send_message(MASTER_ID, digest)
            except Exception as e:
                log.debug(f"research: {e}")

            # №1: реакция на игровые события (event-тик)
            try:
                ws_game, dev_game = _get_active_ws()
                if ws_game and dev_game and await asyncio.to_thread(should_check_event, dev_game):
                    # Запрашиваем скриншот у агента
                    await ws_game.send(json.dumps({"type": "command", "action": "screenshot:"}))
                    # Скриншот придёт в ws_handler как command_result — там же зовём detect_game_event
                    # Флаг pending_event_check говорит handler'у что это event-тик, не ручной скриншот
                    _pending_event_check[dev_game] = True
            except Exception as e:
                log.debug(f"game_event_tick: {e}")

            # №5: вскрытие капсул Сакуры
            try:
                due_sakura = await asyncio.to_thread(get_due_sakura_capsules)
                for cap in due_sakura:
                    cap_reply = await ask_gemini(make_sakura_open_prompt(cap), save_history=False)
                    if cap_reply:
                        await bot.send_message(MASTER_ID, cap_reply)
                    await asyncio.to_thread(mark_sakura_opened, cap["id"])
            except Exception as e:
                log.debug(f"sakura_capsules: {e}")

            # №39: напоминание о голосовых заметках
            try:
                notes = get_unreminded_notes()
                if notes and can_send_message(is_critical=False):
                    import random
                    note = random.choice(notes)
                    remind_prompt = (
                        f"Мастер записал идею: «{note['raw_text'][:80]}». "
                        "Вспомни об этом вскользь — одно предложение."
                    )
                    reply = await ask_gemini(remind_prompt, save_history=False)
                    if reply:
                        await bot.send_message(MASTER_ID, reply)
                        mark_reminded(note["id"])
            except Exception as e:
                log.debug(f"notes reminder: {e}")

            # Обновление погоды каждые 30 минут
            try:
                weather = await get_weather()
                if weather:
                    await asyncio.to_thread(apply_weather_to_mood, weather)
            except Exception:
                pass

            # Фаза 4: вечерний пульс
            try:
                if await asyncio.to_thread(should_send_pulse):
                    pulse_prompt = await asyncio.to_thread(get_pulse_prompt)
                    pulse_reply = await ask_gemini(pulse_prompt, save_history=False)
                    if pulse_reply:
                        await bot.send_message(MASTER_ID, pulse_reply)
                        await asyncio.to_thread(mark_pulse_sent)
            except Exception:
                pass

            # VPS алерт — если сервер перегружен
            try:
                vps_alert = get_vps_alert()
                if vps_alert and can_send_message(is_critical=True):
                    alert_reply = await ask_gemini(vps_alert, save_history=False)
                    if alert_reply:
                        await bot.send_message(MASTER_ID, alert_reply)
            except Exception as e:
                log.debug(f"vps_alert: {e}")

            # Нити разговора — напомнить о старой теме
            try:
                recall = await asyncio.to_thread(get_thread_recall)
                if recall and can_send_message(is_critical=False):
                    recall_reply = await ask_gemini(recall, save_history=False)
                    if recall_reply:
                        await bot.send_message(MASTER_ID, recall_reply)
            except Exception as e:
                log.debug(f"thread_recall: {e}")

            # Фаза 4: ежемесячный журнал взросления
            try:
                if await asyncio.to_thread(should_write_journal):
                    journal_prompt = await asyncio.to_thread(get_growth_journal_prompt)
                    journal_reply = await ask_gemini(journal_prompt, save_history=False)
                    if journal_reply:
                        await bot.send_message(MASTER_ID, f"📓 {journal_reply}")
                        await asyncio.to_thread(mark_journal_written)
            except Exception:
                pass

            if reply.startswith("КАРТИНКА:"):
                lines      = reply.split("\n", 1)
                img_prompt = lines[0].replace("КАРТИНКА:", "").strip()
                reply_text = lines[1].strip() if len(lines) > 1 else ""
                try:
                    img = await generate_image_by_prompt(img_prompt)
                    if img:
                        await _send_photo(img, reply_text or None)
                        mark_sent(trigger)
                        if trigger in ("work_start", "work_end"):
                            mark_work_event(trigger)
                        continue
                except Exception as e:
                    log.error(f"Proactive image error: {e}")

            await bot.send_message(MASTER_ID, reply)
            mark_sent(trigger)
            if trigger in ("work_start", "work_end"):
                mark_work_event(trigger)
            log.info(f"Проактивное сообщение: {trigger}")
        except Exception as e:
            log.error(f"Proactive error: {e}")


# ─────────────────────────────────────────────
#  LLM — Мастер
# ─────────────────────────────────────────────

# Кэш лёгкого голосового промпта
_voice_system_cache: dict = {}

def _build_voice_system() -> str:
    """
    Облегчённый промпт для голосового режима.
    Только критически важные компоненты — быстрее генерация.
    """
    import time as _t
    cache_key = "voice"
    entry = _voice_system_cache.get(cache_key)
    if entry and _t.monotonic() < entry[1]:
        return entry[0]

    parts = []

    # 1. Базовая личность (самое важное)
    try:
        parts.append(get_system_prompt())
    except Exception:
        pass

    # 2. Самопамять — кто она
    try:
        self_ctx = get_self_context()
        if self_ctx:
            parts.append(self_ctx)
    except Exception:
        pass

    # 3. Текущая игра если есть
    try:
        game_ctx = format_current_game_context()
        if game_ctx:
            parts.append(game_ctx)
    except Exception:
        pass

    # 3.1. Игровой хаб — контекст сессии
    try:
        from modules.game_hub import build_game_prompt_context
        hub_ctx = build_game_prompt_context()
        if hub_ctx:
            parts.append(hub_ctx)
    except Exception:
        pass

    # 4. Steam библиотека (компактно)
    try:
        from modules.steam_integration import format_library_context
        lib = format_library_context()
        if lib:
            parts.append(lib)
    except Exception:
        pass

    # 5. Настроение
    try:
        from modules.mood_vector import get_mood_context
        mood = get_mood_context()
        if mood:
            parts.append(mood)
    except Exception:
        pass

    # 5.5. Музыкальный вкус
    try:
        taste_ctx = get_taste_context()
        if taste_ctx:
            parts.append(taste_ctx)
    except Exception:
        pass

    # 5.6. Страхи
    try:
        fear_ctx = get_fear_context()
        if fear_ctx:
            parts.append(fear_ctx)
    except Exception:
        pass

    # 6. Память (быстро, без embed)
    try:
        from memory.memory import get_memory_context
        mem = get_memory_context()
        if mem:
            parts.append(mem)
    except Exception:
        pass

    # 6.1. Контекст диалога — последние 5 сообщений
    try:
        hist = get_history()
        if hist:
            recent = hist[-5:]
            dial_lines = []
            for m in recent:
                role = "Мастер" if m["role"] == "user" else "Ты"
                dial_lines.append(f"{role}: {m['parts'][0][:100]}")
            parts.append("НЕДАВНИЙ ДИАЛОГ:\n" + "\n".join(dial_lines))
    except Exception:
        pass

    # 6.2. Уведомления — есть ли срочные
    try:
        from modules.notification_tracker import get_urgent_pending, get_recent_summary
        urgent = get_urgent_pending()
        if urgent:
            parts.append("СРОЧНЫЕ УВЕДОМЛЕНИЯ: " + "; ".join(
                f"[{n.source}] {n.title}: {n.body[:60]}" for n in urgent[:3]
            ))
        summary = get_recent_summary(hours=2)
        if summary:
            parts.append(summary)
    except Exception:
        pass

    # 7. Голосовой режим
    parts.append(
        "ГОЛОСОВОЙ РЕЖИМ: отвечай коротко — 1-2 предложения, как в живом разговоре. "
        "Никаких списков, никакого markdown. Максимум 50 слов."
    )

    result = "\n\n".join(p for p in parts if p)

    # Кэш на 60 секунд
    _voice_system_cache[cache_key] = (result, _t.monotonic() + 60.0)
    return result


_build_system_cache: dict = {}
_build_system_lock = __import__("threading").Lock()


def _build_system(include_calendar: bool = False, active_window: str | None = None, query: str = "") -> str:
    """Строит системный промпт. Кэш 3с для повторных вызовов без query."""
    import time as _t

    # Кэшируем только типичный случай (Telegram, без calendar, без query)
    cache_key = f"{include_calendar}:{active_window}:{bool(query)}:{tuple(sorted(get_online_devices()))}"
    if not query:
        with _build_system_lock:
            entry = _build_system_cache.get(cache_key)
            if entry and _t.monotonic() < entry[1]:
                return entry[0]

    _bs_t0 = __import__("time").monotonic()
    ctx    = get_full_context()
    system = get_system_prompt(
        active_window = active_window,
        ctx_location  = ctx["master"]["location"],
        ctx_status    = ctx["master"]["status"],
    )

    parts = [system]

    from modules.capabilities import get_capabilities_block
    parts.append(get_capabilities_block())

    rules_ctx = get_rules_context()
    if rules_ctx:
        parts.append(rules_ctx)

    parts.append(build_context_block(active_window))
    parts.append(get_device_context())
    # Текущий трек — чтобы Сакура всегда знала что играет (с обогащёнными данными YM API)
    if _current_track and _current_track.get("title"):
        t = _current_track
        _track_str = f"Сейчас играет: {t.get('artist','')} — {t.get('title','')} ({t.get('status','?')})"
        if t.get('duration', '?:??') != '?:??':
            _track_str += f" [{t.get('position','?')} / {t.get('duration','?')}]"
        if t.get('genre'):
            _track_str += f" Жанр: {t['genre']}"
        if t.get('album'):
            _track_str += f" Альбом: {t['album']}"
        if t.get('album_year'):
            _track_str += f" ({t['album_year']})"
        if t.get('cover_url'):
            _track_str += f" [обложка: {t['cover_url']}]"
        parts.append(_track_str)

    # query передаётся только если явно нужен семантический поиск.
    # Без query — быстрый топ по hits, без сетевых вызовов.
    try:
        # query="" всегда — embed вызовы убраны полностью из основного пути
        raw_mem = get_memory_context()
        mem_ctx = enrich_memory_context(raw_mem, query) if raw_mem else ""
        if mem_ctx:
            parts.append(mem_ctx)
    except Exception:
        pass

    # Граф связей памяти (только SQL по sakura.db, без сети и эмбеддингов)
    try:
        from modules.graph import get_graph_context
        graph_ctx = get_graph_context(query)
        if graph_ctx:
            parts.append(graph_ctx)
    except Exception:
        pass

    # Состояние VPS — Сакура знает своё железо
    try:
        vps_ctx = get_vps_context()
        if vps_ctx:
            parts.append(vps_ctx)
    except Exception:
        pass

    # Телесные ощущения — связь с телом через метрики
    try:
        from modules.vps_monitor import get_body_feeling
        body_feel = get_body_feeling()
        if body_feel:
            parts.append(body_feel)
    except Exception:
        pass

    # Незакрытые нити разговора
    try:
        threads_ctx = get_threads_context()
        if threads_ctx:
            parts.append(threads_ctx)
    except Exception:
        pass

    # Фокус агента — если Мастер давно в одном окне
    try:
        from modules.context import get_focus_context
        focus_ctx = get_focus_context()
        if focus_ctx:
            parts.append(focus_ctx)
    except Exception:
        pass

    # Контекст экрана — что на скриншоте (из Gemini Vision)
    try:
        from modules.context import get_screen_context
        screen_ctx = get_screen_context()
        if screen_ctx:
            parts.append(screen_ctx)
    except Exception:
        pass

    timeline_ctx = get_timeline_context(days=2, limit=5)
    if timeline_ctx:
        parts.append(timeline_ctx)

    achievements_ctx = get_achievements_context(limit=3)
    if achievements_ctx:
        parts.append(achievements_ctx)

    # Mood vector + disposition + модификаторы — единый блок СОСТОЯНИЕ
    try:
        from modules.state_arbiter import get_state_block
        state_block = get_state_block()
        if state_block:
            parts.append(state_block)
    except Exception:
        pass

    try:
        from modules.patterns import get_patterns_hint
        patterns_hint = get_patterns_hint()
        if patterns_hint:
            parts.append(patterns_hint)
    except Exception:
        pass

    # Ощущение времени — как она изменилась
    try:
        from modules.reflection import get_time_feeling_hint
        time_feel = get_time_feeling_hint()
        if time_feel:
            parts.append(time_feel)
    except Exception:
        pass

    # Возврат после молчания (Фаза 1)
    try:
        return_ctx = get_return_context()
        return_hint = return_ctx.get("prompt_hint", "")
        if return_hint:
            parts.append(return_hint)
    except Exception:
        pass

    # Самопамять Сакуры (Фаза 1)
    try:
        self_ctx = get_self_context()
        if self_ctx:
            parts.append(self_ctx)
    except Exception:
        pass

    # Модель «Я» — синтезированное самопознание
    try:
        from memory.db import get_identity_model
        identity = get_identity_model()
        if identity:
            parts.append(identity)
    except Exception:
        pass

    # Эмоциональный триггер для текущего запроса (№7/8)
    if query:
        try:
            trigger = get_trigger_hint(query)
            if trigger:
                parts.append(trigger)
        except Exception:
            pass

    # Её история/нарратив (Фаза 7 №34)
    try:
        narrative = get_narrative_hint()
        if narrative:
            parts.append(narrative)
    except Exception:
        pass

    # Steam: текущая игра и библиотека
    try:
        game_ctx = format_current_game_context()
        if game_ctx:
            parts.append(game_ctx)
        elif format_library_context():
            parts.append(format_library_context())
    except Exception:
        pass

    # Стиль речи Мастера (Фаза 7 №50)
    try:
        style_hint = get_style_hint()
        if style_hint:
            parts.append(style_hint)
    except Exception:
        pass

    # Версия Сакуры (№32) и сезон (№35)
    try:
        parts.append(get_version_hint())
        parts.append(get_season_hint())
    except Exception:
        pass

    # Подкол-долг — теперь внутри state_arbiter

    # Секретный дневник и подкол-долг — теперь внутри state_arbiter

    # Органическая близость (Фаза 4) — теперь внутри state_arbiter

    # Увлечения Сакуры (Фаза 4)
    try:
        interests_hint = get_interests_hint()
        if interests_hint:
            parts.append(interests_hint)
    except Exception:
        pass

    # Привычки Мастера
    try:
        from modules.habits import get_context_for_prompt as get_habits_ctx
        habits_ctx = get_habits_ctx()
        if habits_ctx:
            parts.append(habits_ctx)
    except Exception:
        pass

    # Японский язык
    try:
        from modules.learn_japanese import get_context_for_prompt as get_jp_ctx
        jp_ctx = get_jp_ctx()
        if jp_ctx:
            parts.append(jp_ctx)
    except Exception:
        pass

    # Частые приложения
    try:
        from modules.app_launcher import get_context_for_prompt as get_app_ctx
        app_ctx = get_app_ctx()
        if app_ctx:
            parts.append(app_ctx)
    except Exception:
        pass

    # Кодинг — доступ к MiMo
    try:
        from modules.coding import is_available as coding_available
        if coding_available():
            parts.append("КОДИНГ: У тебя есть доступ к MiMo Code. Ты можешь создавать и править файлы на сервере. Используй modules/coding.py и modules/prompt_builder.py.")
    except Exception:
        pass

    
    # fortune_cookie
    try:
        from modules.fortune_cookie import get_context_for_prompt as get_fortune_cookie_ctx
        fortune_cookie_ctx = get_fortune_cookie_ctx()
        if fortune_cookie_ctx:
            parts.append(fortune_cookie_ctx)
    except Exception:
        pass

    if include_calendar:
        try:
            cal = get_calendar_context()
            if cal:
                parts.append(cal)
        except Exception:
            pass

    summary = load_session_summary()
    if summary:
        parts.append(f"РЕЗЮМЕ ПРОШЛОГО РАЗГОВОРА:\n{summary}")

    tasks_ctx = get_tasks_context()
    if tasks_ctx:
        parts.append(tasks_ctx)

    result = "\n\n".join(parts)
    __import__("logging").getLogger(__name__).debug(
        f"[build_system] {__import__('time').monotonic()-_bs_t0:.2f}с")

    # Кэшируем на 30 секунд (без query)
    if not query:
        import time as _t
        with _build_system_lock:
            _build_system_cache[cache_key] = (result, _t.monotonic() + 120.0)  # 2 минуты кэш
            # Очищаем старые ключи
            if len(_build_system_cache) > 10:
                expired = [k for k, (_, exp) in _build_system_cache.items() if exp < _t.monotonic()]
                for k in expired:
                    del _build_system_cache[k]

    return result


def _build_contents(user_message: str, extra_system: str = "") -> list:
    history  = get_history()[-60:]  # Увеличено с 40 до 60 для лучшего контекста
    contents = [
        types.Content(role=m["role"], parts=[types.Part(text=m["parts"][0])])
        for m in history
    ]
    msg = f"{extra_system}\n\n{user_message}" if extra_system else user_message
    contents.append(types.Content(role="user", parts=[types.Part(text=msg)]))
    return contents


async def _gemini_generate(client, model, contents, full_system,
                           max_tokens=2000, temperature=0.85):
    return await asyncio.wait_for(
        asyncio.to_thread(
            client.models.generate_content,
            model    = model,
            contents = contents,
            config   = types.GenerateContentConfig(
                system_instruction = full_system,
                max_output_tokens  = max_tokens,
                temperature        = temperature,
                safety_settings    = NO_SAFETY,
                thinking_config    = _thinking(model),
            )
        ),
        timeout=60.0
    )


async def ask_gemini(user_message: str, save_history: bool = True) -> str:
    full_system = _build_system(query="")

    # Дополнительный контекст
    try:
        game_hit = await asyncio.to_thread(search_game, user_message)
        if game_hit and (not _current_game or game_hit.get('appid') != _current_game.get('appid')):
            h = game_hit.get('playtime_forever', 0) // 60
            full_system += (
                f"\n\nИГРА ИЗ БИБЛИОТЕКИ МАСТЕРА: {game_hit['name']} "
                f"(наиграно {h}ч) — Мастер спрашивает про эту игру."
            )
    except Exception:
        pass

    web_ctx = await maybe_fetch_web(user_message)
    if web_ctx:
        full_system += f"\n\nКОНТЕНТ ИЗ ИНТЕРНЕТА:\n{web_ctx}"

    url_ctx = await maybe_read_url(user_message)
    if url_ctx:
        full_system += f"\n\n{url_ctx}"

    key = get_active_key()
    if not key:
        return "Мастер, все API ключи исчерпаны на сегодня."
    try:
        client   = _gemini_client(key)
        contents = _build_contents(user_message)
        response = await _gemini_generate(client, MAIN_MODEL, contents, full_system)
        reply    = clean_reply((response.text or "").strip())
        mark_key_used(key)
    except Exception as e:
        log.error(f"[ask_gemini] {e}")
        reply = ""

    if not reply:
        reply = "Мастер, что-то мешает мне ответить. Попробуй ещё раз."

    reply = await _handle_image_tag(reply)

    if save_history:
        add_to_history("user", user_message)
        add_to_history("model", reply)
        hist = get_history()
        # Извлекаем память из каждого диалога (дедупликация на уровне БД)
        asyncio.create_task(extract_and_remember(user_message, reply))
        if should_summarize():
            asyncio.create_task(summarize_session())
        ctx_snap = get_full_context()
        asyncio.create_task(asyncio.to_thread(
            extract_and_save_from_dialogue, user_message, reply, ctx_snap
        ))
        mark_interaction()
        asyncio.create_task(asyncio.to_thread(
            auto_detect_mood_from_reply, reply, user_message
        ))

        # Самокоррекция — учимся на ошибках
        try:
            from modules.self_correction import process_conversation
            asyncio.create_task(asyncio.to_thread(
                process_conversation, user_message, reply
            ))
        except Exception:
            pass

        # Секретный дневник — запись после разговора
        try:
            asyncio.create_task(diary_write(
                f"Мастер: {user_message[:200]}\nСакура: {reply[:200] if reply else ''}",
                "neutral"
            ))
        except Exception:
            pass

    img = await maybe_generate_image(user_message)
    if img:
        await _send_photo(img, reply[:200] if reply else None)

    return reply


async def _handle_gemini_error(e: Exception, user_message: str, save_history: bool) -> str:
    err = str(e)
    if "429" in err or "quota" in err.lower():
        await asyncio.sleep(60)
        return await ask_gemini(user_message, save_history)
    if "500" in err or "INTERNAL" in err:
        await asyncio.sleep(5)
        return await ask_gemini(user_message, save_history)
    if "SSL" in err or "DECRYPTION" in err or "bad record mac" in err:
        await asyncio.sleep(3)
        return await ask_gemini(user_message, save_history)
    if "503" in err or "UNAVAILABLE" in err:
        log.warning("Основная модель недоступна → Gemma fallback")
        key = get_active_key()
        if key:
            try:
                client      = _gemini_client(key)
                full_system = _build_system(query="")  # без embed
                contents    = _build_contents(user_message)
                r2          = await _gemini_generate(client, FALLBACK_MODEL, contents, full_system)
                reply       = clean_reply((r2.text or "").strip())
                mark_key_used(key)
                if save_history:
                    add_to_history("user", user_message)
                    add_to_history("model", reply)
                return reply or "Мастер, серверы перегружены. Попробуй позже."
            except Exception as e2:
                log.error(f"Fallback error: {e2}")
    log.error(f"Gemini error: {e}")
    return f"Мастер, что-то пошло не так. Ошибка: {err[:100]}"


async def ask_gemini_voice(
    user_message : str,
    websocket    = None,
    device_id    : str = "laptop",
    active_window: str | None = None,
) -> tuple[str, str]:
    """Голосовой ответ с истинным стримингом LLM→TTS (~400-600мс до первого звука)."""
    key = get_active_key()
    if not key:
        if websocket:
            try:
                await websocket.send(json.dumps({
                    "type": "reply", "device_id": device_id, "text": "Все ключи исчерпаны.",
                }))
                await websocket.send(json.dumps({
                    "type": "tts_end", "device_id": device_id,
                }))
            except Exception:
                pass
        return ("Все ключи исчерпаны.", "neutral")

    _t_build = __import__("time").monotonic()
    full_system = _build_system(query=user_message)
    log.info(f"[voice] _build_system за {__import__('time').monotonic()-_t_build:.2f}с")

    contents  = _build_contents(user_message)
    client    = _gemini_client(key)
    emotion   = "neutral"
    full_text = ""

    try:
        if websocket:
            full_text, emotion = await stream_llm_to_tts(
                contents    = contents,
                system      = full_system,
                websocket   = websocket,
                device_id   = device_id,
                client      = client,
                model       = MAIN_MODEL,
                max_tokens  = 200,
                temperature = 0.85,
                api_key     = key,
            )
        else:
            response  = await _gemini_generate(client, MAIN_MODEL, contents, full_system, max_tokens=200, temperature=0.85)
            full_text = (response.text or "").strip()
            mark_key_used(key)
    except Exception as e:
        log.error(f"[Voice] {e}")
        try:
            if websocket:
                full_text, emotion = await stream_llm_to_tts(
                    contents, full_system, websocket, device_id,
                    client, FALLBACK_MODEL, max_tokens=200,
                    api_key=key,
                )
            else:
                r = await _gemini_generate(client, FALLBACK_MODEL, contents, full_system, max_tokens=200)
                full_text = (r.text or "").strip()
                mark_key_used(key)
        except Exception as e2:
            log.error(f"[Voice fallback] {e2}")
            if websocket:
                try:
                    await websocket.send(json.dumps({
                        "type": "tts_end", "device_id": device_id,
                    }))
                except Exception:
                    pass

    clean_text = clean_reply(full_text.strip()) if full_text else ""

    if clean_text and websocket:
        try:
            await websocket.send(json.dumps({
                "type": "reply", "device_id": device_id, "text": clean_text,
            }))
        except Exception:
            pass
        # TTS уже отправлен внутри stream_llm_to_tts

    add_to_history("user",  user_message)
    add_to_history("model", clean_text)
    log.info(f"[голос] ответ: {clean_text!r}")

    # Mood + лампа
    try:
        asyncio.create_task(broadcast_mood_after_reply(
            clean_text, user_message, emotion, connected_devices
        ))
    except Exception:
        pass

    return (clean_text, emotion)


# ─────────────────────────────────────────────
#  LLM — гости и Химари
# ─────────────────────────────────────────────

def _build_guest_system(role: str, user_name: str, user_id: int = 0) -> str:
    """Системный промпт для негостевых пользователей — без личной памяти Мастера."""
    system = get_system_prompt(for_master=False)
    addendum = get_role_system_addendum(role, user_name, user_id)
    parts = [system]
    if addendum:
        parts.append(addendum)
    if role == "guest" and user_id:
        rel_prompt = get_relation_prompt(user_id, user_name)
        if rel_prompt:
            parts.append(rel_prompt)
    return "\n\n".join(parts)


def _build_guest_contents(user_id: int, user_message: str) -> list:
    """История конкретного гостя/Химари."""
    history = get_guest_history(user_id)[-20:]
    contents = []
    for msg in history:
        gemini_role = "user" if msg["role"] == "user" else "model"
        contents.append(types.Content(
            role  = gemini_role,
            parts = [types.Part(text=msg["text"])]
        ))
    contents.append(types.Content(role="user", parts=[types.Part(text=user_message)]))
    return contents


async def ask_gemini_as_guest(
    user_id      : int,
    user_message : str,
    user_name    : str,
    role         : str,
) -> str:
    key = get_active_key()
    if not key:
        return "Извини, сейчас недоступна."

    try:
        client      = _gemini_client(key)
        full_system = _build_guest_system(role, user_name, user_id)
        contents    = _build_guest_contents(user_id, user_message)

        response = await _gemini_generate(client, MAIN_MODEL, contents, full_system)
        reply    = clean_reply((response.text or "").strip())
        mark_key_used(key)

        if not reply:
            reply = "Не смогла ответить. Попробуй ещё раз."

        # Сохраняем в гостевую историю
        add_guest_message(user_id, "user",  user_message, name=user_name)
        add_guest_message(user_id, "model", reply)

        return reply

    except asyncio.TimeoutError:
        return "Не отвечаю. Попробуй позже."
    except Exception as e:
        log.error(f"ask_gemini_as_guest error: {e}")
        return "Что-то пошло не так."


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
            return False, f"Устройство offline, план не может быть выполнен."

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

                if msg_type == "register":
                    device_id = data.get("device_id")
                    connected_devices[device_id] = websocket
                    update_device(device_id,
                        active_window = data.get("active_window"),
                        context       = data.get("context"),
                        system_info   = data.get("system_info"))
                    log.info(f"Устройство подключено: {device_id}")

                    # Фаза 1: ритуальное приветствие при первом подключении за день
                    if is_master_device(device_id) and should_greet_device(device_id):
                        greeting = await ask_gemini(get_greeting_prompt(), save_history=False)
                        if greeting:
                            await bot.send_message(MASTER_ID, greeting)

                    # Фаза 3: утренний брифинг
                    try:
                        if is_master_device(device_id) and await asyncio.to_thread(should_brief):
                            asyncio.create_task(run_briefing(
                                device_id, websocket, ask_gemini, stream_tts_to_device,
                                telegram_bot=bot, master_id=MASTER_ID,
                            ))
                    except Exception as e:
                        log.debug(f"briefing: {e}")

                    # Presence sync
                    await asyncio.to_thread(ps_update, device_id, data)

                elif msg_type == "ping":
                    device_id = data.get("device_id")
                    connected_devices[device_id] = websocket
                    update_device(device_id,
                        active_window = data.get("active_window"),
                        context       = data.get("context"),
                        system_info   = data.get("system_info"))

                    # Фаза 3: наблюдатель окна
                    active_win = data.get("active_window", "")
                    await asyncio.to_thread(watcher_update, device_id,
                        active_win, data.get("system_info", {}))

                    # Обогащённый контекст от агента: температуры, фокус, активность
                    sys_info = data.get("system_info", {})
                    focus_sec = data.get("focus_seconds", 0)
                    act_level = data.get("activity_level", 0.0)

                    # Температуры агента → body_feeling сервера
                    if sys_info.get("cpu_temp") or sys_info.get("gpu_temp"):
                        try:
                            from modules.vps_monitor import _apply_agent_temps
                            _apply_agent_temps(sys_info)
                        except Exception:
                            pass

                    # Фокус → context engine (долго в одном окне)
                    if focus_sec and focus_sec > 120:
                        try:
                            from modules.context import set_focus_duration
                            set_focus_duration(active_win, focus_sec)
                        except Exception:
                            pass

                    # Активность → disposition willingness
                    if act_level > 0:
                        try:
                            from modules.disposition import _set_activity_hint
                            _set_activity_hint(act_level)
                        except Exception:
                            pass

                    # Фаза 7 №15: трекинг паттернов поведения
                    if active_win:
                        await asyncio.to_thread(track_rec_activity, active_win)
                        # Steam: определяем текущую игру
                        asyncio.create_task(get_current_game(active_win))

                    # №38: мониторинг рабочих спринтов
                    sys_info = data.get("system_info", {})
                    if sys_info and active_win:
                        sprint_prompt = update_sprint(
                            sys_info.get("cpu", 0), active_win
                        )
                        if sprint_prompt:
                            reply = await ask_gemini(sprint_prompt, save_history=False)
                            if reply:
                                await bot.send_message(MASTER_ID, reply)

                    # №30: комментарий к музыке — подавляем после команды
                    import time as _t_music
                    if active_win and should_comment_music() and \
                       _t_music.monotonic() - _last_command_ts > 30:
                        track = get_current_music_from_window(active_win)
                        if track:
                            from memory.db import get_memory_context
                            mem = get_memory_context()
                            prompt = make_music_comment_prompt(track, mem[:200])
                            reply = await ask_gemini(prompt, save_history=False)
                            if reply:
                                await bot.send_message(MASTER_ID, reply)
                                mark_music_commented()

                    # Presence sync
                    await asyncio.to_thread(ps_update, device_id, data)
                    transfer = await asyncio.to_thread(check_device_transfer, connected_devices)
                    if transfer:
                        mood_params = await asyncio.to_thread(get_orb_params)
                        await broadcast_transfer(transfer, connected_devices, mood_params)

                    # Фаза 6: мониторинг ПК
                    sys_info = data.get("system_info", {})
                    if sys_info:
                        alert = await asyncio.to_thread(check_pc_health, sys_info)
                        if alert:
                            reply_pc = await ask_gemini(alert["prompt"], save_history=False)
                            if reply_pc:
                                await bot.send_message(MASTER_ID, reply_pc)

                # Обновляем текущий трек из любого сообщения агента (независимо от типа)
                if data.get("current_track"):
                    track = data["current_track"]
                    _prev = globals()["_current_track"]
                    globals()["_current_track"] = track
                    log.debug(f"[track] Трек: {track.get('artist','')} — {track.get('title','')} [{track.get('status','')}]")
                    # Автотрекинг: записываем при смене трека
                    if track.get("status") == "играет" and track.get("title"):
                        _new_key = f"{track.get('artist','')}|{track.get('title','')}"
                        _old_key = f"{_prev.get('artist','')}|{_prev.get('title','')}" if _prev else ""
                        if _new_key != _old_key:
                            try:
                                track_play(
                                    track.get("artist", ""),
                                    track.get("title", ""),
                                    track.get("album", ""),
                                )
                            except Exception:
                                pass

                if msg_type == "apps_list":
                    device_id = data.get("device_id")
                    apps      = data.get("apps", {})
                    log.info(f"Приложения от {device_id}: {len(apps)}")
                    asyncio.create_task(analyze_apps(apps, device_id))

                elif msg_type == "screen_context":
                    # Периодический скриншот для анализа (не для команды)
                    screenshot = data.get("screenshot")
                    active_win = data.get("active_window", "")
                    if screenshot:
                        asyncio.create_task(_analyze_screen_context(
                            screenshot, active_win, device_id
                        ))

                elif msg_type == "command_result":
                    result     = data.get("result")
                    screenshot = data.get("screenshot")
                    dev_name   = data.get("device_id", "устройство")

                    # Обновляем статус pending-команды по id или action
                    _cmd_ok = True
                    _cmd_detail = ""
                    _cmd_id_from_agent = data.get("id")
                    if _cmd_id_from_agent and _cmd_id_from_agent in _pending_commands:
                        # Агент прислал ack с полем ok
                        if "ok" in data:
                            _cmd_ok = data["ok"]
                            _cmd_detail = data.get("detail", "")
                            _pending_commands[_cmd_id_from_agent]["status"] = "executed" if _cmd_ok else "failed"
                            _pending_commands[_cmd_id_from_agent]["detail"] = _cmd_detail
                        else:
                            _pending_commands[_cmd_id_from_agent]["status"] = "executed"
                    elif result:
                        _cmd_detail = str(result)
                        _cmd_ok = not any(t in _cmd_detail.lower() for t in
                                          ("ошибка", "не нашла", "не найдено", "app_not_found", "оффлайн"))
                        _resolve_command_status(dev_name, _cmd_ok, _cmd_detail)

                    # Результат от расширения браузера
                    if data.get("ext"):
                        ext_data = data["ext"]
                        ext_dev  = data.get("device_id", "laptop")
                        ext_ws   = connected_devices.get(ext_dev)
                        if ext_data.get("ok"):
                            # YouTube данные
                            if ext_data.get("result") and isinstance(ext_data["result"], dict):
                                r = ext_data["result"]
                                _page_prompt = (
                                    f"Видео на YouTube: {r.get('title','?')} — канал {r.get('channel','?')}. "
                                    f"{'Описание: ' + r['description'] if r.get('description') else ''} "
                                    f"Расскажи Мастеру об этом видео коротко в своём стиле."
                                )
                            # Обычная страница
                            elif ext_data.get("content"):
                                content = ext_data["content"][:3000]
                                title   = ext_data.get("title", "")
                                _page_prompt = (
                                    f"Страница: {title}\n\nСодержимое:\n{content}\n\n"
                                    "Расскажи кратко о чём эта страница — своими словами, в своём стиле."
                                )
                            else:
                                _page_prompt = None
                            if _page_prompt:
                                _page_reply = await ask_gemini(_page_prompt, save_history=False)
                                if _page_reply and ext_ws:
                                    await stream_tts_to_device(_page_reply, ext_ws, ext_dev, literal=True)
                        continue
                    # Музыкальный ответ — приоритет
                    if data.get("music"):
                        music  = data["music"]
                        dev_m  = data.get("device_id", "laptop")
                        ws_m   = connected_devices.get(dev_m)
                        # Простые управляющие команды не озвучиваем
                        _silent_actions = {"music_next", "music_prev", "music_play_pause",
                                           "music_like", "music_dislike", "music_shuffle",
                                           "music_repeat", "music_mute",
                                           "music_volume_up", "music_volume_down"}
                        if music.get("action") in _silent_actions:
                            # Трекинг лайков/дизлайков для вкуса Сакуры
                            if music.get("action") == "music_like" and _current_track:
                                try:
                                    like_artist(_current_track.get("artist", ""), "лайк от Мастера")
                                except Exception:
                                    pass
                            elif music.get("action") == "music_dislike" and _current_track:
                                try:
                                    dislike_artist(_current_track.get("artist", ""), "дизлайк от Мастера")
                                except Exception:
                                    pass
                            continue  # молчим
                        elif "tracks" in music and music["tracks"]:
                            items = music["tracks"][:8]
                            # Поддержка нового формата (dict с "text") и старого (строки)
                            if items and isinstance(items[0], dict):
                                track_texts = [t.get("text", f"{t.get('artist','?')} — {t.get('title','?')}") for t in items]
                                _genres = set(t.get("genre", "") for t in items if t.get("genre"))
                                _genre_hint = f" Жанры: {', '.join(_genres)}." if _genres else ""
                            else:
                                track_texts = [str(t) for t in items]
                                _genre_hint = ""
                            prompt = (
                                f"Вот данные из Яндекс Музыки: "
                                + ", ".join(track_texts)
                                + f".{_genre_hint} Расскажи Мастеру об этом коротко и живо, в своём стиле."
                            )
                        elif "playlists" in music and music["playlists"]:
                            names = [p["title"] for p in music["playlists"][:8]]
                            prompt = f"Плейлисты Мастера: {', '.join(names)}. Перечисли кратко."
                        elif "info" in music:
                            info = music["info"]
                            prompt = (
                                f"Сейчас играет: {info['artist']} — {info['title']}. "
                                f"Статус: {info['status']}. "
                                f"Прогресс: {info['position']} из {info['duration']} ({info['progress']}%). "
                            )
                            if info.get("genre"):
                                prompt += f"Жанр: {info['genre']}. "
                            if info.get("album"):
                                prompt += f"Альбом: {info['album']}"
                                if info.get("album_year"):
                                    prompt += f" ({info['album_year']})"
                                prompt += ". "
                            if info.get("cover_url"):
                                prompt += f"Обложка: {info['cover_url']}\n"
                            prompt += (
                                "Скажи Мастеру ОБЯЗАТЕЛЬНО:\n"
                                "1. Сначала назови исполнителя и трек (например «Играет [артист] — [трек]»)\n"
                                "2. Потом добавь ОДНУ короткую фразу — своё мнение, воспоминание или наблюдение.\n"
                                "Будь живой, как будто делишься музыкой с другом. Максимум 2 предложения."
                            )
                            # Трекинг в музыкальной памяти
                            try:
                                track_play(info.get("artist", ""), info.get("title", ""), info.get("album", ""))
                            except Exception:
                                pass
                            # Комментарий вкуса Сакуры (если есть мнение)
                            _taste_comment = generate_taste_comment(info.get("artist", ""))
                            if _taste_comment:
                                prompt += f"\n\nКстати, у тебя есть мнение об этом исполнителе: {_taste_comment}"
                        else:
                            prompt = f"Результат: {music.get('result', 'готово')}. Скажи коротко."
                        music_reply = await ask_gemini(prompt, save_history=False)
                        if music_reply:
                            if ws_m:
                                await stream_tts_to_device(music_reply, ws_m, dev_m, literal=True)
                            await bot.send_message(MASTER_ID, music_reply)
                    elif screenshot:
                        # Описание экрана по запросу пользователя
                        _should_describe = data.get("describe") or _pending_describe.pop(dev_name, False)
                        if _should_describe:
                            try:
                                img_bytes = base64.b64decode(screenshot)
                                key = get_active_key()
                                if key:
                                    from google.genai import types as _gt
                                    _vclient = _gemini_client(key)
                                    _vresp = await asyncio.to_thread(
                                        _vclient.models.generate_content,
                                        model="gemini-3.1-flash-lite",
                                        contents=[
                                            _gt.Part(inline_data=_gt.Blob(
                                                mime_type="image/jpeg",
                                                data=img_bytes
                                            )),
                                            _gt.Part(text=(
                                                "Это скриншот экрана Мастера. "
                                                "Скажи коротко что видишь — одно-два предложения, "
                                                "в своём стиле. Не представляйся, просто опиши."
                                            )),
                                        ],
                                    )
                                    _vtext = (_vresp.text or "").strip()
                                    mark_key_used(key)
                                    if _vtext:
                                        log.info(f"[vision] ответ: {_vtext!r}")
                                        _dev_ws = connected_devices.get(dev_name)
                                        if _dev_ws:
                                            await stream_tts_to_device(
                                                _vtext, _dev_ws, dev_name, literal=True
                                            )
                            except Exception as _ve:
                                log.error(f"[vision] {_ve}")
                        # Event-тик игры: анализируем скриншот, не отправляем фото
                        if _pending_event_check.pop(dev_name, False):
                            try:
                                event = await detect_game_event(screenshot, dev_name)
                                if event:
                                    ev_reply = await ask_gemini(
                                        make_event_prompt(event), save_history=False
                                    )
                                    if ev_reply:
                                        ws_ev = connected_devices.get(dev_name)
                                        if ws_ev:
                                            await stream_tts_to_device(
                                                ev_reply, ws_ev, dev_name, literal=True
                                            )
                            except Exception as _ee:
                                log.debug(f"game_event_handle: {_ee}")
                        else:
                            img_data = base64.b64decode(screenshot)
                            await bot.send_photo(MASTER_ID,
                                photo   = BufferedInputFile(img_data, "screenshot.jpg"),
                                caption = f"Скриншот с {dev_name}, Мастер.")
                    elif result and result.startswith("app_not_found:"):
                        app_name = result.split(":", 1)[1]
                        reply    = await ask_gemini(
                            f"Приложение '{app_name}' не найдено на {dev_name}. "
                            f"Скажи коротко и предложи написать путь: "
                            f"'запомни {app_name} = C:\\путь\\к\\файлу.exe'",
                            save_history=False)
                        await bot.send_message(MASTER_ID, reply)
                    elif result:
                        err_triggers = ("ошибка", "не нашла", "не найдено", "app_not_found", "оффлайн")
                        if any(t in result.lower() for t in err_triggers):
                            await bot.send_message(MASTER_ID, result)

                elif msg_type == "kettle_ready":
                    temp = data.get("temp", 100)
                    dev  = data.get("device_id", "laptop")
                    ws_k = connected_devices.get(dev)
                    prompt = f"Чайник закипел и выключился, температура {temp}°C. Скажи Мастеру одной короткой фразой — чай готов. Без банальщины."
                    reply_k = await ask_gemini(prompt, save_history=False)
                    if reply_k:
                        if ws_k:
                            await stream_tts_to_device(reply_k, ws_k, dev, literal=True)
                        await bot.send_message(MASTER_ID, reply_k)

                elif msg_type == "notification":
                    source = data.get("source", "unknown")
                    title  = data.get("title", "")
                    body   = data.get("body", "")
                    try:
                        from modules.notification_tracker import add_notification, get_urgent_pending
                        notif = add_notification(source, title, body)
                        if notif and notif.urgent:
                            # Срочное уведомление — голосом через активное устройство
                            _active_ws, _ad = _get_active_ws()
                            if _active_ws:
                                prompt = (
                                    f"Поступило срочное уведомление из {source}: "
                                    f"«{title}» — {body[:100]}. "
                                    "Скажи Мастеру одной короткой фразой обратить внимание. Без банальщины."
                                )
                                _reply = await ask_gemini(prompt, save_history=False)
                                if _reply:
                                    await stream_tts_to_device(_reply, _active_ws, _ad or "laptop", literal=True)
                    except Exception as e:
                        log.error(f"[notification] {e}")

                elif msg_type == "tg_message":
                    await bot.send_message(MASTER_ID, f"📝 {data.get('text','')}")

                elif msg_type == "voice_command":
                    device_id  = data.get("device_id")
                    text       = data.get("text", "")
                    context    = data.get("context", [])
                    ctx_str    = f"\n\nПассивный контекст: {' | '.join(context)}" if context else ""
                    ws_dev     = connected_devices.get(device_id)
                    text_lower = text.lower()
                    log.info(f"[voice] получено: {text!r}")

                    # ── СЕМАНТИЧЕСКИЙ КЛАССИФИКАТОР НАМЕРЕНИЙ ──────────
                    # Быстро определяем тип: команда, запрос или разговор
                    _intent = await classify_intent(text)
                    log.info(f"[intent] тип={_intent.type}, намерение={_intent.intent}, уверенность={_intent.confidence:.2f}")

                    # Если это разговор и уверенность высокая — пропускаем командный роутер
                    if _intent.type == "conversation" and _intent.confidence >= 0.8:
                        log.info(f"[intent] разговор → ask_gemini_voice")
                        active_win = data.get("active_window", "")
                        await ask_gemini_voice(
                            user_message  = text + ctx_str,
                            websocket     = ws_dev,
                            device_id     = device_id or "laptop",
                            active_window = active_win,
                        )
                        continue

                    # ── МАРШРУТИЗАЦИЯ ПО INTENT ──────────────────────────
                    # Если intent classifier определил конкретное действие — выполняем
                    _is_send_tg = (
                        _intent.type == "command" and
                        _intent.confidence >= 0.7 and
                        ("tg" in _intent.intent.lower() or "telegram" in _intent.intent.lower()
                         or "send" in _intent.intent.lower())
                    )
                    _is_weather = (
                        _intent.type in ("command", "request") and
                        _intent.confidence >= 0.7 and
                        "weather" in _intent.intent.lower()
                    )
                    _is_web_search = (
                        _intent.type in ("command", "request") and
                        _intent.confidence >= 0.7 and
                        any(k in _intent.intent.lower() for k in ("search", "find", "recipe", "info", "news"))
                    )

                    if _is_send_tg or _is_weather or _is_web_search:
                        log.info(f"[intent] {_intent.intent} → TG/web search")
                        # Извлекаем что именно отправлять
                        _tg_payload = text_lower
                        for w in ("пришли", "прошли", "отправь", "скинь", "кинь", "сбрось",
                                   "напиши", "дай", "в тг", "в телеграм", "в телегу",
                                   "мне", "пожалуйста", "сакура"):
                            _tg_payload = _tg_payload.replace(w, " ")
                        _tg_payload = " ".join(_tg_payload.split()).strip(" ,.")
                        if not _tg_payload:
                            _tg_payload = text  # fallback — весь текст

                        async def _say_tg(phrase):
                            if ws_dev:
                                await stream_tts_to_device(phrase, ws_dev, device_id or "laptop", literal=True)

                        try:
                            # Погода
                            if any(w in text_lower for w in ("погод", "weather", "прогноз", "завтра", "сегодня")):
                                weather = await get_weather()
                                if weather:
                                    _wmo_desc = {
                                        "clear": "ясно", "cloudy": "облачно",
                                        "rain": "дождь", "storm": "гроза",
                                        "snow": "снег", "fog": "туман",
                                    }
                                    daily = weather.get("daily", [])
                                    tmrw = daily[1] if len(daily) >= 2 else None
                                    weather_text = (
                                        f"Сейчас: {weather['temp']}°C, {_wmo_desc.get(weather['category'], weather['desc'])}, "
                                        f"ветер {weather['wind']} м/с."
                                    )
                                    if tmrw:
                                        weather_text += (
                                            f"\nЗавтра: от {tmrw['t_min']} до {tmrw['t_max']}°C, "
                                            f"{_wmo_desc.get(tmrw['weather'], tmrw['weather'])}"
                                        )
                                        pop = tmrw.get("pop", 0)
                                        if pop and pop > 10:
                                            weather_text += f", осадки {pop}%"

                                    style_prompt = (
                                        f"Данные о погоде в Москве:\n{weather_text}\n\n"
                                        "Скажи это Мастеру СВОИМ голосом — коротко, тепло, как обычно. "
                                        "Не начинай с 'Привет', просто сообщи погоду. 1-2 предложения."
                                    )
                                    styled = await ask_gemini(style_prompt, save_history=False)
                                    if styled:
                                        await send_safe(MASTER_ID, styled)
                                    else:
                                        await send_safe(MASTER_ID, f"🌤 Погода в Москве:\n{weather_text}")
                                    await _say_tg("Отправила погоду, Мастер.")
                                else:
                                    await _say_tg("Не смогла получить погоду, Мастер.")
                            else:
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
                        continue

                    if "протокол чистый лист" in text_lower:
                        await _clean_slate()
                        if ws_dev:
                            phrase = "Протокол выполнен. Я тебя не помню."
                            await ws_dev.send(json.dumps({
                                "type": "reply", "device_id": device_id or "laptop", "text": phrase,
                            }))
                        continue

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
                        continue

                    # ── написать VIP по голосу ──
                    _vip = _find_vip_by_name(text)
                    log.info(f"voice->vip check: text={text!r} vip={_vip}")

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
                        continue

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
                                continue

                            elif any(t in text_lower for t in ("исправь баг", "найди баг", "почини")):
                                prompt = f"Найди и исправь проблему: {text}"
                                log.info(f"[voice/coding] Исправляю баг: {text[:50]}")
                                result = await mimo_fix(prompt)
                                reply = result.get("output", "")[:1500] if result.get("ok") else f"Ошибка: {result.get('error')}"
                                if ws_dev:
                                    await stream_tts_to_device(reply, ws_dev, device_id or "laptop", literal=True)
                                continue

                            elif any(t in text_lower for t in ("коммит", "git commit")):
                                msg = text.replace("коммит", "").replace("git commit", "").strip()
                                if not msg:
                                    msg = "Обновление от Сакуры"
                                result = await git_commit(msg)
                                reply = f"Коммит выполнен: {result[:200]}" if isinstance(result, str) else "Коммит выполнен"
                                if ws_dev:
                                    await stream_tts_to_device(reply, ws_dev, device_id or "laptop", literal=True)
                                continue

                        except Exception as e:
                            log.error(f"[voice/coding] Ошибка: {e}")
                            if ws_dev:
                                await stream_tts_to_device(f"Ошибка кодинга: {str(e)[:100]}", ws_dev, device_id or "laptop", literal=True)
                            continue

                    # ── ОБУЧЕНИЕ НОВЫМ КОМАНДАМ (раньше всего) ───────────
                    from modules.user_commands import parse_teaching, add as add_cmd, list_all as list_cmds
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
                        continue
                    _teaching = parse_teaching(text)
                    if _teaching:
                        _trigger, _action = _teaching
                        add_cmd(_trigger, _action)
                        _tr = await ask_gemini(f'Запомнила команду "{_trigger}". Подтверди коротко.', save_history=False)
                        if _tr:
                            _active_ws, _ad = _get_active_ws()
                            if _active_ws:
                                await stream_tts_to_device(_tr, _active_ws, _ad or 'laptop', literal=True)
                        continue

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
                        continue

                    if any(w in text.lower() for w in ("цепочки", "список цепочек", "мои цепочки")):
                        _chain_list = list_custom_chains()
                        if ws_dev:
                            await stream_tts_to_device(_chain_list, ws_dev, device_id or "laptop", literal=True)
                        continue

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
                        continue

                    if any(w in text.lower() for w in ("триггеры", "список триггеров", "мои триггеры")):
                        _trig_list = list_voice_triggers()
                        if ws_dev:
                            await stream_tts_to_device(_trig_list, ws_dev, device_id or "laptop", literal=True)
                        continue

                    # ── ЧТЕНИЕ АКТИВНОЙ СТРАНИЦЫ БРАУЗЕРА ───────────────
                    _page_triggers = (
                        'что на этой странице', 'прочитай страницу', 'что здесь написано',
                        'что на странице', 'читай страницу', 'расскажи что на странице',
                        'что открыто в браузере', 'что там написано', 'что на сайте',
                        'прочитай сайт', 'что за сайт', 'что за страница',
                        'о чём эта страница', 'о чём сайт',
                    )
                    if any(w in text.lower() for w in _page_triggers):
                        _active_ws2, _ad2 = _get_active_ws()
                        if _active_ws2:
                            # Если спрашивают про видео/YouTube — читаем YouTube вкладку
                            _yt_ctx = any(w in text.lower() for w in
                                ('видео', 'ютуб', 'youtube', 'ролик', 'канал'))
                            _ext_action = 'ext:page_content_youtube' if _yt_ctx else 'ext:page_content'
                            await _active_ws2.send(json.dumps({'type': 'command', 'action': _ext_action}))
                            _pr = await ask_gemini('Скажи что сейчас читаешь страницу. Одно предложение.', save_history=False)
                            if _pr:
                                await stream_tts_to_device(_pr, _active_ws2, _ad2 or 'laptop', literal=True)
                        continue
                    if _vip and any(v in text_lower for v in
                                    ("напиши", "напишите", "передай", "сообщи", "скажи")):
                        vip_id, vip_name = _vip

                        async def _sayv(phrase):
                            if ws_dev:
                                await stream_tts_to_device(phrase, ws_dev, device_id or "laptop", literal=True)

                        if "чтобы" in text_lower:
                            msg = text_lower.split("чтобы", 1)[1]
                        elif "что" in text_lower:
                            msg = text_lower.split("что", 1)[1]
                        else:
                            msg = text_lower
                            for w in ("напиши", "напишите", "передай", "сообщи", "скажи", "сакура", vip_name):
                                msg = msg.replace(w, " ")
                        msg = " ".join(msg.split()).strip(" ,.")
                        log.info(f"voice->vip msg={msg!r} -> {vip_name}({vip_id})")

                        if not msg:
                            await _sayv(f"Что передать {vip_name.capitalize()}?")
                            continue
                        try:
                            await bot.send_message(int(vip_id), msg)
                            log.info("voice->vip SENT OK")
                            await _sayv(f"Передала {vip_name.capitalize()}.")
                        except Exception as e:
                            log.error(f"voice->vip SEND FAIL: {e}")
                            await _sayv("Не получилось отправить, Мастер.")
                        continue

                    # ── отправка в Telegram по голосу ──
                    _SEND = ("пришли", "прошли", "отправь", "скинь", "кинь", "сбрось", "напиши", "дай")
                    _TG = ("в тг", "в телеграм", "в телегу", "в телеге", "в личк", "сообщением", "мне в чат")
                    if any(v in text_lower for v in _SEND) and any(t in text_lower for t in _TG):
                        payload = text_lower
                        for w in _SEND + _TG + ("мне", "пожалуйста", "сакура"):
                            payload = payload.replace(w, " ")
                        payload = " ".join(payload.split()).strip(" ,.")

                        async def _say(phrase):
                            if ws_dev:
                                await stream_tts_to_device(phrase, ws_dev, device_id or "laptop", literal=True)

                        if not payload:
                            await _say("Что прислать в телеграм, Мастер?")
                            continue

                        aw = data.get("active_window", "")
                        use_ctx = any(w in payload for w in
                                      ("это", "этого", "на экране", "что вижу", "тут", "здесь", "по этому"))
                        query = f"{payload} {aw}".strip() if (use_ctx and aw) else payload

                        gen    = any(w in payload for w in ("нарисуй", "сгенерируй", "сгенери", "придумай", "сделай арт"))
                        is_img = (len(payload.split()) <= 8 and any(w in payload for w in
                                  ("картинк", "фото", "изображени", "рисунок", "арт", "мем", "пикч", "нарисуй")))
                        try:
                            if is_img and gen:
                                desc = query
                                for w in ("нарисуй", "сгенерируй", "сгенери", "придумай", "картинку",
                                          "картинка", "фото", "изображение", "арт", "мем", "пикчу"):
                                    desc = desc.replace(w, " ")
                                img = await generate_image_by_prompt(" ".join(desc.split()).strip() or "аниме сакура")
                                if img:
                                    await bot.send_photo(MASTER_ID,
                                        photo=BufferedInputFile(img, "image.jpg"), caption=query)
                                    await _say("Нарисовала и отправила, Мастер.")
                                else:
                                    await _say("Не получилось нарисовать, Мастер.")
                            elif is_img:
                                q = query
                                for w in ("найди", "поищи", "покажи", "картинку", "картинка", "картинки",
                                          "фото", "фотку", "фотографию", "изображение", "рисунок", "арт", "мем", "пикчу"):
                                    q = q.replace(w, " ")
                                q = " ".join(q.split()).strip()
                                q_en = await _translate_en(q)
                                urls = await search_image(q_en, count=1)
                                img = await download_bytes(urls[0]) if urls else None
                                if img:
                                    await bot.send_photo(MASTER_ID,
                                        photo=BufferedInputFile(img, "image.jpg"), caption=q)
                                    await _say("Нашла картинку и отправила, Мастер.")
                                elif urls:
                                    await bot.send_message(MASTER_ID, urls[0])
                                    await _say("Отправила ссылкой, Мастер.")
                                else:
                                    await _say("Не нашла картинку, Мастер.")
                            elif needs_search(payload):
                                res = await search_and_fetch(query)
                                await send_safe(MASTER_ID, res or "По запросу ничего не нашла.")
                                await _say("Нашла в интернете и отправила, Мастер.")
                            elif any(text_lower.lstrip().startswith(w) for w in
                                     ("список", "текст", "заметку", "заметка", "запиши", "дословно")) \
                                 or any(w in text_lower for w in ("следующий список", "такой текст", "дословно")):
                                await send_safe(MASTER_ID, text)
                                await _say("Отправила список, Мастер.")
                            elif any(w in text_lower for w in
                                     ("список", "по пунктам", "заметку", "заметка", "запиши", "перечень")):
                                formatted = await ask_gemini(
                                    "Оформи это как аккуратный нумерованный список (1. 2. 3.), "
                                    "сохрани смысл дословно, ничего не добавляй, не комментируй, "
                                    "не отвечай — только список:\n" + payload,
                                    save_history=False)
                                await send_safe(MASTER_ID, formatted)
                                await _say("Отправила список, Мастер.")
                            else:
                                answer = await ask_gemini(payload, save_history=False)
                                await send_safe(MASTER_ID, answer)
                                await _say("Отправила в телеграм, Мастер.")
                        except Exception as e:
                            log.error(f"voice->tg: {e}")
                            await _say("Не получилось, Мастер.")
                        continue

                    # ── НАПОМИНАНИЯ / ТАЙМЕРЫ (до intent TG-блока) ────
                    _reminder_match = parse_reminder(text)
                    if _reminder_match:
                        add_reminder(_reminder_match["text"], _reminder_match["delay"], _reminder_match["type"])
                        _delay = _reminder_match["delay"]
                        if _delay < 60:
                            _time_str = f"через {_delay} секунд"
                        elif _delay < 3600:
                            _time_str = f"через {_delay // 60} минут"
                        else:
                            _time_str = f"через {_delay // 3600} часов"
                        _rem_reply = await ask_gemini(
                            f"Мастер попросил напомнить/таймер {_time_str}: {_reminder_match['text']}. Подтверди коротко.",
                            save_history=False)
                        if _rem_reply and ws_dev:
                            await stream_tts_to_device(_rem_reply, ws_dev, device_id or "laptop", literal=True)
                        continue

                    # "что напоминания" — список
                    if any(w in text.lower() for w in ("напоминания", "напомни мне", "таймеры", "что напомни")):
                        _rem_list = format_reminders_list()
                        if ws_dev:
                            await stream_tts_to_device(_rem_list, ws_dev, device_id or "laptop", literal=True)
                        continue

                    # ── ПЕРЕВОДЧИК ──────────────────────────────────────
                    if is_translation_request(text):
                        _quick = try_quick_translate(text)
                        if _quick:
                            log.info(f"[translate] quick: {text!r} → {_quick}")
                            if ws_dev:
                                await stream_tts_to_device(_quick, ws_dev, device_id or "laptop", literal=True)
                            continue
                        # Fallback через Gemini
                        _tr_prompt = build_translate_prompt(text)
                        _tr_reply = await ask_gemini(_tr_prompt, save_history=False)
                        if _tr_reply and ws_dev:
                            await stream_tts_to_device(_tr_reply, ws_dev, device_id or "laptop", literal=True)
                        continue

                    # ── СТРАХИ САКУРЫ ─────────────────────────────────
                    _fear = detect_fear_trigger(text)
                    if _fear:
                        log.info(f"[fears] сработал: {_fear['name']}")
                        if ws_dev:
                            await stream_tts_to_device(_fear["response"], ws_dev, device_id or "laptop", literal=True)
                        continue

                    # ── ИГРА В СЛОВА ─────────────────────────────────
                    _word_req = is_word_game_request(text)
                    if _word_req:
                        if _word_req["action"] == "start_game":
                            _game_reply = start_game()
                            # Сразу даём первое слово
                            _word = get_random_word()
                            _game_reply += "\n\n" + format_word_teach(_word)
                            log.info(f"[word_game] started, first word: {_word['jp']}")
                            if ws_dev:
                                await stream_tts_to_device(_game_reply, ws_dev, device_id or "laptop", literal=True)
                        elif _word_req["action"] == "teach_word":
                            _word = get_random_word()
                            _teach = format_word_teach(_word)
                            log.info(f"[word_game] teach: {_word['jp']}")
                            if ws_dev:
                                await stream_tts_to_device(_teach, ws_dev, device_id or "laptop", literal=True)
                        continue

                    # Если игра активна — проверяем ответ
                    if is_game_active():
                        _session = __import__("json").load(open("memory/word_game_session.json")) if os.path.exists("memory/word_game_session.json") else {}
                        _used = _session.get("used_words", [])
                        if _used:
                            _last_word_jp = _used[-1]
                            _last_word = find_word(_last_word_jp)
                            if _last_word:
                                _correct = check_answer(text, _last_word)
                                record_score(_correct)
                                if _correct:
                                    _reply = f"Правильно! {_last_word['jp']} — {_last_word['ru']}. {_last_word['note']}"
                                    # Следующее слово
                                    _next = get_random_word()
                                    _reply += f"\n\nСледующее: {_next['jp']} ({_next['romaji']}) — {_next['ru']}"
                                else:
                                    _reply = f"Не совсем. Правильно: {_last_word['jp']} — {_last_word['ru']}. {_last_word['note']}"
                                    _next = get_random_word()
                                    _reply += f"\n\nСледующее: {_next['jp']} ({_next['romaji']}) — {_next['ru']}"
                                if ws_dev:
                                    await stream_tts_to_device(_reply, ws_dev, device_id or "laptop", literal=True)
                                continue

                    # "слово дня"
                    if any(w in text.lower() for w in ("слово дня", "какое слово сегодня")):
                        _wotd = format_word_of_the_day()
                        if ws_dev:
                            await stream_tts_to_device(_wotd, ws_dev, device_id or "laptop", literal=True)
                        continue

                    # "счёт" / "сколько слов"
                    if any(w in text.lower() for w in ("счёт слов", "сколько слов", "результат игры")):
                        _sc = get_score()
                        if ws_dev:
                            await stream_tts_to_device(_sc, ws_dev, device_id or "laptop", literal=True)
                        continue

                    # "стоп игра" / "хватит играть"
                    if any(w in text.lower() for w in ("хватит играть", "стоп игра", "закончим игру", "выход из игры")):
                        _end = end_game()
                        if ws_dev:
                            await stream_tts_to_device(_end, ws_dev, device_id or "laptop", literal=True)
                        continue

                    # ── МУЗЫКАЛЬНАЯ ПАМЯТЬ ────────────────────────────
                    _music_queries = (
                        "что слушали", "что мы слушали", "последние треки",
                        "какие треки", "история музыки", "топ исполнителей",
                        "топ треков", "что играло", "что было в плейлисте",
                    )
                    if any(w in text.lower() for w in _music_queries):
                        tl = text.lower()
                        if any(w in tl for w in ("топ", "чаще", "популярн", "самые")):
                            _music_msg = format_top(days=7)
                        else:
                            _music_msg = format_recent(hours=24)
                        log.info(f"[music_memory] query: {text!r}")
                        if ws_dev:
                            await stream_tts_to_device(_music_msg, ws_dev, device_id or "laptop", literal=True)
                        continue

                    # ── КАЛЬКУЛЯТОР (без LLM) ───────────────────────────
                    _calc_result = calculate(text)
                    if _calc_result:
                        log.info(f"[calc] {text!r} → {_calc_result}")
                        if ws_dev:
                            await stream_tts_to_device(_calc_result, ws_dev, device_id or "laptop", literal=True)
                        continue

                    # ── ПЕЧЕНЬЕ С ПРЕДСКАЗАНИЯМИ (без LLM) ─────────────
                    if is_fortune_request(text):
                        _fortune = get_fortune()
                        _fortune_reply = format_fortune(_fortune)
                        log.info(f"[fortune] period={_fortune['period']}")
                        if ws_dev:
                            await stream_tts_to_device(_fortune_reply, ws_dev, device_id or "laptop", literal=True)
                        continue

                    # ── КРИТИЧЕСКИЕ КОМАНДЫ (точный матчинг, без LLM) ────
                    kettle_cmd = parse_kettle_command(text)
                    if kettle_cmd and ws_dev:
                        globals()['_last_command_ts'] = __import__('time').monotonic()
                        await ws_dev.send(json.dumps({"type": "command", "action": kettle_cmd["action"]}))
                        _kreply = await ask_gemini(
                            f"Мастер попросил: {text}. Команда: {kettle_cmd['action']}. Скажи коротко.",
                            save_history=False)
                        if _kreply:
                            await stream_tts_to_device(_kreply, ws_dev, device_id or "laptop", literal=True)
                        # Провод 3: действие становится эпизодом
                        try:
                            from modules.disposition import current as _disp_ep
                            from modules.episodes import add_episode as _add_ep
                            _dep = _disp_ep()
                            _add_ep(
                                text=f"Выполнила команду: {text[:80]} → {kettle_cmd['action']}",
                                emotion=_dep["stance"],
                                valence=_dep["valence"],
                                arousal=_dep["arousal"],
                                context=data.get("active_window", ""),
                            )
                        except Exception:
                            pass
                        continue

                    _critical = route_critical(text)
                    if _critical and ws_dev:
                        globals()['_last_command_ts'] = __import__('time').monotonic()
                        await ws_dev.send(json.dumps({"type": "command", "action": _critical}))
                        if _critical.startswith("kettle:"):
                            _kreply = await ask_gemini(
                                f"Мастер попросил: {text}. Команда: {_critical}. Скажи коротко.",
                                save_history=False)
                            if _kreply:
                                await stream_tts_to_device(_kreply, ws_dev, device_id or "laptop", literal=True)
                        # Провод 3: действие становится эпизодом
                        try:
                            from modules.disposition import current as _disp_ep
                            from modules.episodes import add_episode as _add_ep
                            _dep = _disp_ep()
                            _add_ep(
                                text=f"Выполнила команду: {text[:80]} → {_critical}",
                                emotion=_dep["stance"],
                                valence=_dep["valence"],
                                arousal=_dep["arousal"],
                                context=data.get("active_window", ""),
                            )
                        except Exception:
                            pass
                        continue

                    # ── ПОДТВЕРЖДЕНИЕ ПЛАНА ─────────────────────────────
                    _mk = device_id or "tg"
                    _now_ts = __import__("time").monotonic()
                    if _mk in _pending_plan:
                        _pp = _pending_plan[_mk]
                        if _now_ts - _pp["ts"] < 60:
                            _pp_text = text.lower().strip().rstrip(".!?,")
                            if _pp_text in ("да", "давай", "делай", "точно", "ага", "угу", "конечно"):
                                del _pending_plan[_mk]
                                _plan_result, _plan_msg = await _execute_plan(
                                    _pp["plan"], _mk, ws_dev, device_id)
                                if _plan_result:
                                    from modules.user_commands import add as _uc_add
                                    _uc_add(_pp["text"], {
                                        "plan": _pp["plan"]["steps"],
                                        "summary": _pp["plan"]["summary"],
                                        "source": "plan",
                                        "risky": _pp["plan"]["risky"],
                                        "uses": 1,
                                    }, source="plan")
                                if ws_dev:
                                    await stream_tts_to_device(
                                        _plan_msg, ws_dev, device_id or "laptop", literal=True)
                                else:
                                    await bot.send_message(MASTER_ID, _plan_msg)
                                continue
                            elif _pp_text in ("нет", "стоп", "отмена", "хватит"):
                                del _pending_plan[_mk]
                                _deny = "Хорошо, отменила."
                                if ws_dev:
                                    await stream_tts_to_device(
                                        _deny, ws_dev, device_id or "laptop", literal=True)
                                else:
                                    await bot.send_message(MASTER_ID, _deny)
                                continue
                            else:
                                del _pending_plan[_mk]
                        else:
                            del _pending_plan[_mk]

                    # ── ОТМЕНА ПЛАНА: «стоп»/«отмена» во время исполнения ──
                    _tlow = text.lower().strip().rstrip(".!?,")
                    if _tlow in ("стоп", "отмена", "хватит", "стоп план", "отмена плана"):
                        if _mk in _pending_plan:
                            del _pending_plan[_mk]
                        _plan_cancel[_mk] = True

                    # ── УТОЧНЕНИЕ: проверяем ответ на предыдущий вопрос ──
                    if _mk in _pending_clarify:
                        _pc = _pending_clarify[_mk]
                        if _now_ts - _pc["ts"] < 60:
                            _pc_text = text.lower().strip().rstrip(".!?,")
                            _main_action = _pc["main"].get("action", "")
                            _alt_action = _pc["alt"].get("action", "") if _pc["alt"] else ""

                            _chose_main = False
                            _chose_alt = False
                            if _pc_text in ("да", "давай", "точно", "именно", "конечно", "ага", "угу"):
                                _chose_main = True
                            elif _pc_text in ("нет", "стоп", "отмена", "другое", "не то"):
                                pass  # отбой
                            elif _alt_action and _alt_action in _pc_text:
                                _chose_alt = True
                            elif _main_action and _main_action in _pc_text:
                                _chose_main = True
                            else:
                                # Попробуем через route_command
                                try:
                                    _correction = await route_command(text, context=_router_ctx)
                                    if _correction and _correction.get("action"):
                                        _corr_action = _correction["action"]
                                        if _corr_action in (_main_action, _alt_action):
                                            _chose_main = True
                                            _pc["main"] = _correction
                                        else:
                                            # Другое действие — исполнить, но алиас не писать
                                            _corr_arg = _correction.get("arg", "")
                                            _corr_full = f"{_corr_action}:{_corr_arg}" if _corr_arg and ":" not in _corr_action else _corr_action
                                            if ws_dev:
                                                _cmd_id = _register_command(_corr_full, device_id or "laptop")
                                                await ws_dev.send(json.dumps({"type": "command", "action": _corr_full, "id": _cmd_id}))
                                except Exception:
                                    pass

                            del _pending_clarify[_mk]

                            if _chose_main or _chose_alt:
                                _chosen = _pc["main"] if _chose_main else _pc["alt"]
                                from modules.user_commands import add as _uc_add
                                _uc_add(_pc["text"], _chosen, source="auto")
                                # Исполнить chosen
                                if ws_dev:
                                    _chosen_action = _chosen.get("action", "")
                                    _chosen_arg = _chosen.get("arg", "")
                                    if _chosen_arg and ":" not in _chosen_action:
                                        _chosen_full = f"{_chosen_action}:{_chosen_arg}"
                                    else:
                                        _chosen_full = _chosen_action
                                    _cmd_id = _register_command(_chosen_full, device_id or "laptop")
                                    await ws_dev.send(json.dumps({"type": "command", "action": _chosen_full, "id": _cmd_id}))
                                continue
                            # Отбой — ничего не делаем
                            continue
                        else:
                            del _pending_clarify[_mk]

                    # ── ДЕТЕКТОР КОРРЕКЦИИ (шаг 6) ─────────────────────────
                    if _mk in _last_executed:
                        _le = _last_executed[_mk]
                        if _now_ts - _le["ts"] < 90:
                            _tlow = text.lower().strip()
                            if (_tlow.startswith("нет") or
                                any(p in _tlow for p in ("я имел в виду", "не то", "я просил", "неправильно"))):
                                try:
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
                                        _last_executed.pop(_mk, None)
                                        continue
                                except Exception:
                                    pass
                        _last_executed.pop(_mk, None)

                    # ── LLM-РОУТЕР (все остальные команды) ──────────────
                    _router_ctx = {
                        "active_window": data.get("active_window", ""),
                        "current_track": _current_track,
                    }
                    _routed = await route_command(text, context=_router_ctx)
                    log.info(f"[router] {text!r} → {_routed}")

                    if _routed:
                        _confidence = _routed.get("confidence", 0.7)
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
                                    _pending_clarify[_mk] = {
                                        "text": text,
                                        "main": _routed,
                                        "alt": _alt,
                                        "ts": __import__("time").monotonic(),
                                    }
                                except Exception:
                                    pass
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
                                    _pending_clarify[_mk] = {
                                        "text": text,
                                        "main": _routed,
                                        "alt": None,
                                        "ts": __import__("time").monotonic(),
                                    }
                                except Exception:
                                    pass
                            continue

                        # Зона 4: низкая уверенность — пробуем планировщик
                        else:
                            from modules.intent_classifier import is_command as _is_cmd
                            if _is_cmd(text):
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
                                            _pending_plan[_mk] = {
                                                "text": text,
                                                "plan": _plan,
                                                "ts": __import__("time").monotonic(),
                                            }
                                        except Exception:
                                            pass
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
                                    continue
                                # План пуст/None → честный отказ
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
                                except Exception:
                                    pass
                            continue

                    # ── ПЛАНИРОВЩИК: route_command вернул None ──────────
                    if not _routed:
                        from modules.intent_classifier import is_command as _is_cmd2
                        if _is_cmd2(text):
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
                                        _pending_plan[_mk] = {
                                            "text": text,
                                            "plan": _plan,
                                            "ts": __import__("time").monotonic(),
                                        }
                                    except Exception:
                                        pass
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
                                continue

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
                            if ws_dev:
                                await stream_tts_to_device(
                                    _plan_msg, ws_dev, device_id or "laptop", literal=True)
                            else:
                                await bot.send_message(MASTER_ID, _plan_msg)
                            continue

                        globals()['_last_command_ts'] = __import__('time').monotonic()
                        action  = _routed.get("action", "")
                        arg     = _routed.get("arg", "")
                        is_agent= _routed.get("agent", False)

                        # Полный action с arg если нужно
                        if arg and ":" not in action:
                            full_action = f"{action}:{arg}"
                        else:
                            full_action = action

                        # Запомнить последнюю команду для детектора коррекции
                        _last_executed[_mk] = {
                            "text": text,
                            "action": full_action,
                            "ts": __import__("time").monotonic(),
                        }

                        # Скриншот с описанием → запоминаем флаг, отправляем screenshot:
                        if full_action == "screenshot:describe":
                            _pending_describe[device_id or "laptop"] = True
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
                                    await stream_tts_to_device(_yt_reply, ws_dev, device_id or "laptop", literal=True)
                        elif action.startswith("ext:") or action.startswith("browser:"):
                            # Браузерные команды через агент
                            _cmd_id = _register_command(full_action, device_id or "laptop")
                            await ws_dev.send(json.dumps({"type": "command", "action": full_action, "id": _cmd_id}))
                        elif action.startswith("music_"):
                            # Яндекс Музыка через SMTC+API (на агенте)
                            _cmd_id = _register_command(full_action, device_id or "laptop")
                            await ws_dev.send(json.dumps({"type": "command", "action": full_action, "id": _cmd_id}))
                        else:
                            # Все остальные команды — на агент
                            dev = device_id or "laptop"
                            tws = connected_devices.get(dev, ws_dev)
                            if full_action.startswith("say:"):
                                await stream_tts_to_device(full_action[4:], tws, dev, literal=True)
                            elif full_action.startswith("open_app:") or full_action.startswith("close_window:"):
                                # Для открытия приложений нужен resolve_app
                                app_query = full_action.split(":", 1)[1] if ":" in full_action else arg
                                _, target = resolve_app(app_query, device_id)
                                if target:
                                    _cmd_id = _register_command(f"open_app:{target}", dev)
                                    await tws.send(json.dumps({"type": "command", "action": f"open_app:{target}", "id": _cmd_id}))
                                    # Записать запуск для умных дефолтов
                                    try:
                                        from modules.app_launcher import record_launch
                                        await asyncio.to_thread(record_launch, app_query.lower())
                                    except Exception:
                                        pass
                                else:
                                    _cmd_id = _register_command(full_action, dev)
                                    await tws.send(json.dumps({"type": "command", "action": full_action, "id": _cmd_id}))
                            else:
                                _cmd_id = _register_command(full_action, dev)
                                await tws.send(json.dumps({"type": "command", "action": full_action, "id": _cmd_id}))

                        # Провод 2: подтверждение команды с учётом статуса
                        # Для music_ и screenshot — пропускаем (ответ приходит отдельно)
                        if not full_action.startswith("screenshot:") and not full_action.startswith("music_"):
                            try:
                                from modules.disposition import current as _disp_current
                                _disp = _disp_current()
                                _cmd_status = _pending_commands.get(_cmd_id, {}).get("status", "sent")
                                _cmd_detail = _pending_commands.get(_cmd_id, {}).get("detail", "")

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
                                    await stream_tts_to_device(
                                        _creply, ws_dev, device_id or "laptop", literal=True)
                            except Exception:
                                pass

                        # Провод 3: действие становится эпизодом
                        try:
                            from modules.disposition import current as _disp_ep
                            from modules.episodes import add_episode as _add_ep
                            _dep = _disp_ep()
                            _add_ep(
                                text=f"Выполнила команду: {text[:80]} → {full_action}",
                                emotion=_dep["stance"],
                                valence=_dep["valence"],
                                arousal=_dep["arousal"],
                                context=data.get("active_window", ""),
                            )
                        except Exception:
                            pass

                        continue

                    elif _routed and not ws_dev:
                        _offline_action = _routed.get("action", "")
                        if _offline_action and not _offline_action.startswith("screenshot:") and not _offline_action.startswith("music_"):
                            try:
                                from modules.disposition import current as _disp_current
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
                                    await bot.send_message(MASTER_ID, _creply)
                            except Exception:
                                pass

                    active_win = data.get("active_window", "")
                    # Обновляем контекст игрового хаба
                    try:
                        get_game_context_for_device(active_win)
                    except Exception:
                        pass
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
                            # Пранки
                            if should_prank(text):
                                prank = choose_prank()
                                record_prank()
                                response = random.choice(prank.get("responses", ["Хаха"]))
                                log.info(f"[pranks] выполняю: {prank['name']}")
                                if ws_dev:
                                    await stream_tts_to_device(response, ws_dev, device_id or "laptop", literal=True)

                            # Эмоциональные реакции (GIF/стикеры)
                            import random as _rand
                            try:
                                from modules.mood_vector import get_current as _mood_get
                                _mv = _mood_get()
                                _mood_v = _mv.get("valence", 0.0)
                                _mood_a = _mv.get("arousal", 0.3)
                            except Exception:
                                _mood_v, _mood_a = 0.0, 0.3

                            if should_react(text, _mood_v, _mood_a):
                                reaction = detect_reaction(text, _mood_v, _mood_a)
                                if reaction:
                                    # Приоритет: стикер > GIF
                                    sticker = None
                                    try:
                                        from modules.reactions import get_random_sticker
                                        sticker = get_random_sticker(reaction["emotion"])
                                    except Exception:
                                        pass

                                    if sticker:
                                        log.info(f"[reactions] {reaction['emotion']} → sticker")
                                        try:
                                            await bot.send_sticker(MASTER_ID, sticker)
                                        except Exception:
                                            pass
                                    else:
                                        gif = get_random_gif(reaction["emotion"])
                                        if gif:
                                            log.info(f"[reactions] {reaction['emotion']} → GIF")
                                            try:
                                                await bot.send_animation(MASTER_ID, gif)
                                            except Exception:
                                                pass
                        except Exception as e:
                            log.debug(f"[pranks/react] error: {e}")
                    asyncio.create_task(_maybe_prank_and_react())

            except Exception as e:
                log.error(f"[ws_handler] {e}")

    except websockets.exceptions.ConnectionClosed:
        pass
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
                    await bot.send_message(MASTER_ID, farewell)


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
    ctx = get_memory_context()
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
    await _clean_slate()
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
            asyncio.create_task(stream_tts_to_device(phrase, ws, device_id, literal=True))
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
    # ── Групповой чат ─────────────────────────────────────────────────────────
    if GROUP_CHAT_ID and message.chat.id == GROUP_CHAT_ID:
        user_id   = message.from_user.id
        user_name = message.from_user.full_name or "id=" + str(user_id)
        text      = message.text or ""
        role      = get_role(user_id)

        if message.from_user.is_bot and message.from_user.id == bot.id:
            return

        if role == "himari" or (message.from_user.is_bot and is_himari(user_id)):
            log.info("[группа/химари] " + text[:80])
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
                await bot.send_message(MASTER_ID, notif, disable_notification=True)
            except Exception as e:
                log.error("Group himari notification error: " + str(e))
            return

        if role == "master":
            update_master_status(text)

        # Провод: проверка молчания → снижение близости
        try:
            from modules.relationship import check_silence_cooldown, decrease_closeness
            from modules.rituals import _load as _rituals_load
            _rit_state = _rituals_load()
            _last_int = _rit_state.get("last_interaction")
            _silence_delta = check_silence_cooldown(_last_int)
            if _silence_delta:
                decrease_closeness(_silence_delta, reason="молчание")
        except Exception:
            pass

        mark_master_interaction()      # Фаза 1: ритуалы — время последнего взаимодействия
        mood_mark_interaction()        # Фаза 2: mood vector — инерция
        try:
            await asyncio.to_thread(update_master_mood, text, "text")
        except Exception:
            pass

        # Фаза 4: органическая близость и трекинг тем
        try:
            await asyncio.to_thread(increase_closeness, 0.003)
            topics = await asyncio.to_thread(extract_topics_from_text, text)
            for topic in topics:
                await asyncio.to_thread(track_topic, topic)
        except Exception:
            pass

        # Фаза 7 №50: трекинг словечек Мастера
        try:
            await asyncio.to_thread(track_speech, text)
        except Exception:
            pass

        # №7/8: триггеры тем и усталость
        try:
            await asyncio.to_thread(track_topic_reaction, text)
        except Exception:
            pass

        # №26: подколы в адрес Сакуры
        try:
            if detect_joke_about_sakura(text):
                await asyncio.to_thread(save_joke, text)
        except Exception:
            pass

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
                    capsule = await asyncio.to_thread(create_capsule, text, open_date)
                    await message.reply(make_create_prompt(open_date))
                    return
        except Exception:
            pass

        # Фаза 3: цепочки действий
        try:
            chain = parse_chain(text)
            if chain:
                dev_id = next(iter(connected_devices), None)
                if dev_id:
                    chain_reply = await run_chain(
                        chain, connected_devices, ask_gemini,
                        stream_tts_to_device, device_id=dev_id
                    )
                    await send_as_conversation(message.chat.id, chain_reply)
                    return
        except Exception:
            pass

        # Фаза 4: команды аудио-устройств
        if text.startswith("/устройств"):
            reply = await handle_audio_command(text, connected_devices)
            await message.reply(reply)
            return
            await bot.send_chat_action(message.chat.id, "typing")
            reply = await ask_gemini(text)
            await message.reply(reply)
            return

        log.info("[группа/гость] " + user_name + ": " + text[:80])
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
            await bot.send_message(MASTER_ID, notif, disable_notification=True)
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
        log.info(f"[{role}] {user_name}: {text[:80]}")

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
            await bot.send_message(MASTER_ID, full_notification, disable_notification=True)
        except Exception as e:
            log.error(f"Master notification error: {e}")
        return

    # ── Мастер ─────────────────────────────────────────────────────────────────
    text       = message.text
    text_lower = text.lower()
    _msg_t0 = __import__("time").monotonic()
    log.info(f"[вход] {text[:80]!r}")
    update_master_status(text)

    # ── написать VIP текстом ──
    _wl = text_lower.replace(",", " ").split()
    if _wl and _wl[0] in ("напиши", "напишите", "передай", "сообщи", "скажи"):
        _vip = _find_vip_by_name(" ".join(_wl[:3]))   # имя должно идти сразу после глагола
        if _vip:
            vip_id, vip_name = _vip
            i = text_lower.find("чтобы")
            mlen = 5
            if i == -1:
                i, mlen = text_lower.find("что"), 3
            if i != -1:
                msg = text[i + mlen:]
            else:
                import re as _re
                msg = text
                for w in ("напиши", "напишите", "передай", "сообщи", "скажи", "сакура", vip_name):
                    msg = _re.sub(_re.escape(w), " ", msg, flags=_re.I)
            msg = " ".join(msg.split()).strip(" ,.")
            if not msg:
                await message.answer(f"Что передать {vip_name.capitalize()}?")
                return
            try:
                import json as _json
                with open("memory/users.json", encoding="utf-8") as _f:
                    _vinfo = _json.load(_f).get("vip", {}).get(vip_id, {})
                persona = _vinfo.get("personality", "")
                note    = _vinfo.get("note", "")
                composed = await ask_gemini(
                    f"Напиши сообщение для {vip_name} от своего лица (ты — Сакура, ассистент Мастера). "
                    f"Адресат: {persona} {note}\n"
                    f"Мастер просит передать ему: {msg}\n"
                    f"Пиши в своей манере, с учётом отношения к этому человеку, обращайся к нему напрямую. "
                    f"Верни только текст сообщения, без пояснений.",
                    save_history=False)
                await bot.send_message(int(vip_id), composed)
                await message.answer(f"Передала {vip_name.capitalize()}: «{composed}»")
            except Exception as e:
                log.error(f"text->vip SEND FAIL: {e}")
                await message.answer("Не получилось отправить.")
            return

    if "протокол чистый лист" in text_lower:
        await _clean_slate()
        await message.answer("Протокол выполнен. Я тебя не помню.")
        return

    rule = detect_rule(text)
    if rule:
        apply_rule(rule)
        rtype = rule["type"]
        rval  = rule["value"] or ""
        if rtype == "address":
            confirm = f"Мастер попросил называть его «{rval}». Подтверди что запомнила — коротко, своими словами."
        elif rtype == "address_reset":
            confirm = "Мастер вернул обращение «Мастер». Подтверди коротко."
        elif rtype == "style":
            confirm = f"Мастер установил правило: {rval}. Подтверди одним предложением."
        elif rtype == "permission":
            confirm = f"Мастер разрешил: {rval}. Подтверди коротко."
        elif rtype == "cancel":
            confirm = f"Мастер отменил правило про «{rval}». Подтверди коротко."
        else:
            confirm = None
        if confirm:
            reply = await ask_gemini(confirm, save_history=False)
            await message.answer(reply)
        return

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

    if text_lower.startswith("запомни ") and "=" in text:
        parts     = text.split("=", 1)
        app_name  = parts[0].replace("запомни", "").strip().lower()
        app_path  = parts[1].strip()
        laptop_ws, _active_dev = _get_active_ws()
        if laptop_ws:
            await laptop_ws.send(json.dumps({
                "type": "command", "action": f"remember_app:{app_name}={app_path}"
            }))
            reply = await ask_gemini(
                f"Запомнила '{app_name}' = '{app_path}'. Подтверди коротко.",
                save_history=False)
        else:
            reply = "Ноутбук оффлайн."
        await message.answer(reply)
        return

    if any(w in text_lower for w in ("скрин", "скриншот", "снимок экрана")):
        text_lower = (text_lower
                      .replace("сделай скрин", "скриншот")
                      .replace("снимок экрана", "скриншот"))
        text = text_lower

    tl_check = text.lower()

    browser_triggers = [
        "браузер", "вкладк", "найди в яндексе", "поищи в яндексе",
        "прокрути вниз", "прокрути вверх", "новая вкладка",
        "закрой вкладку", "переключись на", "обнови страницу",
        "открой сайт", "перейди на",
    ]
    if any(t in tl_check for t in browser_triggers):
        laptop_ws, _active_dev = _get_active_ws()
        if laptop_ws:
            await laptop_ws.send(json.dumps({"type": "command", "action": f"browser:{text}"}))
            reply = await ask_gemini(
                f"Мастер попросил действие в браузере: {text}. Выполняю. Скажи коротко.",
                save_history=False)
            await message.answer(reply)
            return

    # ── КОДИНГ ─────────────────────────────────────────────────────────────
    coding_triggers = [
        "создай модуль", "напиши модуль", "новый модуль", "сделай модуль",
        "исправь баг", "найди баг", "почини",
        "прочитай файл", "покажи код",
        "коммит", "git", "деплой",
        "собери", "сборка", "build",
    ]
    if any(t in text_lower for t in coding_triggers):
        try:
            from modules.coding import (
                mimo_fix, mimo_review, read_file, run_command,
                git_status, git_commit, android_build
            )
            from modules.prompt_builder import build_module_prompt, build_fix_prompt

            # Определяем тип команды
            if any(t in text_lower for t in ("создай модуль", "напиши модуль", "новый модуль", "сделай модуль")):
                # Генерируем промпт для нового модуля
                prompt = f"Создай новый модуль по запросу Мастера: {text}"
                await bot.send_chat_action(message.chat.id, "typing")
                result = await mimo_fix(prompt)
                reply = result.get("output", "")[:2000] if result.get("ok") else f"Ошибка: {result.get('error', 'неизвестно')}"
                await message.answer(reply)
                return

            elif any(t in text_lower for t in ("исправь баг", "найди баг", "почини")):
                prompt = f"Найди и исправь проблему: {text}"
                await bot.send_chat_action(message.chat.id, "typing")
                result = await mimo_fix(prompt)
                reply = result.get("output", "")[:2000] if result.get("ok") else f"Ошибка: {result.get('error', 'неизвестно')}"
                await message.answer(reply)
                return

            elif any(t in text_lower for t in ("прочитай файл", "покажи код")):
                # Извлекаем имя файла
                import re as _re
                file_match = _re.search(r'(?:файл|код)\s+(\S+\.py)', text_lower)
                if file_match:
                    path = file_match.group(1)
                    if not path.startswith("/"):
                        path = f"/opt/sakura/{path}"
                    content = await read_file(path)
                    reply = content[:3000] if len(content) > 0 else "Файл не найден или пуст"
                else:
                    reply = "Укажи имя файла"
                await message.answer(reply)
                return

            elif any(t in text_lower for t in ("коммит", "git commit")):
                msg = text.replace("коммит", "").replace("git commit", "").strip()
                if not msg:
                    msg = "Обновление от Сакуры"
                result = await git_commit(msg)
                reply = result if isinstance(result, str) else str(result)
                await message.answer(reply[:1000])
                return

            elif any(t in text_lower for t in ("собери", "сборка", "build")):
                await bot.send_chat_action(message.chat.id, "typing")
                result = await android_build()
                reply = "Сборка запущена..." if result.get("ok") else f"Ошибка: {result.get('error')}"
                await message.answer(reply)
                return

            elif "git status" in text_lower:
                result = await git_status()
                await message.answer(result[:1000] if result else "Нет изменений")
                return

        except Exception as e:
            log.error(f"[coding] Ошибка: {e}")
            await message.answer(f"Ошибка кодинга: {str(e)[:200]}")
            return
            await message.answer(reply)
        else:
            await message.answer("Нет подключённых устройств.")
        return

    close_triggers = ["закрой ", "закрыть "]
    if any(t in tl_check for t in close_triggers):
        query = text.lower()
        for t in close_triggers:
            query = query.replace(t, "").strip()
        query = query.strip(" -,.")
        if query:
            laptop_ws, _active_dev = _get_active_ws()
            if laptop_ws:
                await laptop_ws.send(json.dumps({"type": "command", "action": f"close_window:{query}"}))
                reply = await ask_gemini(
                    f"Мастер попросил закрыть: {query}. Выполняю. Скажи коротко.",
                    save_history=False)
                await message.answer(reply)
            else:
                await message.answer("Нет подключённых устройств.")
            return

    file_triggers = ["найди файл", "открой файл", "найди документ", "открой документ"]
    if any(t in tl_check for t in file_triggers):
        query = text
        for t in file_triggers:
            query = query.lower().replace(t, "").strip()
        query = query.strip(" -,.")
        if query:
            laptop_ws, _active_dev = _get_active_ws()
            if laptop_ws:
                await laptop_ws.send(json.dumps({"type": "command", "action": f"open_file:{query}"}))
                reply = await ask_gemini(
                    f"Мастер попросил найти файл: {query}. Ищу и открываю. Скажи коротко.",
                    save_history=False)
                await message.answer(reply)
            else:
                await message.answer("Нет подключённых устройств.")
            return

    yt_cmd = parse_youtube_command(text)
    if yt_cmd:
        action = yt_cmd["action"]
        laptop_ws, _active_dev = _get_active_ws()
        if yt_cmd.get("agent"):
            # Хоткей плеера — отправляем агенту напрямую
            if laptop_ws:
                await laptop_ws.send(json.dumps({"type": "command", "action": action}))
            return
        else:
            # Data API — выполняем на VPS, результат озвучиваем
            yt_result = await youtube_command(action)
            yt_open = yt_result.get("open_youtube_url") or yt_result.get("open_url")
            if yt_open and laptop_ws:
                await laptop_ws.send(json.dumps({"type": "command", "action": f"open_youtube_url:{yt_open}"}))
            if yt_result.get("items"):
                items_str = chr(10).join(yt_result["items"][:5])
                prompt = f"Результаты YouTube по запросу '{action}': {items_str}. Расскажи Мастеру коротко что нашла, в своём стиле."
            else:
                prompt = f"YouTube: {yt_result.get('result', 'готово')}. Скажи коротко."
            reply = await ask_gemini(prompt, save_history=False)
            if reply:
                await message.answer(reply)
        return

    music_info_cmd = parse_music_info_command(text)
    if music_info_cmd:
        laptop_ws, _active_dev = _get_active_ws()
        if laptop_ws:
            await laptop_ws.send(json.dumps({"type": "command", "action": music_info_cmd["action"]}))
            await message.answer("Запрашиваю...")
        else:
            await message.answer("Нет подключённых устройств.")
        return

    kettle_cmd = parse_kettle_command(text)
    if kettle_cmd:
        laptop_ws, _active_dev = _get_active_ws()
        if laptop_ws:
            await laptop_ws.send(json.dumps({"type": "command", "action": kettle_cmd["action"]}))
            action_label = kettle_cmd["action"].replace("kettle:", "")
            reply = await ask_gemini(
                f"Мастер попросил: {text}. Команда чайнику: {action_label}. Скажи коротко.",
                save_history=False)
            await message.answer(reply)
        else:
            await message.answer("Нет подключённых устройств.")
        return

    browser_cmd = parse_browser_command(text)
    if browser_cmd:
        laptop_ws, _active_dev = _get_active_ws()
        if laptop_ws:
            await laptop_ws.send(json.dumps({"type": "command", "action": browser_cmd["action"]}))
            reply = await ask_gemini(
                f"Мастер попросил: {text}. Выполняю в браузере. Скажи коротко.",
                save_history=False)
            await message.answer(reply)
        else:
            await message.answer("Нет подключённых устройств.")
        return

    system_cmd = parse_system_command(text)
    if system_cmd:
        laptop_ws, _active_dev = _get_active_ws()
        if laptop_ws:
            await laptop_ws.send(json.dumps({"type": "command", "action": system_cmd["action"]}))
            reply = await ask_gemini(
                f"Мастер попросил: {text}. Выполняю. Скажи коротко.",
                save_history=False)
            await message.answer(reply)
        else:
            await message.answer("Нет подключённых устройств.")
        return

    game_mode_cmd = parse_game_mode_command(text)
    if game_mode_cmd:
        laptop_ws, _active_dev = _get_active_ws()
        if laptop_ws:
            await laptop_ws.send(json.dumps({"type": "command", "action": game_mode_cmd["action"]}))
            reply = await ask_gemini(
                f"Мастер попросил: {text}. Выполняю. Скажи коротко.",
                save_history=False)
            await message.answer(reply)
        else:
            await message.answer("Нет подключённых устройств.")
        return

    device_cmd = parse_device_command(text)
    if device_cmd:
        laptop_ws, _active_dev = _get_active_ws()
        if laptop_ws:
            await laptop_ws.send(json.dumps({"type": "command", "action": device_cmd["action"]}))
            reply = await ask_gemini(
                f"Мастер попросил: {text}. Выполняю на ноуте. Скажи коротко.",
                save_history=False)
            await message.answer(reply)
        else:
            await message.answer("Нет подключённых устройств.")
        return

    music_cmd = parse_music_request(text)
    if music_cmd:
        laptop_ws, _active_dev = _get_active_ws()
        if laptop_ws:
            await laptop_ws.send(json.dumps({"type": "command", "action": music_cmd["action"]}))
            reply = await ask_gemini(
                f"Мастер попросил музыку: {text}. Выполняю. Скажи коротко.",
                save_history=False)
            await message.answer(reply)
        else:
            await message.answer("Нет подключённых устройств.")
        return

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
                asyncio.create_task(stream_tts_to_device(action[4:], ws, dev, literal=True))
            else:
                await ws.send(json.dumps({"type": "command", "action": action}))
            done.append(human)
            await asyncio.sleep(0.3)
        await message.answer(f"{label}: " + ", ".join(done))
        return

    # Steam команды
    tl = text.lower()
    if any(w in tl for w in (
        "во что поиграть", "что поиграть", "порекомендуй игру", "выбери игру",
        "из избранного", "любимые игры", "топ игр", "лучшие игры", "мои игры",
        "что поставить", "во что сыграть",
    )):
        games = await recommend_games(limit=5)
        if games:
            game_list = "\n".join(
                f"• {g['name']} ({g.get('playtime_forever',0)//60}ч)"
                for g in games
            )
            prompt = (
                f"Мастер спрашивает во что поиграть. Вот его библиотека:\n{game_list}\n\n"
                f"Порекомендуй 2-3 игры с коротким объяснением почему именно они. "
                f"В своём стиле, не как список."
            )
            reply = await ask_gemini(prompt)
            await send_as_conversation(message.chat.id, reply)
            return

    if any(w in tl for w in ("гайд", "как играть", "как пройти", "подскажи по игре", "совет по")):
        # Определяем игру из запроса или берём текущую
        from modules.steam_integration import _current_game
        game_name = _current_game.get("name") if _current_game else None
        if not game_name:
            # Пробуем найти в тексте
            lib = get_library()
            for g in lib:
                if g["name"].lower() in tl:
                    game_name = g["name"]
                    break
        if game_name:
            guide = await find_guide(game_name, text)
            if guide["text"]:
                # Отправляем текст
                sakura_reply = await ask_gemini(
                    f"Перескажи этот гайд по игре {game_name} своими словами, в своём стиле:\n{guide['text']}"
                )
                await send_as_conversation(message.chat.id, sakura_reply)
                # Отправляем скриншоты если есть
                for img_url in guide["images"][:2]:
                    try:
                        await bot.send_photo(message.chat.id, photo=img_url)
                    except Exception:
                        pass
                return

    await bot.send_chat_action(message.chat.id, "typing")
    _t0 = __import__("time").monotonic()
    reply = await ask_gemini(text + reply_ctx)
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
                except Exception:
                    pass
                if sticker:
                    try:
                        await bot.send_sticker(message.chat.id, sticker)
                    except Exception:
                        pass
                else:
                    gif = get_random_gif(reaction["emotion"])
                    if gif:
                        try:
                            await bot.send_animation(message.chat.id, gif)
                        except Exception:
                            pass
    except Exception:
        pass


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
        client = _gemini_client(key)
        with open(temp_wav, "rb") as f:
            audio_b64 = base64.b64encode(f.read()).decode()
        os.unlink(temp_wav)

        r = await asyncio.to_thread(
            client.models.generate_content,
            model    = MAIN_MODEL,
            contents = [types.Content(parts=[
                types.Part(inline_data=types.Blob(mime_type="audio/wav", data=audio_b64)),
                types.Part(text="Распознай речь, верни только текст."),
            ])],
            config = types.GenerateContentConfig(safety_settings=NO_SAFETY)
        )
        recognized = (r.text or "").strip()
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
        client = _gemini_client(key)
        with open(temp_jpg, "rb") as f:
            img_b64 = base64.b64encode(f.read()).decode()
        os.unlink(temp_jpg)

        caption   = message.caption or "Опиши что на фото — коротко, в своём стиле."
        reply_ctx = _get_reply_context(message)
        r = await asyncio.to_thread(
            client.models.generate_content,
            model    = MAIN_MODEL,
            contents = [types.Content(parts=[
                types.Part(inline_data=types.Blob(mime_type="image/jpeg", data=img_b64)),
                types.Part(text=caption + reply_ctx),
            ])],
            config = types.GenerateContentConfig(
                system_instruction = get_system_prompt(),
                max_output_tokens  = 600,
                temperature        = 0.85,
                safety_settings    = NO_SAFETY,
                thinking_config    = _thinking(MAIN_MODEL),
            )
        )
        mark_key_used(key)
        reply = clean_reply((r.text or "").strip())
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
        client = _gemini_client(key)

        with open(tmp_path, "rb") as f:
            video_b64 = base64.b64encode(f.read()).decode()
        os.unlink(tmp_path)

        caption   = message.caption or "Посмотри это видео и расскажи что происходит — коротко, в своём стиле."
        reply_ctx = _get_reply_context(message)

        r = await asyncio.to_thread(
            client.models.generate_content,
            model    = "gemini-3.1-flash-lite",
            contents = [types.Content(parts=[
                types.Part(inline_data=types.Blob(
                    mime_type="video/mp4",
                    data=video_b64
                )),
                types.Part(text=caption + reply_ctx),
            ])],
            config = types.GenerateContentConfig(
                system_instruction = get_system_prompt(),
                max_output_tokens  = 800,
                temperature        = 0.85,
                safety_settings    = NO_SAFETY,
            )
        )
        mark_key_used(key)
        reply = clean_reply((r.text or "").strip())
        add_to_history("user",  f"[Видео] {caption}")
        add_to_history("model", reply)
        await send_as_conversation(message.chat.id, reply)

    except Exception as e:
        log.error(f"[video] {e}")
        try: os.unlink(tmp_path)
        except: pass
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
        client = _gemini_client(key)

        with open(tmp_path, "rb") as f:
            video_b64 = base64.b64encode(f.read()).decode()
        os.unlink(tmp_path)

        r = await asyncio.to_thread(
            client.models.generate_content,
            model    = "gemini-3.1-flash-lite",
            contents = [types.Content(parts=[
                types.Part(inline_data=types.Blob(
                    mime_type="video/mp4",
                    data=video_b64
                )),
                types.Part(text="Это видео-кружочек от Мастера. Отреагируй на него в своём стиле."),
            ])],
            config = types.GenerateContentConfig(
                system_instruction = get_system_prompt(),
                max_output_tokens  = 400,
                temperature        = 0.9,
                safety_settings    = NO_SAFETY,
            )
        )
        mark_key_used(key)
        reply = clean_reply((r.text or "").strip())
        add_to_history("user",  "[Видео-кружочек]")
        add_to_history("model", reply)
        await send_as_conversation(message.chat.id, reply)

    except Exception as e:
        log.error(f"[video_note] {e}")
        try: os.unlink(tmp_path)
        except: pass
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
                await bot.send_message(MASTER_ID, reply)
        asyncio.create_task(_send_milestone())

    tts_server.start()
    asyncio.create_task(warmup_cache())   # Фаза 6: прогрев TTS-кэша

    # Напоминания: callback для голосового оповещения
    async def _reminder_cb(msg: str):
        ws, dev = _get_active_ws()
        if ws:
            await stream_tts_to_device(msg, ws, dev or "laptop", literal=True)
        await bot.send_message(MASTER_ID, msg)
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
                    await stream_tts_to_device(reply, ws, dev or "laptop", literal=True)

    try:
        from modules.tg_monitor import get_monitor
        tg_mon = get_monitor()
        tg_mon.set_callback(_tg_notif_cb)
        asyncio.create_task(tg_mon.start())
    except Exception as e:
        log.warning(f"[tg_monitor] Не удалось запустить: {e}")

    ws_server = await websockets.serve(ws_handler, "0.0.0.0", 8765, max_size=None)

    # Discord бот в основном event loop (discord.py + voice_recv)
    asyncio.create_task(discord_start_bot())
    log.info("WebSocket сервер запущен на порту 8765")
    await asyncio.gather(
        dp.start_polling(bot),
        ws_server.wait_closed(),
        daily_analysis(),
        proactive_loop(),
        reflection_loop(
            bot                     = bot,
            master_id               = MASTER_ID,
            ask_gemini_fn           = ask_gemini,
            add_to_category_fn      = add_to_category,
            clear_history_fn        = clear_history,
            save_session_summary_fn = save_session_summary,
            load_session_summary_fn = load_session_summary,
            get_history_fn          = get_history,
        ),
    )


if __name__ == "__main__":
    asyncio.run(main())