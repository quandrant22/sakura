"""Разбор расписания МУИВ: поле `ttable` из ответа /services/timetable/ajax.php.

Источник не важен (прямой запрос или букмарклет): на вход — HTML-фрагмент
вида  <h2>05.11.2026 (четверг)</h2><div class="tableScroll"><table>…</table></div>
и так по дням. На выход — список Lesson, отсортированный по дате и времени.
"""
from __future__ import annotations

import hashlib
import logging
import re
from dataclasses import dataclass
from datetime import date, time

from bs4 import BeautifulSoup, Tag

log = logging.getLogger(__name__)

_DATE_RE = re.compile(r"(\d{2})\.(\d{2})\.(\d{4})")
_TIME_RE = re.compile(r"(\d{1,2})[:.](\d{2})\s*[-–—]\s*(\d{1,2})[:.](\d{2})")
_ROOM_PREFIX_RE = re.compile(r"^\s*ауд(?:итория)?\.?\s*", re.IGNORECASE)

# Колонки сайта → поля. Порядок берём из шапки, а не по номеру ячейки:
# если вуз переставит колонки, разбор не сломается.
_HEADERS = {
    "время занятия": "time",
    "группа": "group",
    "дисциплина": "subject",
    "аудитория": "room",
    "вид занятия": "kind",
    "преподаватель": "teacher",
}
_DEFAULT_ORDER = ["time", "group", "subject", "room", "kind", "teacher"]

# Вид занятия: первое совпадение по подстроке (нижний регистр).
_KINDS = [
    ("лекц", "lecture"),
    ("семинар", "seminar"),
    ("практ", "seminar"),
    ("лаб", "lab"),
    ("экзам", "exam"),
    ("зач", "credit"),
    ("консульт", "consult"),
]


@dataclass(frozen=True)
class Lesson:
    date: date
    start: time
    end: time
    group: str
    subject: str
    room: str        # «531»; «» если не указана; «онлайн»/«СДО» как есть
    kind: str        # lecture | seminar | lab | exam | credit | consult | other
    kind_raw: str    # «Семинары ИПЗ»
    teacher: str

    @property
    def uid(self) -> str:
        """Ключ для сравнения выгрузок: аудитория и преподаватель в него
        не входят — их смена считается изменением, а не новым занятием."""
        key = f"{self.date.isoformat()}|{self.start:%H:%M}|{self.group}|{self.subject}"
        return hashlib.sha1(key.encode()).hexdigest()[:16]


class ParseError(ValueError):
    """Фрагмент не похож на расписание (например, пришла заглушка антибота)."""


def _clean(s: str) -> str:
    return re.sub(r"\s+", " ", s.replace("\xa0", " ")).strip()


def normalize_room(raw: str) -> str:
    return _clean(_ROOM_PREFIX_RE.sub("", _clean(raw)))


def normalize_kind(raw: str) -> str:
    low = raw.lower()
    for needle, kind in _KINDS:
        if needle in low:
            return kind
    return "other"


def parse_time_range(raw: str) -> tuple[time, time] | None:
    m = _TIME_RE.search(raw)
    if not m:
        return None
    h1, m1, h2, m2 = map(int, m.groups())
    try:
        return time(h1, m1), time(h2, m2)
    except ValueError:
        return None


def _header_order(row: Tag) -> list[str] | None:
    cells = [_clean(td.get_text()).lower() for td in row.find_all(["td", "th"])]
    if not cells or not any(c in _HEADERS for c in cells):
        return None
    return [_HEADERS.get(c, f"_{i}") for i, c in enumerate(cells)]


def _parse_table(table: Tag, day: date) -> list[Lesson]:
    order = _DEFAULT_ORDER
    lessons: list[Lesson] = []
    for row in table.find_all("tr"):
        header = _header_order(row)
        if header:
            order = header
            continue
        cells = [_clean(td.get_text(" ")) for td in row.find_all("td")]
        if len(cells) != len(order):
            log.warning("[schedule] строка пропущена: %d ячеек вместо %d", len(cells), len(order))
            continue
        f = dict(zip(order, cells))
        span = parse_time_range(f.get("time", ""))
        if span is None or not f.get("subject"):
            log.warning("[schedule] строка пропущена: нет времени или дисциплины")
            continue
        lessons.append(Lesson(
            date=day, start=span[0], end=span[1],
            group=f.get("group", ""), subject=f["subject"],
            room=normalize_room(f.get("room", "")),
            kind=normalize_kind(f.get("kind", "")), kind_raw=f.get("kind", ""),
            teacher=f.get("teacher", ""),
        ))
    return lessons


def parse_ttable(html: str) -> list[Lesson]:
    """HTML `ttable` → занятия. Пустое расписание → []. Не расписание → ParseError."""
    if not html or not html.strip():
        return []
    soup = BeautifulSoup(html, "html.parser")
    if soup.find("script") or "__jhash_" in html:
        raise ParseError("похоже на страницу проверки антибота, а не на расписание")

    lessons: list[Lesson] = []
    for h2 in soup.find_all("h2"):
        m = _DATE_RE.search(h2.get_text())
        if not m:
            continue
        dd, mm, yyyy = map(int, m.groups())
        try:
            day = date(yyyy, mm, dd)
        except ValueError:
            log.warning("[schedule] неверная дата в заголовке дня")
            continue
        # Таблица дня — первая <table> после заголовка и до следующего <h2>.
        for sib in h2.find_all_next(["h2", "table"]):
            if sib.name == "h2":
                break
            lessons.extend(_parse_table(sib, day))
            break
    lessons.sort(key=lambda x: (x.date, x.start, x.subject))
    return lessons
