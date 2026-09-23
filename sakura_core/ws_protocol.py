"""Обработчики WebSocket-протокола: register, ping, apps_list, screen_context,
kettle_ready, notification, tg_message, command_result, update_current_track.

Перенесено из modules/ws_handlers.py (7C-1). Протокол не меняется —
только перемещение функций. Каждый хендлер принимает (websocket, data, ctx),
ctx — словарь зависимостей из main.py.
"""

from __future__ import annotations

import asyncio
import base64
import json
import logging
import re
import time as _time

import modules.state as st
from config import MASTER_ID, get_active_key, mark_key_used, MAIN_MODEL
from sakura_core.llm import generate as _llm_generate
from modules.tts_server import stream_tts_to_device
from modules.device_manager import update_device
from modules.window_watcher import update as watcher_update
from modules.proactive_recs import track_activity as track_rec_activity
from modules.steam_integration import get_current_game
from modules.integrations import (
    should_comment_music, get_current_music_from_window,
    make_music_comment_prompt, mark_music_commented,
)
from modules.mood_vector import get_orb_params
from modules.evening_pulse import check_pc_health
from modules.presence_sync import update as ps_update, check_device_transfer, broadcast_transfer
from modules.notification_tracker import add_notification
from modules.music_memory import track_play, like_artist, dislike_artist, generate_taste_comment
from modules.game_detector import detect_game_event, make_event_prompt
from modules.rituals import should_greet_device, get_greeting_prompt
from modules.briefing import should_brief, run_briefing
from modules.ws_auth import is_master_device
from memory.db import get_memory_context as db_get_memory_context
from aiogram.types import BufferedInputFile

log = logging.getLogger(__name__)

# ── Константы ──────────────────────────────────────────────────────────

_DANGEROUS_SYSTEM_ACTIONS = frozenset({"system:shutdown", "system:restart", "system:sleep"})
_SYSTEM_CONFIRM_PROMPTS = {
    "system:shutdown": "Выключаю компьютер. Подтверждаешь?",
    "system:restart": "Перезагружаю компьютер. Подтверждаешь?",
    "system:sleep": "Отправляю компьютер в сон. Подтверждаешь?",
}


# ── register ───────────────────────────────────────────────────────────

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

    if is_master_device(device_id) and should_greet_device(device_id):
        greeting = await ask_gemini(get_greeting_prompt(), save_history=False)
        if greeting:
            await bot.send_message(MASTER_ID, greeting)

    try:
        if is_master_device(device_id) and await asyncio.to_thread(should_brief):
            asyncio.create_task(run_briefing(
                device_id, websocket, ask_gemini, stream_tts_to_device,
                telegram_bot=bot, master_id=MASTER_ID,
            ))
    except Exception as e:
        log.debug(f"briefing: {e}")

    await asyncio.to_thread(ps_update, device_id, data)


# ── ping ───────────────────────────────────────────────────────────────

async def handle_ping(websocket, data, ctx) -> None:
    ask_gemini = ctx["ask_gemini"]
    bot = ctx["bot"]

    device_id = data.get("device_id")
    st.connected_devices[device_id] = websocket
    update_device(device_id,
        active_window = data.get("active_window"),
        context       = data.get("context"),
        system_info   = data.get("system_info"))

    active_win = data.get("active_window", "")
    await asyncio.to_thread(watcher_update, device_id,
        active_win, data.get("system_info", {}))

    sys_info = data.get("system_info", {})
    focus_sec = data.get("focus_seconds", 0)
    act_level = data.get("activity_level", 0.0)

    if sys_info.get("cpu_temp") or sys_info.get("gpu_temp"):
        try:
            from modules.vps_monitor import _apply_agent_temps
            _apply_agent_temps(sys_info)
        except Exception as e:
            log.debug(f"[ws] handle_ping: {type(e).__name__}: {e}")

    if focus_sec and focus_sec > 120:
        try:
            from modules.context import set_focus_duration
            set_focus_duration(active_win, focus_sec)
        except Exception as e:
            log.debug(f"[ws] handle_ping: {type(e).__name__}: {e}")

    if act_level > 0:
        try:
            from modules.disposition import _set_activity_hint
            _set_activity_hint(act_level)
        except Exception as e:
            log.debug(f"[ws] handle_ping: {type(e).__name__}: {e}")

    if active_win:
        await asyncio.to_thread(track_rec_activity, active_win)
        asyncio.create_task(get_current_game(active_win))


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

    await asyncio.to_thread(ps_update, device_id, data)
    transfer = await asyncio.to_thread(check_device_transfer, st.connected_devices)
    if transfer:
        mood_params = await asyncio.to_thread(get_orb_params)
        await broadcast_transfer(transfer, st.connected_devices, mood_params)

    sys_info = data.get("system_info", {})
    if sys_info:
        alert = await asyncio.to_thread(check_pc_health, sys_info)
        if alert:
            reply_pc = await ask_gemini(alert["prompt"], save_history=False)
            if reply_pc:
                await bot.send_message(MASTER_ID, reply_pc)


