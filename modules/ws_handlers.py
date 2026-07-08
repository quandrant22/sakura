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
import os
import random
import time as _time

import modules.state as st
from aiogram.types import BufferedInputFile
from config import MASTER_ID, get_active_key, mark_key_used
from modules.command_router import route_command, route_critical, is_irreversible, EXEC_THRESHOLD, GRAY_THRESHOLD
from modules.intent_classifier import classify_intent, is_command as _is_command_check
from modules.chains import match_voice_trigger, list_voice_triggers, list_custom_chains
from modules.tts_server import stream_tts_to_device
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
from modules.reminders import parse_reminder, add_reminder, format_reminders_list
from modules.translator import is_translation_request, try_quick_translate, build_translate_prompt
from modules.fears import detect_fear_trigger
from modules.word_game import (
    is_word_game_request, start_game, get_random_word, format_word_teach,
    check_answer, record_score, get_score, end_game,
    is_game_active, find_word, format_word_of_the_day,
)
from modules.calculator import calculate
from modules.fortune_cookie import is_fortune_request, get_fortune, format_fortune
from modules.music_memory import (
    track_play, like_artist, dislike_artist,
    format_recent, format_top, generate_taste_comment,
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
from modules.weather import get_weather

log = logging.getLogger(__name__)


# ─────────────────────────────────────────────
#  register
# ─────────────────────────────────────────────

async def handle_register(websocket, data, ctx) -> None:
    ask_gemini = ctx["ask_gemini"]
    bot = ctx["bot"]

    device_id = data.get("device_id")
    st.connected_devices[device_id] = websocket
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


# ─────────────────────────────────────────────
#  ping
# ─────────────────────────────────────────────

async def handle_ping(websocket, data, ctx) -> None:
    ask_gemini = ctx["ask_gemini"]
    bot = ctx["bot"]

    device_id = data.get("device_id")
    st.connected_devices[device_id] = websocket
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
       _t_music.monotonic() - st._last_command_ts > 30:
        track = get_current_music_from_window(active_win)
        if track:
            mem = db_get_memory_context()
            prompt = make_music_comment_prompt(track, mem[:200])
            reply = await ask_gemini(prompt, save_history=False)
            if reply:
                await bot.send_message(MASTER_ID, reply)
                mark_music_commented()

    # Presence sync
    await asyncio.to_thread(ps_update, device_id, data)
    transfer = await asyncio.to_thread(check_device_transfer, st.connected_devices)
    if transfer:
        mood_params = await asyncio.to_thread(get_orb_params)
        await broadcast_transfer(transfer, st.connected_devices, mood_params)

    # Фаза 6: мониторинг ПК
    sys_info = data.get("system_info", {})
    if sys_info:
        alert = await asyncio.to_thread(check_pc_health, sys_info)
        if alert:
            reply_pc = await ask_gemini(alert["prompt"], save_history=False)
            if reply_pc:
                await bot.send_message(MASTER_ID, reply_pc)


# ─────────────────────────────────────────────
#  apps_list
# ─────────────────────────────────────────────

async def handle_apps_list(websocket, data, ctx) -> None:
    device_id = data.get("device_id")
    apps      = data.get("apps", {})
    log.info(f"Приложения от {device_id}: {len(apps)}")
    asyncio.create_task(ctx["analyze_apps"](apps, device_id))


# ─────────────────────────────────────────────
#  screen_context
# ─────────────────────────────────────────────

async def handle_screen_context(websocket, data, ctx) -> None:
    screenshot = data.get("screenshot")
    active_win = data.get("active_window", "")
    if screenshot:
        asyncio.create_task(ctx["_analyze_screen_context"](
            screenshot, active_win, data.get("device_id")
        ))


# ─────────────────────────────────────────────
#  kettle_ready
# ─────────────────────────────────────────────

async def handle_kettle_ready(websocket, data, ctx) -> None:
    ask_gemini = ctx["ask_gemini"]
    bot = ctx["bot"]

    temp = data.get("temp", 100)
    dev  = data.get("device_id", "laptop")
    ws_k = st.connected_devices.get(dev)
    prompt = f"Чайник закипел и выключился, температура {temp}°C. Скажи Мастеру одной короткой фразой — чай готов. Без банальщины."
    reply_k = await ask_gemini(prompt, save_history=False)
    if reply_k:
        if ws_k:
            await stream_tts_to_device(reply_k, ws_k, dev, literal=True)
        await bot.send_message(MASTER_ID, reply_k)


# ─────────────────────────────────────────────
#  notification
# ─────────────────────────────────────────────

async def handle_notification(websocket, data, ctx) -> None:
    ask_gemini = ctx["ask_gemini"]
    _get_active_ws = ctx["_get_active_ws"]

    source = data.get("source", "unknown")
    title  = data.get("title", "")
    body   = data.get("body", "")
    try:
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


# ─────────────────────────────────────────────
#  tg_message
# ─────────────────────────────────────────────

async def handle_tg_message(websocket, data, ctx) -> None:
    await ctx["bot"].send_message(MASTER_ID, f"📝 {data.get('text','')}")


# ─────────────────────────────────────────────
#  command_result
# ─────────────────────────────────────────────

async def handle_command_result(websocket, data, ctx) -> None:
    ask_gemini = ctx["ask_gemini"]
    bot = ctx["bot"]
    _resolve_command_status = ctx["_resolve_command_status"]
    _gemini_client = ctx["_gemini_client"]

    result     = data.get("result")
    screenshot = data.get("screenshot")
    dev_name   = data.get("device_id", "устройство")

    # Обновляем статус pending-команды по id или action
    _cmd_ok = True
    _cmd_detail = ""
    _cmd_id_from_agent = data.get("id")
    if _cmd_id_from_agent and _cmd_id_from_agent in st._pending_commands:
        # Агент прислал ack с полем ok
        if "ok" in data:
            _cmd_ok = data["ok"]
            _cmd_detail = data.get("detail", "")
            st._pending_commands[_cmd_id_from_agent]["status"] = "executed" if _cmd_ok else "failed"
            st._pending_commands[_cmd_id_from_agent]["detail"] = _cmd_detail
        else:
            st._pending_commands[_cmd_id_from_agent]["status"] = "executed"
    elif result:
        _cmd_detail = str(result)
        _cmd_ok = not any(t in _cmd_detail.lower() for t in
                          ("ошибка", "не нашла", "не найдено", "app_not_found", "оффлайн"))
        _resolve_command_status(dev_name, _cmd_ok, _cmd_detail)

    # Результат от расширения браузера
    if data.get("ext"):
        ext_data = data["ext"]
        ext_dev  = data.get("device_id", "laptop")
        ext_ws   = st.connected_devices.get(ext_dev)
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
        return
    # Музыкальный ответ — приоритет
    if data.get("music"):
        music  = data["music"]
        dev_m  = data.get("device_id", "laptop")
        ws_m   = st.connected_devices.get(dev_m)
        # Простые управляющие команды не озвучиваем
        _silent_actions = {"music_next", "music_prev", "music_play_pause",
                           "music_like", "music_dislike", "music_shuffle",
                           "music_repeat", "music_mute",
                           "music_volume_up", "music_volume_down"}
        if music.get("action") in _silent_actions:
            # Трекинг лайков/дизлайков для вкуса Сакуры
            if music.get("action") == "music_like" and st._current_track:
                try:
                    like_artist(st._current_track.get("artist", ""), "лайк от Мастера")
                except Exception:
                    pass
            elif music.get("action") == "music_dislike" and st._current_track:
                try:
                    dislike_artist(st._current_track.get("artist", ""), "дизлайк от Мастера")
                except Exception:
                    pass
            return  # молчим
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
        _should_describe = data.get("describe") or st._pending_describe.pop(dev_name, False)
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
                        _dev_ws = st.connected_devices.get(dev_name)
                        if _dev_ws:
                            await stream_tts_to_device(
                                _vtext, _dev_ws, dev_name, literal=True
                            )
            except Exception as _ve:
                log.error(f"[vision] {_ve}")
        # Event-тик игры: анализируем скриншот, не отправляем фото
        if st._pending_event_check.pop(dev_name, False):
            try:
                event = await detect_game_event(screenshot, dev_name)
                if event:
                    ev_reply = await ask_gemini(
                        make_event_prompt(event), save_history=False
                    )
                    if ev_reply:
                        ws_ev = st.connected_devices.get(dev_name)
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


# ─────────────────────────────────────────────
#  voice_command  (~1000 строк, вынос целиком)
# ─────────────────────────────────────────────

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
    generate_image_by_prompt = ctx["generate_image_by_prompt"]
    parse_kettle_command = ctx["parse_kettle_command"]
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
        return

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
        return

    if "протокол чистый лист" in text_lower:
        await _clean_slate()
        if ws_dev:
            phrase = "Протокол выполнен. Я тебя не помню."
            await ws_dev.send(json.dumps({
                "type": "reply", "device_id": device_id or "laptop", "text": phrase,
            }))
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
                msg = text.replace("коммит", "").replace("git commit", "").strip()
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
        return
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
            return
        try:
            await bot.send_message(int(vip_id), msg)
            log.info("voice->vip SENT OK")
            await _sayv(f"Передала {vip_name.capitalize()}.")
        except Exception as e:
            log.error(f"voice->vip SEND FAIL: {e}")
            await _sayv("Не получилось отправить, Мастер.")
        return

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
            return

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
        return

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
        return

    # "что напоминания" — список
    if any(w in text.lower() for w in ("напоминания", "напомни мне", "таймеры", "что напомни")):
        _rem_list = format_reminders_list()
        if ws_dev:
            await stream_tts_to_device(_rem_list, ws_dev, device_id or "laptop", literal=True)
        return

    # ── ПЕРЕВОДЧИК ──────────────────────────────────────
    if is_translation_request(text):
        _quick = try_quick_translate(text)
        if _quick:
            log.info(f"[translate] quick: {text!r} → {_quick}")
            if ws_dev:
                await stream_tts_to_device(_quick, ws_dev, device_id or "laptop", literal=True)
            return
        # Fallback через Gemini
        _tr_prompt = build_translate_prompt(text)
        _tr_reply = await ask_gemini(_tr_prompt, save_history=False)
        if _tr_reply and ws_dev:
            await stream_tts_to_device(_tr_reply, ws_dev, device_id or "laptop", literal=True)
        return

    # ── СТРАХИ САКУРЫ ─────────────────────────────────
    _fear = detect_fear_trigger(text)
    if _fear:
        log.info(f"[fears] сработал: {_fear['name']}")
        if ws_dev:
            await stream_tts_to_device(_fear["response"], ws_dev, device_id or "laptop", literal=True)
        return

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
        return

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
                return

    # "слово дня"
    if any(w in text.lower() for w in ("слово дня", "какое слово сегодня")):
        _wotd = format_word_of_the_day()
        if ws_dev:
            await stream_tts_to_device(_wotd, ws_dev, device_id or "laptop", literal=True)
        return

    # "счёт" / "сколько слов"
    if any(w in text.lower() for w in ("счёт слов", "сколько слов", "результат игры")):
        _sc = get_score()
        if ws_dev:
            await stream_tts_to_device(_sc, ws_dev, device_id or "laptop", literal=True)
        return

    # "стоп игра" / "хватит играть"
    if any(w in text.lower() for w in ("хватит играть", "стоп игра", "закончим игру", "выход из игры")):
        _end = end_game()
        if ws_dev:
            await stream_tts_to_device(_end, ws_dev, device_id or "laptop", literal=True)
        return

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
        return

    # ── КАЛЬКУЛЯТОР (без LLM) ───────────────────────────
    _calc_result = calculate(text)
    if _calc_result:
        log.info(f"[calc] {text!r} → {_calc_result}")
        if ws_dev:
            await stream_tts_to_device(_calc_result, ws_dev, device_id or "laptop", literal=True)
        return

    # ── ПЕЧЕНЬЕ С ПРЕДСКАЗАНИЯМИ (без LLM) ─────────────
    if is_fortune_request(text):
        _fortune = get_fortune()
        _fortune_reply = format_fortune(_fortune)
        log.info(f"[fortune] period={_fortune['period']}")
        if ws_dev:
            await stream_tts_to_device(_fortune_reply, ws_dev, device_id or "laptop", literal=True)
        return

    # ── КРИТИЧЕСКИЕ КОМАНДЫ (точный матчинг, без LLM) ────
    kettle_cmd = parse_kettle_command(text)
    if kettle_cmd and ws_dev:
        st._last_command_ts = __import__('time').monotonic()
        await ws_dev.send(json.dumps({"type": "command", "action": kettle_cmd["action"]}))
        _kreply = await ask_gemini(
            f"Мастер попросил: {text}. Команда: {kettle_cmd['action']}. Скажи коротко.",
            save_history=False)
        if _kreply:
            await stream_tts_to_device(_kreply, ws_dev, device_id or "laptop", literal=True)
        # Провод 3: действие становится эпизодом
        try:
            from modules.disposition import current as _disp_ep
            _dep = _disp_ep()
            add_episode(
                text=f"Выполнила команду: {text[:80]} → {kettle_cmd['action']}",
                emotion=_dep["stance"],
                valence=_dep["valence"],
                arousal=_dep["arousal"],
                context=data.get("active_window", ""),
            )
        except Exception:
            pass
        return

    _critical = route_critical(text)
    if _critical and ws_dev:
        st._last_command_ts = __import__('time').monotonic()
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
            _dep = _disp_ep()
            add_episode(
                text=f"Выполнила команду: {text[:80]} → {_critical}",
                emotion=_dep["stance"],
                valence=_dep["valence"],
                arousal=_dep["arousal"],
                context=data.get("active_window", ""),
            )
        except Exception:
            pass
        return

    # ── ПОДТВЕРЖДЕНИЕ ПЛАНА ─────────────────────────────
    _mk = device_id or "tg"
    _now_ts = __import__("time").monotonic()
    if _mk in st._pending_plan:
        _pp = st._pending_plan[_mk]
        if _now_ts - _pp["ts"] < 60:
            _pp_text = text.lower().strip().rstrip(".!?,")
            if _pp_text in ("да", "давай", "делай", "точно", "ага", "угу", "конечно"):
                del st._pending_plan[_mk]
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
                return
            elif _pp_text in ("нет", "стоп", "отмена", "хватит"):
                del st._pending_plan[_mk]
                _deny = "Хорошо, отменила."
                if ws_dev:
                    await stream_tts_to_device(
                        _deny, ws_dev, device_id or "laptop", literal=True)
                else:
                    await bot.send_message(MASTER_ID, _deny)
                return
            else:
                del st._pending_plan[_mk]
        else:
            del st._pending_plan[_mk]

    # ── ОТМЕНА ПЛАНА: «стоп»/«отмена» во время исполнения ──
    _tlow = text.lower().strip().rstrip(".!?,")
    if _tlow in ("стоп", "отмена", "хватит", "стоп план", "отмена плана"):
        if _mk in st._pending_plan:
            del st._pending_plan[_mk]
        st._plan_cancel[_mk] = True

    # ── УТОЧНЕНИЕ: проверяем ответ на предыдущий вопрос ──
    if _mk in st._pending_clarify:
        _pc = st._pending_clarify[_mk]
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
                    _router_ctx = {
                        "active_window": data.get("active_window", ""),
                        "current_track": st._current_track,
                    }
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

            del st._pending_clarify[_mk]

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
                return
            # Отбой — ничего не делаем
            return
        else:
            del st._pending_clarify[_mk]

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
                except Exception:
                    pass
        st._last_executed.pop(_mk, None)

    # ── LLM-РОУТЕР (все остальные команды) ──────────────
    _router_ctx = {
        "active_window": data.get("active_window", ""),
        "current_track": st._current_track,
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
                    st._pending_clarify[_mk] = {
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
                    st._pending_clarify[_mk] = {
                        "text": text,
                        "main": _routed,
                        "alt": None,
                        "ts": __import__("time").monotonic(),
                    }
                except Exception:
                    pass
            return

        # Зона 4: низкая уверенность — пробуем планировщик
        else:
            if _is_command_check(text):
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
                    return
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
            return

    # ── ПЛАНИРОВЩИК: route_command вернул None ──────────
    if not _routed:
        if _is_command_check(text):
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
            tws = st.connected_devices.get(dev, ws_dev)
            if full_action.startswith("say:"):
                await stream_tts_to_device(full_action[4:], tws, dev, literal=True)
            elif full_action.startswith("open_app:") or full_action.startswith("close_window:"):
                # Для открытия приложений нужен resolve_app
                app_query = full_action.split(":", 1)[1] if ":" in full_action else arg
                from modules.device_commands import resolve_app
                _, target = resolve_app(app_query, device_id)
                if target:
                    _cmd_id = _register_command(f"open_app:{target}", dev)
                    await tws.send(json.dumps({"type": "command", "action": f"open_app:{target}", "id": _cmd_id}))
                    # Записать запуск для умных дефолтов
                    try:
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
                    await stream_tts_to_device(
                        _creply, ws_dev, device_id or "laptop", literal=True)
            except Exception:
                pass

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
        except Exception:
            pass

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


# ─────────────────────────────────────────────
#  current_track update (runs for ALL messages)
# ─────────────────────────────────────────────

def update_current_track(data) -> None:
    """Обновляет текущий трек из любого сообщения агента."""
    if data.get("current_track"):
        track = data["current_track"]
        _prev = dict(st._current_track)
        st._current_track.update(track)
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
