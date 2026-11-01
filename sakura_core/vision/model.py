"""model — один вызов модели зрения по кадру.

Только VISION_MODEL_CHAIN и без инструментов: текст с экрана не может
ничего запустить. Байты кадра после вызова не удерживаются.
"""

from __future__ import annotations

import logging
import time

import config

log = logging.getLogger("sakura.vision")


async def see(image: bytes, mime: str, prompt: str, *, max_tokens: int = 300) -> str:
    from google.genai import types as T

    from sakura_core.llm import clean_reply, generate
    t0 = time.monotonic()
    try:
        text = await generate(
            [T.Part(inline_data=T.Blob(mime_type=mime, data=image)),
             T.Part(text=prompt)],
            chain=config.VISION_MODEL_CHAIN, max_tokens=max_tokens,
            safety=False, thinking=False)
    finally:
        image = b""
    text = clean_reply(text or "").strip()
    log.info(f"[vision] модель: {len(text)} симв за {time.monotonic() - t0:.1f}с")
    return text
