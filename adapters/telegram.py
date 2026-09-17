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

_SENT_SPLIT = re.compile(r'(?<=[.!?…])\s+')


# ── Send utilities ─────────────────────────────────────────────

async def send_to_master(text: str, **kwargs):
    cleaned = _strip_tone(text)
    if not cleaned.strip():
        log.warning(f"[send_to_master] Пустой текст после strip_tone: {text!r}")
        return None
    kwargs = dict(kwargs)
    kwargs.setdefault("link_preview_options", LinkPreviewOptions(is_disabled=True))
    result = bot.send_message(MASTER_ID, cleaned, **kwargs)
    if inspect.isawaitable(result):
        return await result
    return result


async def send_telegram_text(chat_id: int, text: str, **kwargs):
    cleaned = _strip_tone(text)
    if not cleaned.strip():
        log.warning(f"[send_telegram_text] Пустой текст после strip_tone: {text!r}")
        return None
    if chat_id == MASTER_ID:
        return await send_to_master(cleaned, **kwargs)
    result = bot.send_message(chat_id, cleaned, **kwargs)
    if inspect.isawaitable(result):
        return await result
    return result


async def send_safe(chat_id: int, text: str):
    if not (text or "").strip():
        log.warning(f"[send_safe] Попытка отправить пустое сообщение в {chat_id}")
        return
    limit = 4096
    if len(text) <= limit:
        await send_telegram_text(chat_id, text)
        return
    for i in range(0, len(text), limit):
        await send_telegram_text(chat_id, text[i:i + limit])


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


# ── Голос → Telegram ───────────────────────────────────────────

_STRIP_WORDS = ("пришли", "прошли", "отправь", "скинь", "кинь", "сбрось",
                "напиши", "напишите", "передай", "сообщи", "скажи",
                "дай", "выдай", "подай", "мне", "пожалуйста", "сакура")
_STRIP_PHRASES = ("в тг", "в телеграм", "в телегу", "в телеге", "в личк",
                  "сообщением", "мне в чат")


def strip_payload_words(s: str, extra=()) -> str:
    for ph in _STRIP_PHRASES:
        s = re.sub(rf"(?<!\w){re.escape(ph)}(?!\w)", " ", s)
    for w in list(extra) + list(_STRIP_WORDS):
        s = re.sub(rf"(?<!\w){re.escape(w)}(?!\w)", " ", s)
    return " ".join(s.split()).strip(" ,.")


def has_tg_trigger(text_lower: str) -> bool:
    _SEND = ("пришли", "прошли", "отправь", "скинь", "кинь", "сбрось", "напиши", "дай")
    _TG = ("в тг", "в телеграм", "в телегу", "в телеге", "в личк", "сообщением", "мне в чат")
    return any(v in text_lower for v in _SEND) and any(t in text_lower for t in _TG)


async def voice_to_tg(text: str, text_lower: str, payload: str,
                       active_window: str, ask_gemini_fn, send_safe_fn,
                       search_image_fn, download_bytes_fn,
                       search_and_fetch_fn, needs_search_fn,
                       translate_en_fn, bot, master_id) -> None:
    if not payload:
        await send_safe_fn(master_id, "Что прислать в телеграм, Мастер?")
        return

    use_ctx = any(w in payload for w in
                  ("это", "этого", "на экране", "что вижу", "тут", "здесь", "по этому"))
    query = f"{payload} {active_window}".strip() if (use_ctx and active_window) else payload

    is_img = (len(payload.split()) <= 8 and any(w in payload for w in
              ("картинк", "фото", "изображени", "рисунок", "арт", "мем", "пикч", "нарисуй")))
    try:
        if is_img:
            q = query
            for w in ("найди", "поищи", "покажи", "картинку", "картинка", "картинки",
                      "фото", "фотку", "фотографию", "изображение", "изображени",
                      "рисунок", "арт", "мем", "пикчу", "пикч"):
                q = re.sub(rf"(?<!\w){re.escape(w)}(?!\w)", " ", q)
            q = " ".join(q.split()).strip()
            q_en = await translate_en_fn(q)
            urls = await search_image_fn(q_en, count=1)
            img = await download_bytes_fn(urls[0]) if urls else None
            if img:
                from aiogram.types import BufferedInputFile
                await bot.send_photo(master_id,
                    photo=BufferedInputFile(img, "image.jpg"), caption=q)
            elif urls:
                await bot.send_message(master_id, urls[0])
        elif needs_search_fn(payload):
            res = await search_and_fetch_fn(query)
            await send_safe_fn(master_id, res or "По запросу ничего не нашла.")
        elif any(text_lower.lstrip().startswith(w) for w in
                 ("список", "текст", "заметку", "заметка", "запиши", "дословно")) \
                 or any(w in text_lower for w in ("следующий список", "такой текст", "дословно")):
            await send_safe_fn(master_id, text)
        elif any(w in text_lower for w in
                 ("список", "по пунктам", "заметку", "заметка", "запиши", "перечень")):
            formatted = await ask_gemini_fn(
                "Оформи это как аккуратный нумерованный список (1. 2. 3.), "
                "сохрани смысл дословно, ничего не добавляй, не комментируй, "
                "не отвечай — только список:\n" + payload,
                save_history=False)
            await send_safe_fn(master_id, formatted)
        else:
            answer = await ask_gemini_fn(payload, save_history=False)
            await send_safe_fn(master_id, answer)
    except Exception as e:
        log.error(f"voice->tg: {e}")
        await send_safe_fn(master_id, "Не получилось, Мастер.")


# ── Command handlers ───────────────────────────────────────────

