"""Калькулятор (этап 5, 3/3): без LLM, перенесено как есть."""

from __future__ import annotations

from modules.calculator import calculate

from . import Reply


def try_handle(text: str, ctx: dict) -> "Reply | None":
    result = calculate(text)
    if result:
        return Reply(text=result)
    return None