"""Домен «календарь» (этап 6, коммит 7B-5): calendar.list — executor=vps.

Чтение событий из Google Calendar. Источник серверный: token.json и
google-api лежат на VPS, читает их modules/calendar_module.py, поэтому
executor=vps, а не agent — у агента на Windows этих данных нет.

Развязка этапа 7: до неё calendar.list был недостижим. Реестр про него знал
(id попадал в каталог LLM), а исполнять было нечем: агент такого действия
не знает, серверный путь жил в modules/ws_handlers.py по подстроке
«календарь». Агента учить не пришлось — домен переехал на vps.

Запись событий (calendar.add, calendar.delete) не реализована —
calendar_module.py умеет только чтение.
"""

import asyncio
import logging

from sakura_core.executor import ExecutionContext, Handler, register_table

log = logging.getLogger("sakura.calendar")

HOURS_AHEAD = 24


def _render(events: list) -> str:
    """События → текст ответа (тот же вид, что в get_calendar_context)."""
    lines = [f"Ближайшие события ({HOURS_AHEAD} ч):"]
    for e in events:
        line = f"— {e.get('date', '')} {e.get('time', '')}: {e.get('summary', '')}"
        if e.get("description"):
            line += f" ({e['description']})"
        lines.append(line.strip())
    return "\n".join(lines)


async def _list(_ctx: ExecutionContext) -> tuple[str, bool]:
    """calendar.list → ближайшие события. Сеть — в поток, не в event loop."""
    from modules.calendar_module import get_calendar_service, get_upcoming_events

    events = await asyncio.to_thread(get_upcoming_events, HOURS_AHEAD)
    if events:
        return (_render(events), True)

    # get_upcoming_events() глотает ошибку источника и отдаёт [] — различаем
    # «событий нет» и «календарь недоступен» явной проверкой сервиса, иначе
    # недоступность выглядела бы как пустой календарь (правило честности v2).
    try:
        await asyncio.to_thread(get_calendar_service)
    except Exception as e:
        log.error(f"[calendar] сервис недоступен: {type(e).__name__}: {e}")
        return ("Google Calendar недоступен — события прочитать не смогла.", False)
    return (f"В ближайшие {HOURS_AHEAD} часов событий нет.", True)


CALENDAR_HANDLERS: dict[str, Handler] = {
    "calendar.list": _list,
}

register_table(CALENDAR_HANDLERS)
