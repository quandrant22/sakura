"""Общая шина capability-модулей (этап 5): текстовая выдача VPS-действий.

Агентные действия исполняются через таблицы AgentCommand в capabilities/*.
VPS-действия (инфо, задачи, напоминания, погода, сервер, капсулы, память,
статистика, брифинг) исполняются на сервере: модулю достаточно переиспользовать
готовую связку modules/voice_info.handle(action, arg, text) → (текст, ok).

По контракту v2 handle() возвращает (текст, ok):
  ok=True  — данные получены (даже если пусты: «новых ачивок нет»);
  ok=False — источник недоступен: говорим это прямо, не маскируем под «нет данных».
Это правило честности переносится в v3 без изменений.

vps_answer(action_id, arg, text) — единый вход всех VPS-доменов v3:
  канонический id «domain.verb» → легаси-имя voice_info «domain:verb» →
  handle() → (текст, ok). Исключение — только если модуля voice_info нет;
  любая ошибка источника — штатный (текст, False), а не падение.
"""

from __future__ import annotations

import logging

log = logging.getLogger("sakura.vps_answer")


def to_legacy(action_id: str) -> str:
    """Канонический 'domain.verb' → легаси-имя 'domain:verb' для voice_info."""
    domain, _, verb = action_id.partition(".")
    return f"{domain}:{verb}"


async def vps_answer(action_id: str, arg: str = "", text: str = "") -> tuple[str, bool]:
    """Исполнить VPS-действие, вернуть (текст, ok). Падение исключено."""
    from modules.voice_info import handle as _info_handle

    legacy = to_legacy(action_id)
    try:
        reply, ok = await _info_handle(legacy, arg or "", text or "")
        return reply, bool(ok)
    except Exception as e:
        log.error(f"[vps_answer] {action_id}: {type(e).__name__}: {e}")
        return "Не смогла получить данные у источника — он недоступен.", False