# ── apps_list ──────────────────────────────────────────────────────────

async def handle_apps_list(websocket, data, ctx) -> None:
    device_id = data.get("device_id")
    apps      = data.get("apps", {})
    log.info(f"Приложения от {device_id}: {len(apps)}")
    # Список нужен не только LLM-маппингу: фильтр param.resolve
    # (installed_apps) матчит по нему однословные «открой/покажи».
    # Агент присылает apps_list после каждой регистрации, так что список
    # обновляется при каждом подключении. Разговорные имена («дискорд»)
    # добираются из маппинга; анализатор (analyze_apps) освежит их после
    # сборки нового маппинга.
    from sakura_core.registry import set_installed_apps
    from modules.app_mapping import mapping_names
    set_installed_apps(apps, extra=mapping_names(device_id))
    asyncio.create_task(ctx["analyze_apps"](apps, device_id))


# ── screen_context ─────────────────────────────────────────────────────

async def handle_screen_context(websocket, data, ctx) -> None:
    screenshot = data.get("screenshot")
    active_win = data.get("active_window", "")
    if screenshot:
        asyncio.create_task(ctx["_analyze_screen_context"](
            screenshot, active_win, data.get("device_id")
        ))


# ── kettle_ready ───────────────────────────────────────────────────────

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


# ── notification ───────────────────────────────────────────────────────

async def handle_notification(websocket, data, ctx) -> None:
    ask_gemini = ctx["ask_gemini"]
    _get_active_ws = ctx["_get_active_ws"]

    source = data.get("source", "unknown")
    title  = data.get("title", "")
    body   = data.get("body", "")
    try:
        notif = add_notification(source, title, body)
        if notif and notif.urgent:
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


# ── tg_message ─────────────────────────────────────────────────────────

async def handle_tg_message(websocket, data, ctx) -> None:
    await ctx["bot"].send_message(MASTER_ID, f"📝 {data.get('text','')}")


# ── command_result ─────────────────────────────────────────────────────

