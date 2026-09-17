"""Telegram-адаптер: bot, dp, send utilities, all TG handlers.

Stage 7D-2: bot, dp, cmd_*, handle_* перенесены из main.py.
"""

from __future__ import annotations

import asyncio
import inspect
import json
import logging
import os
import re
import subprocess
import tempfile
import time

import psutil
from aiogram import Bot, Dispatcher, F
from aiogram.filters import CommandStart, Command
from aiogram.types import Message, LinkPreviewOptions

from config import (
    TELEGRAM_TOKEN, MASTER_ID, GROUP_CHAT_ID,
    get_active_key, mark_key_used, MAIN_MODEL,
)
from personality import get_system_prompt
from modules.users import (
    get_role, is_master, is_himari,
    add_guest_message, format_master_notification, get_user_data,
    get_guest_summaries, add_vip, add_trusted, remove_user, block_user, list_users,
)
from modules.device_manager import get_device_status, parse_device_from_text, get_online_devices
from modules.device_commands import parse as device_parse
from modules.state import (
    connected_devices, check_confirmation,
)
import modules.state as _state_mod
from modules.tts_server import stream_tts_to_device
from modules.state_arbiter import get_current_emotion
from sakura_core.llm import (
    ask_gemini, ask_gemini_as_guest, _strip_tone,
    get_client, generate as _llm_generate, clean_reply,
)
from sakura_core.prompt import _get_reply_context
from sakura_core.memory_tasks import clean_slate
from modules.command_router import route_command
from modules.app_mapping import resolve_app, find_vip_by_name
from modules.proactive import update_master_status
from modules.rituals import mark_master_interaction
from modules.mood_vector import mark_interaction as mood_mark_interaction, update_master_mood
from modules.relationship import (
    increase_closeness, extract_topics_from_text, track_topic,
)
from modules.speech_style import track_message as track_speech
from modules.emotional_memory import (
    track_topic_reaction, detect_joke_about_sakura, save_joke,
)
from modules.autonomous import is_voice_note_request, save_voice_note
from modules.chains import parse_chain, run_chain
from modules.reactions import should_react, detect_reaction, get_random_gif
from modules.steam_integration import recommend_games, get_library, find_guide
from modules.guest_relations import detect_relation_from_text, set_relation
from memory.memory import add_to_history, clear_history, clear_session_summary
from memory.db import get_memory_context as db_get_memory_context
from modules.tasks import get_tasks_context
from adapters.voice import _get_active_ws
from modules.voice_info import is_info_action
# ws_handlers: lazy to avoid circular (ws_handlers → main → adapters.telegram)
# execute_critical_action and answer_voice_info imported lazily in handle_message

log = logging.getLogger("sakura.telegram")

_START = time.monotonic()

bot = Bot(token=TELEGRAM_TOKEN)
dp = Dispatcher()

# ── Send utilities ─────────────────────────────────────────────

from sakura_core.send import (
    _split_into_parts as _shared_split,
    strip_payload_words, has_tg_trigger, voice_to_tg,
    send_to_master as _shared_send_to_master,
    send_telegram_text as _shared_send_telegram_text,
    send_safe as _shared_send_safe,
    send_as_conversation as _shared_send_as_conversation,
)


async def send_to_master(text: str, **kwargs):
    return await _shared_send_to_master(bot, MASTER_ID, text, **kwargs)


async def send_telegram_text(chat_id: int, text: str, **kwargs):
    return await _shared_send_telegram_text(bot, MASTER_ID, chat_id, text, **kwargs)


async def send_safe(chat_id: int, text: str):
    return await _shared_send_safe(bot, MASTER_ID, chat_id, text)


async def send_as_conversation(chat_id: int, text: str):
    return await _shared_send_as_conversation(bot, MASTER_ID, chat_id, text)


# ── Command handlers ───────────────────────────────────────────

