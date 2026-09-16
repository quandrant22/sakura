"""Протокол «чистый лист» (этап 5, 3/3): механизм стирания контекста
живёт у поверхности (_clean_slate), модуль только распознаёт фразу."""

from __future__ import annotations

from . import Reply


def try_handle(text: str, ctx: dict) -> "Reply | None":
    if "протокол чистый лист" in text.lower():
        return Reply(
            text="Протокол выполнен. Я тебя не помню.",
            run_clean_slate=True,
        )
    return None