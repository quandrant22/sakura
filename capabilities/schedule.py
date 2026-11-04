"""Домен «расписание вуза» (feat/schedule): schedule.* — executor=vps.

Данные — sakura_core/schedule (хранилище на VPS). Голос — коротко, без
скобок в названиях; Telegram — списком с преподавателем и видом занятия.
"""
from __future__ import annotations

import logging
from datetime import datetime, timedelta

import config
from sakura_core.executor import ExecutionContext, Handler, register_table
from sakura_core.schedule import query

log = logging.getLogger("sakura.schedule")

PUSH_HINT = "Открой страницу расписания вуза и нажми закладку «Сакура: расписание» — обновлю."


def _now() -> datetime:
    # Наивное локальное время — как во всей Сакуре (R10).
    return datetime.now()  # noqa: DTZ005


def _voice(ctx: ExecutionContext) -> bool:
    return (ctx.extra or {}).get("source") != "telegram"


def _no_data() -> str:
    return "Расписания у меня пока нет. " + PUSH_HINT


def _stale_note(now: datetime) -> str:
    at = query.get_store().fetched_at()
    if at is not None and query.is_stale(now):
        return f" Данные от {at:%d.%m} — могли устареть."
    return ""


async def _day(ctx: ExecutionContext, offset: int) -> tuple[str, bool]:
    now = _now()
    if not query.has_data():
        return (_no_data(), True)
    text = query.describe_day(now.date() + timedelta(days=offset), now, voice=_voice(ctx))
    return (text + _stale_note(now), True)


async def _today(ctx: ExecutionContext) -> tuple[str, bool]:
    return await _day(ctx, 0)


async def _tomorrow(ctx: ExecutionContext) -> tuple[str, bool]:
    return await _day(ctx, 1)


async def _week(ctx: ExecutionContext) -> tuple[str, bool]:
    now = _now()
    if not query.has_data():
        return (_no_data(), True)
    return (query.describe_week(now, voice=_voice(ctx)) + _stale_note(now), True)


async def _next(ctx: ExecutionContext) -> tuple[str, bool]:
    now = _now()
    if not query.has_data():
        return (_no_data(), True)
    return (query.describe_next(now, voice=_voice(ctx)) + _stale_note(now), True)


async def _refresh(_ctx: ExecutionContext) -> tuple[str, bool]:
    if "direct" not in config.SCHEDULE_SOURCES:
        return (PUSH_HINT, True)
    from sakura_core.schedule.sync import sync_direct
    res = await sync_direct(_now())
    if res.ok:
        return (f"Обновила расписание: {res.summary()}.", True)
    if res.error == "blocked":
        return ("Сайт вуза не пускает сервер. " + PUSH_HINT, False)
    return (f"Не получилось обновить: {res.summary()}.", False)


SCHEDULE_HANDLERS: dict[str, Handler] = {
    "schedule.today": _today,
    "schedule.tomorrow": _tomorrow,
    "schedule.week": _week,
    "schedule.next": _next,
    "schedule.refresh": _refresh,
}

register_table(SCHEDULE_HANDLERS)
