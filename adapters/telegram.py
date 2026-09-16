"""Telegram-адаптер: send_telegram_text, send_safe, send_to_master, send_as_conversation.

Перенесено из main.py (commit 5, stage 6).
Зависимости от main.py (bot, MASTER_ID) — ленивый импорт внутри функций.
"""

from __future__ import annotations

import asyncio
import inspect
import logging
import re

log = logging.getLogger("sakura.telegram")

_SENT_SPLIT = re.compile(r'(?<=[.!?…])\s+')


def _get_bot_and_master():
    """Лениво импортирует bot и MASTER_ID из main."""
    import main as _main
    return _main.bot, _main.MASTER_ID


async def send_to_master(text: str, **kwargs):
    from sakura_core.llm import _strip_tone
    from aiogram.types import LinkPreviewOptions
    bot, MASTER_ID = _get_bot_and_master()
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
    from sakura_core.llm import _strip_tone
    bot, MASTER_ID = _get_bot_and_master()
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
    bot, _ = _get_bot_and_master()
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
