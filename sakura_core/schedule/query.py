"""Запросы к расписанию для команд, контекста и сводки. Время — параметром."""
from __future__ import annotations

from datetime import date, datetime, timedelta

import config
from sakura_core.schedule.diff import room_suffix, short_subject
from sakura_core.schedule.parse import Lesson
from sakura_core.schedule.store import ScheduleStore, get_store

_WD_FULL = ["понедельник", "вторник", "среда", "четверг", "пятница", "суббота", "воскресенье"]


def _store(store: ScheduleStore | None) -> ScheduleStore:
    return store or get_store()


def has_data(store: ScheduleStore | None = None) -> bool:
    return _store(store).fetched_at() is not None


def is_stale(now: datetime, store: ScheduleStore | None = None) -> bool:
    at = _store(store).fetched_at()
    return at is None or now - at > timedelta(days=config.SCHEDULE_STALE_DAYS)


def covers(day: date, store: ScheduleStore | None = None) -> bool:
    """Знаем ли мы этот день: выгрузка свежая и день не за её горизонтом.
    Пустой список на покрытый день — «пар нет», на непокрытый — «не знаю»."""
    s = _store(store)
    at = s.fetched_at()
    if at is None:
        return False
    horizon = s._load().get("horizon_to")
    try:
        h = date.fromisoformat(horizon) if horizon else at.date()
    except ValueError:
        h = at.date()
    # сайт показывает ≈2 недели вперёд; дни без пар он не выводит, поэтому
    # «покрыто» — от даты выгрузки до горизонта (и прошлое, что сохранено)
    return day <= max(h, at.date())


def on(day: date, store: ScheduleStore | None = None) -> list[Lesson]:
    return [x for x in _store(store).lessons() if x.date == day]


def between(start: date, end: date, store: ScheduleStore | None = None) -> list[Lesson]:
    return [x for x in _store(store).lessons() if start <= x.date <= end]


def current_lesson(now: datetime, store: ScheduleStore | None = None) -> Lesson | None:
    t = now.time()
    for x in on(now.date(), store):
        if x.start <= t < x.end:
            return x
    return None


def next_lesson(now: datetime, store: ScheduleStore | None = None) -> Lesson | None:
    for x in _store(store).lessons():
        if (x.date, x.start) > (now.date(), now.time()):
            return x
    return None


# ── форматирование ────────────────────────────────────────────────────

def line(x: Lesson, *, voice: bool = False) -> str:
    subj = short_subject(x.subject) if voice else x.subject
    if voice:
        return f"в {x.start:%H:%M} {subj}{room_suffix(x.room)}"
    kind = f" · {x.kind_raw}" if x.kind_raw else ""
    teacher = f" · {x.teacher}" if x.teacher else ""
    return f"{x.start:%H:%M}–{x.end:%H:%M} {subj}{room_suffix(x.room)}{kind}{teacher}"


def day_label(day: date, today: date) -> str:
    if day == today:
        return "Сегодня"
    if day == today + timedelta(days=1):
        return "Завтра"
    return f"{_WD_FULL[day.weekday()].capitalize()}, {day:%d.%m}"


def _plural_pairs(n: int) -> str:
    if n % 10 == 1 and n % 100 != 11:
        return f"{n} пара"
    if 2 <= n % 10 <= 4 and not 12 <= n % 100 <= 14:
        return f"{n} пары"
    return f"{n} пар"


def describe_day(day: date, now: datetime, *, voice: bool,
                 store: ScheduleStore | None = None) -> str:
    lessons = on(day, store)
    label = day_label(day, now.date())
    if not lessons:
        if not covers(day, store):
            return f"{label}: расписания на этот день у меня нет."
        return f"{label} пар нет."
    if voice:
        body = "; ".join(line(x, voice=True) for x in lessons)
        return f"{label} {_plural_pairs(len(lessons))}: {body}."
    return f"{label}:\n" + "\n".join(f"— {line(x)}" for x in lessons)


def describe_week(now: datetime, *, voice: bool, store: ScheduleStore | None = None) -> str:
    today = now.date()
    lessons = between(today, today + timedelta(days=6), store)
    if not lessons:
        if not has_data(store):
            return "Расписания у меня пока нет."
        return "На ближайшую неделю пар нет."
    days = sorted({x.date for x in lessons})
    if voice:
        parts = [f"{day_label(d, today).lower()} — "
                 + ", ".join(f"{x.start:%H:%M} {short_subject(x.subject)}" for x in on(d, store))
                 for d in days]
        return "На неделе: " + "; ".join(parts) + "."
    return "\n\n".join(describe_day(d, now, voice=False, store=store) for d in days)


def describe_next(now: datetime, *, voice: bool, store: ScheduleStore | None = None) -> str:
    cur = current_lesson(now, store)
    if cur is not None:
        return (f"Сейчас идёт {short_subject(cur.subject)}{room_suffix(cur.room)}, "
                f"до {cur.end:%H:%M}.")
    x = next_lesson(now, store)
    if x is None:
        return "Ближайших пар в расписании нет." if has_data(store) else "Расписания у меня пока нет."
    label = day_label(x.date, now.date())
    return f"{label} {line(x, voice=True)}." if voice else f"{label}: {line(x)}"


def today_prompt_line(now: datetime, store: ScheduleStore | None = None) -> str:
    """Строка для промпта: только в дни с парами, ≤ 200 символов."""
    lessons = on(now.date(), store)
    if not lessons or is_stale(now, store):
        return ""
    s = "; ".join(f"{x.start:%H:%M}–{x.end:%H:%M} {short_subject(x.subject)}{room_suffix(x.room)}"
                  for x in lessons)
    return ("ПАРЫ СЕГОДНЯ: " + s)[:200]