def _register_commands():
    """Register all TG command handlers as thin wrappers."""
    from adapters.commands import (
        cmd_help_impl, cmd_health_impl, cmd_restart_impl, cmd_start_impl,
        cmd_status_impl, cmd_memory_impl, cmd_tasks_impl, cmd_clear_impl,
        cmd_clean_slate_impl, cmd_guests_impl, cmd_vip_impl, cmd_trusted_impl,
        cmd_users_impl, cmd_unvip_impl, cmd_block_impl,
    )
    def _master_only(impl, **extra_kw):
        async def _h(message: Message):
            if not is_master(message.from_user.id):
                return
            await impl(message, **extra_kw)
        return _h
    dp.message(Command("помощь"))(_master_only(cmd_help_impl))
    dp.message(Command("health"))(_master_only(cmd_health_impl))
    dp.message(Command("restart"))(_master_only(cmd_restart_impl))
    dp.message(CommandStart())(_master_only(cmd_start_impl, ask_gemini=ask_gemini))
    dp.message(Command("status"))(_master_only(cmd_status_impl))
    dp.message(Command("memory"))(_master_only(cmd_memory_impl))
    dp.message(Command("tasks"))(_master_only(cmd_tasks_impl))
    dp.message(Command("clear"))(_master_only(cmd_clear_impl, ask_gemini=ask_gemini))
    dp.message(Command("чистыйлист"))(_master_only(cmd_clean_slate_impl, clean_slate_fn=clean_slate))
    dp.message(Command("гости"))(_master_only(cmd_guests_impl))
    dp.message(Command("vip"))(_master_only(cmd_vip_impl))
    dp.message(Command("trusted"))(_master_only(cmd_trusted_impl))
    dp.message(Command("users"))(_master_only(cmd_users_impl))
    dp.message(Command("unvip"))(_master_only(cmd_unvip_impl))
    dp.message(Command("block"))(_master_only(cmd_block_impl))

_register_commands()


# ── Device control ─────────────────────────────────────────────

def _resolve_device(text_lower: str) -> tuple[str, str]:
    from modules.presence_sync import get_active_device
    dev = get_active_device()
    return dev or "laptop", ""


@dp.message(Command("устройство"))
async def device_control(message: Message):
    if not is_master(message.from_user.id):
        return
    text = (message.text or "").removeprefix("/устройство").strip()
    if not text:
        await message.answer("Что сделать с устройством? (выкл, перезагрузка, спящий режим)")
        return
    dev_id, _ = _resolve_device(text.lower())
    ws = connected_devices.get(dev_id)
    if not ws:
        await message.answer("Устройство оффлайн.")
        return
    cmd_map = {
        "выкл": "system.shutdown",
        "выключить": "system.shutdown",
        "перезагрузка": "system.restart",
        "перезагрузить": "system.restart",
        "спящий": "system.sleep",
        "спящий режим": "system.sleep",
        "спать": "system.sleep",
    }
    action = None
    for key, val in cmd_map.items():
        if key in text.lower():
            action = val
            break
    if not action:
        await message.answer("Не поняла команду. Доступно: выкл, перезагрузка, спящий режим.")
        return
    await ws.send(json.dumps({"type": "command", "action": action}))
    await message.answer(f"Команда {action} отправлена на {dev_id}.")
    await asyncio.sleep(0.3)
    if action == "system.shutdown":
        asyncio.create_task(stream_tts_to_device(
            "Выключаюсь, Мастер. Спокойной ночи.", ws, dev_id,
            literal=True, emotion=get_current_emotion()))


# ── Message handler (main) ─────────────────────────────────────