async def handle_command_result(websocket, data, ctx) -> None:
    ask_gemini = ctx["ask_gemini"]
    bot = ctx["bot"]
    _resolve_command_status = ctx["_resolve_command_status"]

    result     = data.get("result")
    screenshot = data.get("screenshot")
    dev_name   = data.get("device_id", "устройство")

    _cmd_ok = True
    _cmd_detail = ""
    _cmd_id_from_agent = data.get("id")
    if _cmd_id_from_agent and _cmd_id_from_agent not in st._pending_commands:
        log.warning(
            f"[ws] command_result с НЕИЗВЕСТНЫМ id={_cmd_id_from_agent!r} "
            f"(device={data.get('device_id')}) — ожидались: "
            f"{[k for k, v in st._pending_commands.items() if v['status'] == 'sent'][-5:]}")
    if _cmd_id_from_agent and _cmd_id_from_agent in st._pending_commands:
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

    if data.get("ext"):
        ext_data = data["ext"]
        ext_dev  = data.get("device_id", "laptop")
        ext_ws   = st.connected_devices.get(ext_dev)
        if ext_data.get("ok"):
            if ext_data.get("result") and isinstance(ext_data["result"], dict):
                r = ext_data["result"]
                _page_prompt = (
                    f"Видео на YouTube: {r.get('title','?')} — канал {r.get('channel','?')}. "
                    f"{'Описание: ' + r['description'] if r.get('description') else ''} "
                    f"Расскажи Мастеру об этом видео коротко в своём стиле."
                )
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
                    log.info(f"[голос] ответ: {_page_reply!r}")
                    await stream_tts_to_device(_page_reply, ext_ws, ext_dev, literal=True)
        return

    if data.get("music"):
        music  = data["music"]
        _late_answered = False
        log.info(
            f"[music] command_result получен: id агента={_cmd_id_from_agent!r}, "
            f"в pending={_cmd_id_from_agent in st._pending_commands}, "
            f"action={music.get('action')}, "
            f"detail={(_cmd_detail or music.get('result',''))[:80]!r}")
        if _cmd_id_from_agent and _cmd_id_from_agent in st._pending_commands:
            _pend = st._pending_commands[_cmd_id_from_agent]
            _late_answered = bool(_pend.get("answered")) and not _pend.get("spoken")
            _pend["spoken"] = True
        dev_m  = data.get("device_id", "laptop")
        if _late_answered:
            _info_late = music.get("info") or {}
            log.info(f"[music] поздний результат для уже отвеченного "
                     f"now_playing — молча: {_info_late.get('artist','?')} — {_info_late.get('title','?')}")
            try:
                track_play(_info_late.get("artist", ""),
                           _info_late.get("title", ""),
                           _info_late.get("album", ""))
            except Exception as e:
                log.debug(f"[ws] late now_playing: {type(e).__name__}: {e}")
            return
        ws_m   = st.connected_devices.get(dev_m)
        # «Будет ли ответ от модели» — из реестра, а не из захардкоженного
        # списка: followup == llm → command_result зовёт модель и озвучивает
        # сам; followup == ack → молча (ответ уже дан — «Готово» в мосте).
        from sakura_core.registry import followup_for as _followup_for
        if _followup_for(music.get("action", "")) == "ack":
            if music.get("action") == "music_like" and st._current_track:
                try:
                    like_artist(st._current_track.get("artist", ""), "лайк от Мастера")
                except Exception as e:
                    log.debug(f"[ws] handle_command_result: {type(e).__name__}: {e}")
            elif music.get("action") == "music_dislike" and st._current_track:
                try:
                    dislike_artist(st._current_track.get("artist", ""), "дизлайк от Мастера")
                except Exception as e:
                    log.debug(f"[ws] handle_command_result: {type(e).__name__}: {e}")
            return
        elif "tracks" in music and music["tracks"]:
            items = music["tracks"][:8]
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
                f"Сейчас играет: {info.get('artist','?')} — {info.get('title','?')}. "
                f"Статус: {info.get('status','?')}. "
                f"Прогресс: {info.get('position','?:??')} из {info.get('duration','?:??')} ({info.get('progress',0)}%). "
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
            try:
                track_play(info.get("artist", ""), info.get("title", ""), info.get("album", ""))
            except Exception as e:
                log.debug(f"[ws] handle_command_result: {type(e).__name__}: {e}")
            _taste_comment = generate_taste_comment(info.get("artist", ""))
            if _taste_comment:
                prompt += f"\n\nКстати, у тебя есть мнение об этом исполнителе: {_taste_comment}"
        else:
            prompt = f"Результат: {music.get('result', 'готово')}. Скажи коротко."
        music_reply = await ask_gemini(prompt, save_history=False)
        if music_reply:
            log.info(f"[голос] ответ: {music_reply!r}")
            if ws_m:
                await stream_tts_to_device(music_reply, ws_m, dev_m, literal=True)
            await bot.send_message(MASTER_ID, music_reply)
    elif screenshot:
        _should_describe = data.get("describe") or st._pending_describe.pop(dev_name, False)
        if _should_describe:
            try:
                img_bytes = base64.b64decode(screenshot)
                key = get_active_key()
                if key:
                    from google.genai import types as _gt
                    _vtext = await _llm_generate(
                        [
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
                        model=MAIN_MODEL,
                        safety=False,
                        thinking=False,
                    )
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


# ── update_current_track ───────────────────────────────────────────────

def update_current_track(data) -> None:
    """Обновляет текущий трек из любого сообщения агента."""
    if data.get("current_track"):
        track = data["current_track"]
        _prev = dict(st._current_track)
        st._current_track.update(track)
        log.debug(f"[track] Трек: {track.get('artist','')} — {track.get('title','')} [{track.get('status','')}]")
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
                except Exception as e:
                    log.debug(f"[ws] update_current_track: {type(e).__name__}: {e}")
