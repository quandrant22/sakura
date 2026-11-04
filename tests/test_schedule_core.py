"""Расписание: хранилище, слияние, изменения, ingest, прямой опрос, запросы."""
# Наивное локальное время — как в коде Сакуры (R10).
# ruff: noqa: DTZ001

import asyncio
import json
from datetime import date, datetime, time

import pytest

import config
from sakura_core.schedule import fetch, query
from sakura_core.schedule.diff import diff
from sakura_core.schedule.parse import parse_ttable
from sakura_core.schedule.store import ScheduleStore, merge
from sakura_core.schedule.sync import direct_due, ingest, sync_direct
from tests.schedule_support import FIXTURE, FakeNotifier, ttable

D = date(2026, 11, 10)          # вторник
NOW = datetime(2026, 11, 4, 14, 0)


def L(d, subj="Крипто", room="ауд.505", t="18:40-21:50", kind="Лекции", teacher="Сидоров П. П.", **kw):
    return (d, t, subj, room, kind, teacher, *([kw["group"]] if "group" in kw else []))


@pytest.fixture
def store(tmp_path):
    return ScheduleStore(str(tmp_path / "s.json"))


# ── слияние ───────────────────────────────────────────────────────────

def test_merge_keeps_past_and_beyond_horizon_replaces_inside():
    today = date(2026, 11, 10)
    old = parse_ttable(ttable(L(date(2026, 11, 3)), L(date(2026, 9, 1)),          # прошлое: свежее и старое
                              L(date(2026, 11, 12), "Старая"), L(date(2026, 12, 20), "Далёкая")))
    new = parse_ttable(ttable(L(date(2026, 11, 13), "Новая"), L(date(2026, 11, 20), "Ещё")))
    got = {(x.date, x.subject) for x in merge(old, new, today)}
    assert (date(2026, 11, 3), "Крипто") in got          # прошлое ≤ 30 суток — храним
    assert (date(2026, 9, 1), "Крипто") not in got        # старше 30 суток — нет
    assert (date(2026, 11, 12), "Старая") not in got      # внутри горизонта — авторитет новой
    assert (date(2026, 12, 20), "Далёкая") in got         # за горизонтом новой — не трогаем
    assert {(date(2026, 11, 13), "Новая"), (date(2026, 11, 20), "Ещё")} <= got


def test_merge_today_is_union():
    today = date(2026, 11, 10)
    old = parse_ttable(ttable(L(today, "Утренняя", t="09:00-10:30")))
    new = parse_ttable(ttable(L(today, "Вечерняя")))
    assert {x.subject for x in merge(old, new, today)} == {"Утренняя", "Вечерняя"}


# ── изменения ─────────────────────────────────────────────────────────

def test_diff_kinds():
    today = date(2026, 11, 5)
    old = parse_ttable(ttable(L(D, "Крипто", "ауд.505"), L(date(2026, 11, 11), "Отменят"),
                              L(date(2026, 11, 12), "Перенесут"), L(date(2026, 11, 13), "Время")))
    new = parse_ttable(ttable(L(D, "Крипто", "ауд.507"), L(date(2026, 11, 14), "Перенесут"),
                              L(date(2026, 11, 13), "Время", t="18:40-20:10"), L(date(2026, 11, 16), "Новая")))
    kinds = {(c.kind, c.lesson.subject) for c in diff(old, new, today)}
    assert kinds == {("room_changed", "Крипто"), ("removed", "Отменят"), ("moved", "Перенесут"),
                     ("time_changed", "Время"), ("added", "Новая")}


def test_diff_ignores_today_and_beyond_horizon():
    today = D
    old = parse_ttable(ttable(L(today, "Сегодня"), L(date(2026, 12, 30), "Далёкая"), L(date(2026, 11, 11))))
    new = parse_ttable(ttable(L(date(2026, 11, 11))))
    assert diff(old, new, today) == []


def test_change_texts_are_human():
    old = parse_ttable(ttable(L(D, room="ауд.505")))
    new = parse_ttable(ttable(L(D, room="ауд.507")))
    (c,) = diff(old, new, date(2026, 11, 5))
    assert "507" in c.text() and "505" in c.text() and "10.11" in c.text()


# ── ingest ────────────────────────────────────────────────────────────

def test_ingest_fixture_then_change(store):
    n = FakeNotifier()
    r1 = ingest(FIXTURE.read_text(encoding="utf-8"), "push", NOW, store, n)
    assert r1.ok and r1.count == 5 and r1.changes == []          # первая выгрузка — без «изменений»
    assert store.source() == "push" and store.fetched_at() == NOW
    changed = FIXTURE.read_text(encoding="utf-8").replace("ауд.505", "ауд.512")
    r2 = ingest(changed, "push", NOW, store, n)
    assert [c.kind for c in r2.changes] == ["room_changed"]
    assert n.changes and store.history()[-1]["changes"][0]["kind"] == "room_changed"
    assert "5 занятий" in r2.summary() and "изменений: 1" in r2.summary()


def test_ingest_rejects_stub_wrong_group_and_suspicious_empty(store):
    n = FakeNotifier()
    assert ingest("<html><script>get_jhash()</script></html>", "push", NOW, store, n).error == "not_schedule"
    other = ttable(L(D, group="ИД 23.1/Б1-25"))
    assert ingest(other, "push", NOW, store, n).error == "wrong_group"
    assert ingest(FIXTURE.read_text(encoding="utf-8"), "push", NOW, store, n).ok
    r = ingest("", "push", NOW, store, n)
    assert r.error == "empty_suspicious" and len(store.lessons()) == 5