@dp.message(F.text)
async def handle_message(message: Message):
    _TG_ROUTER_SKIP = {"привет", "приветик", "здравствуй", "здаров", "ладно",
                       "ок", "окей", "ага", "угу", "да", "нет", "спасибо",
                       "благодарю", "понял", "понятно", "класс", "круто",
                       "отлично", "давай", "хорошо", "доброе утро", "добрый вечер"}
    from modules.capsules import (is_capsule_request, parse_open_date,
        create_capsule, make_create_prompt)
    from modules.audio_control import handle_audio_command
    from modules.ws_handlers import execute_critical_action, answer_voice_info
    from adapters.group_chat import (handle_group_message, handle_guest_private,
        handle_reply_to_notification, handle_device_command)

    # ── Групповой чат ─────────────────────────────────────────────
    if await handle_group_message(
        message, bot=bot, ask_gemini=ask_gemini,
        ask_gemini_as_guest=ask_gemini_as_guest,
        send_to_master=send_to_master,
        send_as_conversation=send_as_conversation,
        stream_tts_to_device=stream_tts_to_device,
        get_current_emotion=get_current_emotion,
        GROUP_CHAT_ID=GROUP_CHAT_ID, get_role=get_role, is_himari=is_himari,
        add_guest_message=add_guest_message,
        update_master_status=update_master_status,
        mark_master_interaction=mark_master_interaction,
        mood_mark_interaction=mood_mark_interaction,
        update_master_mood=update_master_mood,
        increase_closeness=increase_closeness,
        extract_topics_from_text=extract_topics_from_text,
        track_topic=track_topic, track_speech=track_speech,
        track_topic_reaction=track_topic_reaction,
        detect_joke_about_sakura=detect_joke_about_sakura,
        save_joke=save_joke,
        is_voice_note_request=is_voice_note_request,
        save_voice_note=save_voice_note,
        is_capsule_request=is_capsule_request,
        parse_open_date=parse_open_date,
        create_capsule=create_capsule,
        make_create_prompt=make_create_prompt,
        parse_chain=parse_chain, run_chain=run_chain,
        connected_devices=connected_devices,
        handle_audio_command=handle_audio_command,
    ):
        return

    # ── Личный чат: гость ──────────────────────────────────────────
    _user_role = get_role(message.from_user.id)
    if _user_role != "master":
        if await handle_guest_private(
            message, bot=bot,
            ask_gemini_as_guest=ask_gemini_as_guest,
            ask_gemini=ask_gemini,
            send_to_master=send_to_master,
            send_as_conversation=send_as_conversation,
            get_role=get_role,
            format_master_notification=format_master_notification,
            get_user_data=get_user_data,
        ):
            return

    # ── Мастер ────────────────────────────────────────────────────
    text       = message.text
    text_lower = text.lower()
    _text_raw  = text
    log.info(f"[вход] {text[:300]!r}")
    update_master_status(text)

    from sakura_core.tts_control import is_tts_stop
    if is_tts_stop(text_lower):
        try:
            from modules.state import tts_request_stop_anywhere
            if tts_request_stop_anywhere():
                await bot.send_message(MASTER_ID, "Хорошо, остановилась.")
        except Exception:
            pass
        return

    from sakura_core.bridge import handle_v3_confirm
    from sakura_core.executor import execute_critical_action as _exec_crit
    async def _v3_on_execute(action):
        ws, dev = _get_active_ws()
        if ws:
            await _exec_crit(action.replace(".", ":", 1), ws, dev, text, "", ask_gemini)
            await message.answer("Готово.")
        else:
            await message.answer("Устройство отключилось, не могу выполнить.")
    async def _v3_on_cancel():
        await message.answer("Хорошо, отменила.")
    if await handle_v3_confirm(text, on_execute=_v3_on_execute, on_cancel=_v3_on_cancel):
        return

    if "tg" in _state_mod._pending_system:
        _ps = _state_mod._pending_system["tg"]
        if __import__("time").monotonic() - _ps["ts"] < 60:
            _ps_result = check_confirmation(text_lower)
            if _ps_result == "confirm":
                del _state_mod._pending_system["tg"]
                laptop_ws, _active_dev = _get_active_ws()
                if laptop_ws:
                    await execute_critical_action(_ps["action"], laptop_ws, _active_dev, text, "", ask_gemini)
                    await message.answer("Готово.")
                else:
                    await message.answer("Устройство отключилось, не могу выполнить.")
                return
            elif _ps_result == "deny":
                del _state_mod._pending_system["tg"]
                await message.answer("Хорошо, отменила.")
                return
            else:
                del _state_mod._pending_system["tg"]
        else:
            del _state_mod._pending_system["tg"]

    from modules.voice_info import pending_forget_active as _pfa, memory_forget_confirm as _mfc
    if _pfa():
        _fg = _mfc(text)
        if _fg is not None:
            await message.answer(_fg[0])
            return

    from sakura_core.bridge import resolve_conv_reply

    async def _tg_resolve_reply(_r):
        await resolve_conv_reply(
            _r, text=text,
            deliver=lambda t: send_as_conversation(message.chat.id, t) if t else None,
            ask_gemini_fn=ask_gemini,
            get_active_ws_fn=_get_active_ws,
            clean_slate_fn=clean_slate,
            strip_tone_fn=_strip_tone,
            on_photo=lambda url: bot.send_photo(message.chat.id, photo=url),
            send_vip_fn=lambda vip_id, txt: bot.send_message(vip_id, txt),
        )

    try:
        from sakura_core.bridge import v3_fast_path
        _laptop_ws, _laptop_dev = _get_active_ws()
        if await v3_fast_path(text, data={"active_window": ""},
                              device_ws=_laptop_ws, device_id=_laptop_dev,
                              register_command=None, ack=message.answer,
                              resolve_reply=_tg_resolve_reply):
            return
    except Exception as _v3_err:
        log.debug(f"[v3] быстрый путь: {type(_v3_err).__name__}: {_v3_err}")

    _tg_short = text_lower.strip().rstrip("!.?,")
    if (not message.reply_to_message
            and _tg_short not in _TG_ROUTER_SKIP
            and len(_tg_short.split()) > 1):
        try:
            _tg_routed = await route_command(text, context=None)
        except Exception as e:
            log.debug(f"[tg] info route: {type(e).__name__}: {e}")
            _tg_routed = None
        if _tg_routed and is_info_action(_tg_routed.get("action", "")):
            import modules.state as _st
            _st._last_command_ts = __import__("time").monotonic()
            log.info(f"[tg/voice_info] {text[:300]!r} → {_tg_routed}")
            await answer_voice_info(
                _tg_routed.get("action", ""), _tg_routed.get("arg", "") or "",
                text, None, None, ask_gemini, bot)
            return

    reply_ctx = _get_reply_context(message)

    if await handle_reply_to_notification(
        message, text, ask_gemini, send_as_conversation, bot,
        detect_relation_from_text=detect_relation_from_text,
        set_relation=set_relation,
    ):
        return

    asked   = parse_device_from_text(text)
    dev_id  = asked or next(iter(get_online_devices()), None) or "laptop"
    if await handle_device_command(
        message, text, dev_id, connected_devices,
        stream_tts_to_device=stream_tts_to_device,
        get_current_emotion=get_current_emotion,
        parse_device_from_text=parse_device_from_text,
        get_online_devices=get_online_devices,
        resolve_app=resolve_app,
        device_parse=device_parse,
    ):
        return

    _t0 = __import__("time").monotonic()
    reply = await ask_gemini(_text_raw + reply_ctx)
    log.info(f"[ответ] {__import__('time').monotonic()-_t0:.1f}с | {reply!r}")
    await send_as_conversation(message.chat.id, reply)

    try:
        from sakura_core.reactions import get_mood_reaction, get_sticker_or_gif
        reaction = get_mood_reaction(text)
        if reaction:
            sticker, gif = get_sticker_or_gif(reaction["emotion"])
            if sticker:
                try:
                    await bot.send_sticker(message.chat.id, sticker)
                except Exception as e:
                    log.debug(f"[tg] reaction sticker: {type(e).__name__}: {e}")
            elif gif:
                try:
                    await bot.send_animation(message.chat.id, gif)
                except Exception as e:
                    log.debug(f"[tg] reaction gif: {type(e).__name__}: {e}")
    except Exception as e:
        log.debug(f"[tg] reaction: {type(e).__name__}: {e}")


# ── Voice / Photo / Video handlers ─────────────────────────────

# ── Media handlers ─────────────────────────────────────────────

def _register_media():
    from adapters.media import (
        handle_voice_impl, handle_photo_impl,
        handle_video_impl, handle_video_note_impl,
    )
    def _media_handler(impl, **extra_kw):
        async def _h(message: Message):
            await impl(message, bot=bot, is_master=is_master,
                       get_active_key=get_active_key, get_client=get_client,
                       mark_key_used=mark_key_used, ask_gemini=ask_gemini,
                       send_as_conversation=send_as_conversation,
                       _get_reply_context=_get_reply_context,
                       get_system_prompt=get_system_prompt,
                       clean_reply=clean_reply, add_to_history=add_to_history,
                       log=log, **extra_kw)
        return _h
    dp.message(F.voice)(_media_handler(handle_voice_impl))
    dp.message(F.photo)(_media_handler(handle_photo_impl))
    dp.message(F.video)(_media_handler(handle_video_impl))
    dp.message(F.video_note)(_media_handler(handle_video_note_impl))

_register_media()
