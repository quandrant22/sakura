from datetime import date, time
from pathlib import Path

import pytest

from sakura_core.schedule.parse import (
    ParseError,
    normalize_kind,
    normalize_room,
    parse_time_range,
    parse_ttable,
)

FIX = Path(__file__).parent / "fixtures" / "muiv_ttable_2026-11-04.html"

HEAD = ('<tr class="th-1"><td><b>Время занятия</b></td><td><b>Группа</b></td>'
        '<td><b>Дисциплина</b></td><td><b>Аудитория</b></td>'
        '<td><b>Вид занятия</b></td><td><b>Преподаватель</b></td></tr>')


def day(d: str, rows: str, head: str = HEAD) -> str:
    return f'<h2>{d} (день)</h2><div class="tableScroll"><TABLE><TBODY>{head}{rows}</TBODY></TABLE></div>'


def test_fixture_five_lessons():
    lessons = parse_ttable(FIX.read_text(encoding="utf-8"))
    assert [x.date for x in lessons] == [
        date(2026, 11, 5), date(2026, 11, 6), date(2026, 11, 10),
        date(2026, 11, 16), date(2026, 11, 17)]
    first = lessons[0]
    assert (first.start, first.end) == (time(18, 40), time(21, 50))
    assert first.group == "ИД 86.1/М1-25"
    assert first.room == "531"
    assert first.kind == "seminar" and first.kind_raw == "Семинары ИПЗ"
    assert lessons[1].room == "319"
    assert lessons[2].kind == "lecture"


def test_uid_ignores_room_and_teacher():
    a = parse_ttable(day("10.11.2026", "<tr><td>18:40-21:50</td><td>G</td><td>Крипто</td><td>ауд.505</td><td>Лекции</td><td>А</td></tr>"))[0]
    b = parse_ttable(day("10.11.2026", "<tr><td>18:40-21:50</td><td>G</td><td>Крипто</td><td>ауд.507</td><td>Лекции</td><td>Б</td></tr>"))[0]
    assert a.uid == b.uid and a.room != b.room


def test_columns_reordered_by_header():
    head = ("<tr><td><b>Дисциплина</b></td><td><b>Время занятия</b></td><td><b>Группа</b></td>"
            "<td><b>Преподаватель</b></td><td><b>Аудитория</b></td><td><b>Вид занятия</b></td></tr>")
    row = "<tr><td>Крипто</td><td>9:00-10:30</td><td>G</td><td>А</td><td>101</td><td>Лабораторные</td></tr>"
    x = parse_ttable(day("01.12.2026", row, head))[0]
    assert (x.subject, x.start, x.room, x.kind) == ("Крипто", time(9, 0), "101", "lab")


def test_bad_row_skipped_good_kept():
    rows = ("<tr><td>18:40-21:50</td><td>G</td></tr>"
            "<tr><td>когда-нибудь</td><td>G</td><td>X</td><td>1</td><td>Лекции</td><td>А</td></tr>"
            "<tr><td>18:40-21:50</td><td>G</td><td>Y</td><td>2</td><td>Лекции</td><td>А</td></tr>")
    assert [x.subject for x in parse_ttable(day("01.12.2026", rows))] == ["Y"]


def test_several_lessons_sorted():
    rows = ("<tr><td>12:00-13:30</td><td>G</td><td>B</td><td>1</td><td>Лекции</td><td>А</td></tr>"
            "<tr><td>09:00-10:30</td><td>G</td><td>A</td><td>1</td><td>Лекции</td><td>А</td></tr>")
    assert [x.subject for x in parse_ttable(day("01.12.2026", rows))] == ["A", "B"]


@pytest.mark.parametrize("html", ["", "   ", "<p>Занятий нет</p>"])
def test_empty(html):
    assert parse_ttable(html) == []


def test_antibot_stub_raises():
    stub = ('<html><head><style>.gorizontal-vertikal{}</style></head><body>'
            '<script>function get_jhash(b){}</script></body></html>')
    with pytest.raises(ParseError):
        parse_ttable(stub)


@pytest.mark.parametrize("raw,exp", [("ауд.531", "531"), ("ауд. 531", "531"), ("Аудитория 12", "12"),
                                     ("319", "319"), ("", ""), ("СДО", "СДО")])
def test_room(raw, exp):
    assert normalize_room(raw) == exp


@pytest.mark.parametrize("raw,exp", [("Лекции", "lecture"), ("Семинары ИПЗ", "seminar"),
                                     ("Экзамен", "exam"), ("Зачет", "credit"), ("Что-то", "other")])
def test_kind(raw, exp):
    assert normalize_kind(raw) == exp


@pytest.mark.parametrize("raw,exp", [("18:40-21:50", (time(18, 40), time(21, 50))),
                                     ("9.00 – 10.30", (time(9, 0), time(10, 30))),
                                     ("25:00-26:00", None), ("—", None)])
def test_time(raw, exp):
    assert parse_time_range(raw) == exp
