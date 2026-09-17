"""Страхи Сакуры (этап 5, 3/3): реакции на пугающие темы, без LLM."""

from __future__ import annotations

from modules.fears import detect_fear_trigger

from . import Reply


def try_handle(text: str, ctx: dict) -> "Reply | None":
    fear = detect_fear_trigger(text)
    if fear:
        return Reply(text=fear["response"])
    return None