@dp.message(Command("помощь"))
async def cmd_help(message: Message):
    if not is_master(message.from_user.id):
        return
    from modules import device_commands
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
    await message.answer(ctx if ctx else "Задач пока нет.")


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
    if not is_master(message.from_user.id):
        return
    await message.answer(get_guest_summaries())


@dp.message(Command("vip"))
async def cmd_vip(message: Message):
    if not is_master(message.from_user.id):
        return
    parts = (message.text or "").split(maxsplit=1)
    if len(parts) < 2:
        await message.answer("Использование: /vip @username или /vip id")
        return
    arg = parts[1].strip()
    uid = None
    if arg.isdigit():
        uid = int(arg)
    else:
        from modules.users import _find_user_by_username
        uid = _find_user_by_username(arg.lstrip("@"))
    if uid:
        add_vip(uid)
        await message.answer(f"Пользователь {uid} добавлен в VIP.")
    else:
        await message.answer("Не нашла такого пользователя.")


@dp.message(Command("trusted"))
async def cmd_trusted(message: Message):
    if not is_master(message.from_user.id):
        return
    parts = (message.text or "").split(maxsplit=1)
    if len(parts) < 2:
        await message.answer("Использование: /trusted @username или /trusted id")
        return
    arg = parts[1].strip()
    uid = None
    if arg.isdigit():
        uid = int(arg)
    else:
        from modules.users import _find_user_by_username
        uid = _find_user_by_username(arg.lstrip("@"))
    if uid:
        add_trusted(uid)
        await message.answer(f"Пользователь {uid} добавлен в доверенные.")
    else:
        await message.answer("Не нашла такого пользователя.")


@dp.message(Command("users"))
async def cmd_users(message: Message):
    if not is_master(message.from_user.id):
        return
    await message.answer(list_users())


@dp.message(Command("unvip"))
async def cmd_unvip(message: Message):
    if not is_master(message.from_user.id):
        return
    parts = (message.text or "").split(maxsplit=1)
    if len(parts) < 2:
        await message.answer("Использование: /unvip id")
        return
    arg = parts[1].strip()
    if arg.isdigit():
        remove_user(int(arg))
        await message.answer(f"Пользователь {arg} удалён.")
    else:
        await message.answer("Укажи numeric ID.")


@dp.message(Command("block"))
async def cmd_block(message: Message):
    if not is_master(message.from_user.id):
        return
    parts = (message.text or "").split(maxsplit=1)
    if len(parts) < 2:
        await message.answer("Использование: /block id")
        return
    arg = parts[1].strip()
    if arg.isdigit():
        block_user(int(arg))
        await message.answer(f"Пользователь {arg} заблокирован.")
    else:
        await message.answer("Укажи numeric ID.")


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
    from adapters.group_chat import handle_group_message, handle_guest_private

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

    if message.reply_to_message:
        replied_text = (message.reply_to_message.text or "").strip()
        is_guest_notification  = replied_text.startswith("[гость]")
        is_himari_notification = replied_text.startswith("[химари]")
        if is_guest_notification or is_himari_notification:
            who = "Химари" if is_himari_notification else "гостя"

            if is_guest_notification and not is_himari_notification:
                import re as _re
                id_match = _re.search(r'id=(\d+)', replied_text)
                if id_match:
                    guest_uid = int(id_match.group(1))
                    detected  = detect_relation_from_text(text)
                    if detected is not None:
                        set_relation(guest_uid, detected, note=text[:150])
                    elif text.strip():
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

    asked   = parse_device_from_text(text)
    dev_id  = asked or next(iter(get_online_devices()), None) or "laptop"
    chosen  = {"dev": dev_id}
    def _resolve(q):
        d, t = resolve_app(q, dev_id)
        if t and not asked:
            chosen["dev"] = d
        return t
    actions = device_parse(text, _resolve)
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
        key = get_active_key()
        client = get_client(key)
        with open(temp_wav, "rb") as f:
            audio_b64 = __import__("base64").b64encode(f.read()).decode()
        os.unlink(temp_wav)

        from google.genai import types
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
        key = get_active_key()
        client = get_client(key)
        with open(temp_jpg, "rb") as f:
            img_b64 = __import__("base64").b64encode(f.read()).decode()
        os.unlink(temp_jpg)

        caption   = message.caption or "Опиши что на фото — коротко, в своём стиле."
        reply_ctx = _get_reply_context(message)
        from google.genai import types
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


@dp.message(F.video)
async def handle_video(message: Message):
    if not is_master(message.from_user.id):
        return
    await bot.send_chat_action(message.chat.id, "upload_video")

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
        key = get_active_key()
        client = get_client(key)

        with open(tmp_path, "rb") as f:
            video_b64 = __import__("base64").b64encode(f.read()).decode()
        os.unlink(tmp_path)

        caption   = message.caption or "Посмотри это видео и расскажи что происходит — коротко, в своём стиле."
        reply_ctx = _get_reply_context(message)

        from google.genai import types
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
            log.debug(f"[tg] handle_video: {type(e).__name__}: {e}")
        await message.reply(f"Не смогла обработать видео: {e}")


@dp.message(F.video_note)
async def handle_video_note(message: Message):
    if not is_master(message.from_user.id):
        return
    await bot.send_chat_action(message.chat.id, "typing")

    file = await bot.get_file(message.video_note.file_id)
    with tempfile.NamedTemporaryFile(suffix=".mp4", delete=False) as f:
        tmp_path = f.name
    await bot.download_file(file.file_path, tmp_path)

    try:
        key = get_active_key()
        client = get_client(key)

        with open(tmp_path, "rb") as f:
            video_b64 = __import__("base64").b64encode(f.read()).decode()
        os.unlink(tmp_path)

        from google.genai import types
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
            log.debug(f"[tg] handle_video_note: {type(e).__name__}: {e}")
        await message.reply("Не смогла посмотреть кружочек.")
