"""Изменения между выгрузками расписания.

Окно сравнения — (сегодня, последний день новой выгрузки]: сегодняшние пары
могли пропасть с сайта просто потому, что прошли, а дни за горизонтом сайт
ещё не показывает. Перенос — пара «отменена + добавлена» с той же
дисциплиной в пределах окна.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date

from sakura_core.schedule.parse import Lesson

_WD = ["пн", "вт", "ср", "чт", "пт", "сб", "вс"]


@dataclass(frozen=True)
class Change:
    kind: str                    # added | removed | moved | room_changed | teacher_changed | time_changed
    lesson: Lesson               # новая версия (для removed — отменённая)
    old: Lesson | None = None

    def when(self) -> date:
        return self.lesson.date

    def to_dict(self) -> dict:
        from sakura_core.schedule.store import lesson_to_dict
        d = {"kind": self.kind, "lesson": lesson_to_dict(self.lesson)}
        if self.old is not None:
            d["old"] = lesson_to_dict(self.old)
        return d

    def text(self) -> str:
        x, o = self.lesson, self.old
        day = f"{x.date:%d.%m} ({_WD[x.date.weekday()]})"
        subj = short_subject(x.subject)
        if self.kind == "added":
            return f"Новая пара {day} в {x.start:%H:%M}: {subj}{room_suffix(x.room)}."
        if self.kind == "removed":
            return f"Отменили пару {day} в {x.start:%H:%M}: {subj}."
        if self.kind == "moved" and o is not None:
            return (f"Перенесли {subj}: было {o.date:%d.%m} {o.start:%H:%M}, "
                    f"стало {day} {x.start:%H:%M}{room_suffix(x.room)}.")
        if self.kind == "room_changed" and o is not None:
            return f"{day} {subj} — другая аудитория: {x.room or 'не указана'} (была {o.room or '—'})."
        if self.kind == "time_changed" and o is not None:
            return f"{day} {subj} — теперь до {x.end:%H:%M} (было до {o.end:%H:%M})."
        if self.kind == "teacher_changed":
            return f"{day} {subj} — другой преподаватель: {x.teacher}."
        return f"Изменение в расписании {day}: {subj}."


def short_subject(subject: str) -> str:
    """Для речи и уведомлений: без уточнения в скобках."""
    import re
    s = re.sub(r"\s*\([^)]*\)", "", subject).strip()
    return s or subject


def room_suffix(room: str) -> str:
    if not room:
        return ""
    return f", ауд. {room}" if room[:1].isdigit() else f", {room}"


def diff(old: list[Lesson], new: list[Lesson], today: date) -> list[Change]:
    if not new:
        return []
    horizon = max(x.date for x in new)

    def window(xs):
        return {x.uid: x for x in xs if today < x.date <= horizon}

    o, n = window(old), window(new)
    changes: list[Change] = []
    added = [n[k] for k in n.keys() - o.keys()]
    removed = [o[k] for k in o.keys() - n.keys()]

    # Перенос: одна дисциплина ушла и появилась в окне — пара по ближайшей дате.
    for r in sorted(removed, key=lambda x: (x.date, x.start)):
        cands = [a for a in added if a.subject == r.subject and a.group == r.group]
        if not cands:
            continue
        best = min(cands, key=lambda a: abs((a.date - r.date).days))
        added.remove(best)
        removed = [x for x in removed if x is not r]
        changes.append(Change("moved", best, r))
    changes += [Change("added", a) for a in added]
    changes += [Change("removed", r) for r in removed]

    for k in n.keys() & o.keys():
        a, b = o[k], n[k]
        if a.room != b.room:
            changes.append(Change("room_changed", b, a))
        if a.end != b.end:
            changes.append(Change("time_changed", b, a))
        if a.teacher != b.teacher and a.teacher and b.teacher:
            changes.append(Change("teacher_changed", b, a))
    changes.sort(key=lambda c: (c.lesson.date, c.lesson.start, c.kind))
    return changes
