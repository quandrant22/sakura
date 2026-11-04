"""Разбор расписания МУИВ из двух мест сайта вуза.

- `parse_ttable` — поле `ttable` из www.muiv.ru/services/timetable/ajax.php
  (прямой запрос или букмарклет): <h2>05.11.2026 (четверг)</h2><table>…</table>.
- `parse_eios` — личная страница ЭИОС e.muiv.ru/local/student_timetable/view.php:
  <div class="ttdate">05.11.2026</div><div class="table"><div class="row">… (без
  колонки «Группа», зато с «Кафедрой»).
На выход — список Lesson, отсортированный по дате и времени.
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
    "кафедра": "department",
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
    department: str = ""   # кафедра — есть только в ЭИОС

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


def _cell_rows(table: Tag) -> list[list[str]]:
    return [[_clean(c.get_text(" ")) for c in row.find_all("div", class_="cell", recursive=False)]
            for row in table.find_all("div", class_="row", recursive=False)]


def parse_eios(html: str, group: str) -> list[Lesson]:
    """Страница «Расписание занятий» ЭИОС → занятия. Группа на странице не
    указана (она личная) — берём из настроек. Не та страница → ParseError."""
    if not html or not html.strip():
        return []
    soup = BeautifulSoup(html, "html.parser")
    root = soup.find("div", class_="studtimetable")
    if root is None:
        if "__jhash_" in html or "get_jhash" in html:
            raise ParseError("похоже на страницу проверки антибота, а не на расписание")
        if soup.find("input", attrs={"type": "password"}) is not None:
            raise ParseError("страница входа ЭИОС, а не расписание (сессия не открыта)")
        if soup.find("div", class_="main_container_studtimetable") is not None:
            return []          # раздел есть, пар нет
        raise ParseError("на странице нет расписания")

    lessons: list[Lesson] = []
    for head in root.find_all("div", class_="ttdate"):
        m = _DATE_RE.search(head.get_text())
        table = head.find_next_sibling("div", class_="table")
        if not m or table is None:
            continue
        dd, mm, yyyy = map(int, m.groups())
        try:
            day = date(yyyy, mm, dd)
        except ValueError:
            log.warning("[schedule] неверная дата в заголовке дня")
            continue
        order = None
        for cells in _cell_rows(table):
            low = [c.lower() for c in cells]
            if any(c in _HEADERS for c in low):
                order = [_HEADERS.get(c, f"_{i}") for i, c in enumerate(low)]
                continue
            if order is None or len(cells) != len(order):
                log.warning("[schedule] строка ЭИОС пропущена: %d ячеек", len(cells))
                continue
            f = dict(zip(order, cells))
            span = parse_time_range(f.get("time", ""))
            if span is None or not f.get("subject"):
                log.warning("[schedule] строка ЭИОС пропущена: нет времени или дисциплины")
                continue
            lessons.append(Lesson(
                date=day, start=span[0], end=span[1], group=f.get("group") or group,
                subject=f["subject"], room=normalize_room(f.get("room", "")),
                kind=normalize_kind(f.get("kind", "")), kind_raw=f.get("kind", ""),
                teacher=f.get("teacher", ""), department=f.get("department", ""),
            ))
    lessons.sort(key=lambda x: (x.date, x.start, x.subject))
    return lessons
