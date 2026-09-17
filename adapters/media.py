"""TG media handlers: voice, photo, video, video_note — extracted from adapters/telegram.py.

These are self-contained @dp handlers that need bot, LLM, and send utilities.
"""

from __future__ import annotations

import base64
import logging
import os
import tempfile
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from aiogram.types import Message

log = logging.getLogger("sakura.media")


async def handle_voice_impl(message: "Message", *, bot, is_master, get_active_key,
                             get_client, mark_key_used, ask_gemini, send_as_conversation):
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
            audio_b64 = base64.b64encode(f.read()).decode()
        os.unlink(temp_wav)

        from config import MAIN_MODEL
        from sakura_core.llm import generate as _llm_generate
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


async def handle_photo_impl(message: "Message", *, bot, is_master, get_active_key,
                             get_client, mark_key_used, send_as_conversation,
                             _get_reply_context, get_system_prompt, clean_reply,
                             add_to_history):
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
            img_b64 = base64.b64encode(f.read()).decode()
        os.unlink(temp_jpg)

        caption   = message.caption or "Опиши что на фото — коротко, в своём стиле."
        reply_ctx = _get_reply_context(message)
        from config import MAIN_MODEL
        from sakura_core.llm import generate as _llm_generate
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


async def handle_video_impl(message: "Message", *, bot, is_master, get_active_key,
                             get_client, mark_key_used, send_as_conversation,
                             _get_reply_context, get_system_prompt, clean_reply,
                             add_to_history, log):
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
            video_b64 = base64.b64encode(f.read()).decode()
        os.unlink(tmp_path)

        caption   = message.caption or "Посмотри это видео и расскажи что происходит — коротко, в своём стиле."
        reply_ctx = _get_reply_context(message)

        from config import MAIN_MODEL
        from sakura_core.llm import generate as _llm_generate
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


async def handle_video_note_impl(message: "Message", *, bot, is_master, get_active_key,
                                  get_client, mark_key_used, send_as_conversation,
                                  get_system_prompt, clean_reply, add_to_history, log):
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
            video_b64 = base64.b64encode(f.read()).decode()
        os.unlink(tmp_path)

        from config import MAIN_MODEL
        from sakura_core.llm import generate as _llm_generate
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
