"""Общие помощники тестов расписания: сборка ttable и хранилище во временном файле."""
from __future__ import annotations

from datetime import date
from pathlib import Path

FIXTURE = Path(__file__).parent / "fixtures" / "muiv_ttable_2026-11-04.html"
GROUP = "ИД 86.1/М1-25"

HEAD = ('<tr class="th-1"><td><b>Время занятия</b></td><td><b>Группа</b></td>'
        '<td><b>Дисциплина</b></td><td><b>Аудитория</b></td>'
        '<td><b>Вид занятия</b></td><td><b>Преподаватель</b></td></tr>')


def ttable(*rows: tuple) -> str:
    """rows: (date, "18:40-21:50", subject, room, kind, teacher[, group])."""
    by_day: dict[date, list[str]] = {}
    for r in rows:
        d, t, subj, room, kind, teacher, *g = r
        group = g[0] if g else GROUP
        by_day.setdefault(d, []).append(
            f"<tr><td>{t}</td><td>{group}</td><td>{subj}</td><td>{room}</td>"
            f"<td>{kind}</td><td>{teacher}</td></tr>")
    out = []
    for d in sorted(by_day):
        out.append(f'<h2>{d:%d.%m.%Y} (день)</h2><div class="tableScroll"><TABLE><TBODY>'
                   f'{HEAD}{"".join(by_day[d])}</TBODY></TABLE></div>')
    return "".join(out)


class FakeNotifier:
    def __init__(self):
        self.changes = []

    def enqueue_changes(self, changes, now):
        self.changes.extend(changes)
