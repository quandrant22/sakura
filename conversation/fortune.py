"""Печенье с предсказаниями (этап 5, 3/3): без LLM, перенесено как есть."""

from __future__ import annotations

from modules.fortune_cookie import format_fortune, get_fortune, is_fortune_request

from . import Reply


def try_handle(text: str, ctx: dict) -> "Reply | None":
    if is_fortune_request(text):
        return Reply(text=format_fortune(get_fortune()))
    return None