def test_store_survives_reload(store):
    ingest(FIXTURE.read_text(encoding="utf-8"), "push", NOW, store, FakeNotifier())
    again = ScheduleStore(store.path)
    assert [x.uid for x in again.lessons()] == [x.uid for x in store.lessons()]
    with open(store.path, encoding="utf-8") as f:
        data = json.load(f)
    assert data["group"] == config.MUIV_GROUP and data["horizon_to"] == "2026-11-17"


# ── прямой опрос ──────────────────────────────────────────────────────

def test_classify():
    ok = fetch.classify(200, "application/json", json.dumps({"ttable": "<h2>x</h2>"}))
    assert isinstance(ok, fetch.Fetched) and ok.ttable == "<h2>x</h2>"
    assert isinstance(fetch.classify(200, "text/html; charset=utf-8", "<html>__jhash_</html>"), fetch.Blocked)
    assert isinstance(fetch.classify(503, "text/html", ""), fetch.FetchError)
    assert fetch.classify(200, "application/json", "{").reason == "bad_json"
    assert fetch.form()["groupname"] == config.MUIV_GROUP and fetch.form()["el"] == "groupnames"


def test_direct_due_rules(store, monkeypatch):
    monkeypatch.setattr(config, "SCHEDULE_SOURCES", ("push",))
    assert not direct_due(datetime(2026, 11, 4, 7, 59), store)
    monkeypatch.setattr(config, "SCHEDULE_SOURCES", ("direct", "push"))
    monkeypatch.setattr(config, "SCHEDULE_SYNC_HOURS", (7,))
    assert not direct_due(datetime(2026, 11, 4, 8, 59), store)          # не тот час
    assert direct_due(datetime(2026, 11, 4, 7, 59), store)               # джиттер < 40 мин
    store.set_meta("direct_slot", "2026-11-04-7")
    assert not direct_due(datetime(2026, 11, 4, 7, 59), store)          # слот уже был
    store.set_meta("direct_slot", None)
    store.set_meta("direct_blocked_at", "2026-11-04T06:00:00")
    assert not direct_due(datetime(2026, 11, 4, 7, 59), store)          # блок < 24 ч
    assert direct_due(datetime(2026, 11, 5, 7, 59), store)


def test_sync_direct_blocked_backs_off(store):
    async def blocked():
        return fetch.Blocked()
    res = asyncio.run(sync_direct(NOW, store, fetch=blocked, notifier=FakeNotifier()))
    assert res.error == "blocked" and store.meta("direct_blocked_at") == NOW.isoformat(timespec="seconds")


def test_sync_direct_ok(store):
    async def ok():
        return fetch.Fetched(FIXTURE.read_text(encoding="utf-8"))
    res = asyncio.run(sync_direct(NOW, store, fetch=ok, notifier=FakeNotifier()))
    assert res.ok and res.count == 5 and store.source() == "direct"


def test_fetch_direct_uses_form_and_never_sends_cookies(monkeypatch):
    import httpx
    seen = {}

    def handler(request: httpx.Request):
        seen["body"] = request.content.decode()
        seen["cookie"] = request.headers.get("cookie")
        return httpx.Response(200, headers={"content-type": "application/json"},
                              json={"ttable": "<h2>05.11.2026</h2>"})
    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    got = asyncio.run(fetch.fetch_direct(client))
    assert isinstance(got, fetch.Fetched)
    assert "el=groupnames" in seen["body"] and seen["cookie"] is None


# ── запросы ───────────────────────────────────────────────────────────

def test_queries(store):
    ingest(FIXTURE.read_text(encoding="utf-8"), "push", NOW, store, FakeNotifier())
    at = datetime(2026, 11, 10, 19, 0)
    assert query.current_lesson(at, store).room == "505"
    assert query.next_lesson(datetime(2026, 11, 10, 22, 0), store).date == date(2026, 11, 16)
    assert query.describe_day(date(2026, 11, 7), datetime(2026, 11, 6, 12), voice=True,
                              store=store) == "Завтра пар нет."
    v = query.describe_day(date(2026, 11, 5), datetime(2026, 11, 5, 12), voice=True, store=store)
    assert v.startswith("Сегодня 1 пара: в 18:40 Технологическая практика, ауд. 531")
    t = query.describe_day(date(2026, 11, 5), datetime(2026, 11, 5, 12), voice=False, store=store)
    assert "Иванов Иван Иванович" in t and "Семинары ИПЗ" in t and "(проектно-технологическая)" in t
    assert "расписания на этот день у меня нет" in query.describe_day(
        date(2026, 12, 25), datetime(2026, 11, 5, 12), voice=True, store=store)
    assert query.today_prompt_line(datetime(2026, 11, 5, 9), store).startswith("ПАРЫ СЕГОДНЯ: 18:40–21:50")
    assert query.today_prompt_line(datetime(2026, 11, 7, 9), store) == ""
    assert query.is_stale(datetime(2026, 11, 20), store) and not query.is_stale(NOW, store)


def test_week_voice(store):
    ingest(FIXTURE.read_text(encoding="utf-8"), "push", NOW, store, FakeNotifier())
    w = query.describe_week(datetime(2026, 11, 5, 9), voice=True, store=store)
    assert w.startswith("На неделе: сегодня — 18:40 Технологическая практика")
    assert "вторник, 10.11" in w


def test_lesson_time_parsed():
    x = parse_ttable(ttable(L(D)))[0]
    assert (x.start, x.end) == (time(18, 40), time(21, 50))
