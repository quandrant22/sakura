"""Shared Telegram send utilities — extracted from adapters/telegram.py.

send_to_master, send_telegram_text, send_safe, send_as_conversation,
voice_to_tg, strip_payload_words, has_tg_trigger.
"""

from __future__ import annotations

import asyncio
import inspect
import logging
import re

log = logging.getLogger("sakura.send")

_SENT_SPLIT = re.compile(r'(?<=[.!?…])\s+')

_STRIP_WORDS = ("пришли", "прошли", "отправь", "скинь", "кинь", "сбрось",
                "напиши", "напишите", "передай", "сообщи", "скажи",
                "дай", "выдай", "подай", "мне", "пожалуйста", "сакура")
_STRIP_PHRASES = ("в тг", "в телеграм", "в телегу", "в телеге", "в личк",
                  "сообщением", "мне в чат")


def _strip_tone(text: str) -> str:
    from sakura_core.llm import _strip_tone as _st
    return _st(text)


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


async def send_to_master(bot, master_id, text: str, **kwargs):
    cleaned = _strip_tone(text)
    if not cleaned.strip():
        log.warning(f"[send_to_master] Пустой текст после strip_tone: {text!r}")
        return None
    kwargs = dict(kwargs)
    kwargs.setdefault("link_preview_options",
                       __import__("aiogram.types", fromlist=["LinkPreviewOptions"]).LinkPreviewOptions(is_disabled=True))
    result = bot.send_message(master_id, cleaned, **kwargs)
    if inspect.isawaitable(result):
        return await result
    return result


async def send_telegram_text(bot, master_id, chat_id: int, text: str, **kwargs):
    cleaned = _strip_tone(text)
    if not cleaned.strip():
        log.warning(f"[send_telegram_text] Пустой текст после strip_tone: {text!r}")
        return None
    if chat_id == master_id:
        return await send_to_master(bot, master_id, cleaned, **kwargs)
    result = bot.send_message(chat_id, cleaned, **kwargs)
    if inspect.isawaitable(result):
        return await result
    return result


async def send_safe(bot, master_id, chat_id: int, text: str):
    if not (text or "").strip():
        log.warning(f"[send_safe] Попытка отправить пустое сообщение в {chat_id}")
        return
    limit = 4096
    if len(text) <= limit:
        await send_telegram_text(bot, master_id, chat_id, text)
        return
    for i in range(0, len(text), limit):
        await send_telegram_text(bot, master_id, chat_id, text[i:i + limit])


async def send_as_conversation(bot, master_id, chat_id: int, text: str):
    if len(text) <= 400 or len(re.findall(r'[.!?…]', text)) < 3:
        await send_safe(bot, master_id, chat_id, text)
        return

    parts = _split_into_parts(text)
    if len(parts) <= 1:
        await send_safe(bot, master_id, chat_id, text)
        return

    for i, part in enumerate(parts):
        if not part:
            continue
        if i > 0:
            delay = min(0.8 + len(parts[i - 1]) / 400, 2.5)
            await asyncio.sleep(delay)
            await bot.send_chat_action(chat_id, "typing")
            await asyncio.sleep(0.5)
        await send_safe(bot, master_id, chat_id, part)


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
