"""Заметка «что только что исполнено» для разговорного ответа.

Гибридная фраза («кстати поставь чайник, а я пока расскажу, как прошёл
день») исполняется в два приёма: мост выполняет команду, а на остаток
отвечает разговорная модель. Чтобы она знала о сделанном и не обещала
это заново, мост кладёт сюда заметку; sakura_core/prompt.py добавляет её
в системный промпт хода.

Заметка живёт недолго (TTL): она относится к текущему ходу, а не к диалогу.
"""

from __future__ import annotations

import time
from typing import Optional

TTL_S = 20.0

_note: Optional[str] = None
_until: float = 0.0


def set_note(text: Optional[str], ttl: float = TTL_S) -> None:
    global _note, _until
    _note = (text or "").strip() or None
    _until = time.monotonic() + ttl


def clear() -> None:
    global _note
    _note = None


def current() -> Optional[str]:
    """Действующая заметка или None (просроченная сбрасывается)."""
    global _note
    if _note is not None and time.monotonic() >= _until:
        _note = None
    return _note


def prompt_block() -> str:
    """Блок для системного промпта; пустая строка — заметки нет."""
    note = current()
    if not note:
        return ""
    return (
        "ТОЛЬКО ЧТО ВЫПОЛНЕНО ПО ЭТОЙ ФРАЗЕ МАСТЕРА:\n"
        f"{note}\n"
        "Эти команды уже исполнены системой — не выполняй и не обещай их заново. "
        "Одной короткой фразой подтверди сделанное и ответь на остальную часть реплики."
    )
