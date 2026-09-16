"""Переводчик (этап 5, 3/3): быстрые переводы без LLM, сложные случаи —
промпт для LLM (его спросит адаптер). Перенесено из handle_message и
handle_voice_command без изменения логики modules/translator."""

from __future__ import annotations

from modules.translator import (
    build_translate_prompt,
    is_translation_request,
    try_quick_translate,
)

from . import Reply


def try_handle(text: str, ctx: dict) -> "Reply | None":
    if not is_translation_request(text):
        return None
    quick = try_quick_translate(text)
    if quick:
        return Reply(text=quick)
    return Reply(prompt=build_translate_prompt(text))