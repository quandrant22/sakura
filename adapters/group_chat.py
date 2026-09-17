"""TG group chat + private guest handlers — extracted from handle_message.

Lines 494-672 of the original handle_message.
"""

from __future__ import annotations

import asyncio
import logging
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from aiogram.types import Message
    from aiogram import Bot

log = logging.getLogger("sakura.group_chat")


async def handle_group_message(
    message: "Message",
    *,
    bot: "Bot",
    ask_gemini,
    ask_gemini_as_guest,
    send_to_master,
    send_as_conversation,
    stream_tts_to_device,
    get_current_emotion,
    GROUP_CHAT_ID: int,
    get_role,
    is_himari,
    add_guest_message,
    update_master_status,
    mark_master_interaction,
    mood_mark_interaction,
    update_master_mood,
    increase_closeness,
    extract_topics_from_text,
    track_topic,
    track_speech,
    track_topic_reaction,
    detect_joke_about_sakura,
    save_joke,
    is_voice_note_request,
    save_voice_note,
    is_capsule_request,
    parse_open_date,
    create_capsule,
    make_create_prompt,
    parse_chain,
    run_chain,
    connected_devices,
    handle_audio_command,
) -> bool:
    """Handle a group-chat message. Returns True if handled."""
    if not GROUP_CHAT_ID or message.chat.id != GROUP_CHAT_ID:
        return False

    user_id   = message.from_user.id
    user_name = message.from_user.full_name or "id=" + str(user_id)
    text      = message.text or ""
    role      = get_role(user_id)

    if message.from_user.is_bot and message.from_user.id == bot.id:
        return True

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
        return True

    if role == "master":
        update_master_status(text)
        from modules.intimacy_mode import mark as _im_mark
        _im_mark(text)

    try:
        from modules.relationship import check_silence_cooldown, decrease_closeness
        from modules.rituals import _load as _rituals_load
        _rit_state = _rituals_load()
        _last_int = _rit_state.get("last_interaction")
        _silence_delta = check_silence_cooldown(_last_int)
        if _silence_delta:
            decrease_closeness(_silence_delta, reason="молчание")
    except Exception as e:
        log.debug(f"[tg] group: {type(e).__name__}: {e}")

    mark_master_interaction()
    mood_mark_interaction()
    try:
        await asyncio.to_thread(update_master_mood, text, "text")
    except Exception as e:
        log.debug(f"[tg] group: {type(e).__name__}: {e}")

    try:
        await asyncio.to_thread(increase_closeness, 0.003)
        topics = await asyncio.to_thread(extract_topics_from_text, text)
        for topic in topics:
            await asyncio.to_thread(track_topic, topic)
    except Exception as e:
        log.debug(f"[tg] group: {type(e).__name__}: {e}")

    try:
        await asyncio.to_thread(track_speech, text)
    except Exception as e:
        log.debug(f"[tg] group: {type(e).__name__}: {e}")

    try:
        await asyncio.to_thread(track_topic_reaction, text)
    except Exception as e:
        log.debug(f"[tg] group: {type(e).__name__}: {e}")

    try:
        if detect_joke_about_sakura(text):
            await asyncio.to_thread(save_joke, text)
    except Exception as e:
        log.debug(f"[tg] group: {type(e).__name__}: {e}")

    if is_voice_note_request(text):
        confirm = await save_voice_note(text)
        await message.reply(confirm)
        return True

    try:
        if is_capsule_request(text):
            open_date = parse_open_date(text)
            if open_date:
                await asyncio.to_thread(create_capsule, text, open_date)
                await message.reply(make_create_prompt(open_date))
                return True
    except Exception as e:
        log.debug(f"[tg] group: {type(e).__name__}: {e}")

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
                return True
    except Exception as e:
        log.debug(f"[tg] group: {type(e).__name__}: {e}")

    if text.startswith("/устройств"):
        reply = await handle_audio_command(text, connected_devices)
        await message.reply(reply)
        return True

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
    return True


async def handle_guest_private(
    message: "Message",
    *,
    bot: "Bot",
    ask_gemini_as_guest,
    ask_gemini,
    send_to_master,
    send_as_conversation,
    get_role,
    format_master_notification,
    get_user_data,
) -> bool:
    """Handle a private-chat message from a non-master user. Returns True if handled."""
    user_id   = message.from_user.id
    role      = get_role(user_id)
    user_name = message.from_user.full_name or f"id={user_id}"

    if role == "master":
        return False

    text = message.text
    log.info(f"[{role}] {user_name}: {text[:300]}")
    await bot.send_chat_action(message.chat.id, "typing")
    reply = await ask_gemini_as_guest(user_id, text, user_name, role)
    await send_as_conversation(message.chat.id, reply)

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
        tag = "[химари]" if role == "himari" else "[гость]"
        full_notification = (
            f"{tag} {notification}\n\n"
            f"💭 {opinion}\n\n"
            f"_← ответь на это сообщение чтобы обсудить_"
        )
        await send_to_master(full_notification, disable_notification=True)
    except Exception as e:
        log.error(f"Master notification error: {e}")
    return True
