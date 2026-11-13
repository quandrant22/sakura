"""Уведомления расписания: напоминание, изменения, устаревание, гейты."""
# Наивное локальное время — как в коде Сакуры (R10).
# ruff: noqa: DTZ001

import asyncio
from datetime import date, datetime

import pytest

import config
from sakura_core.schedule.notify import Notifier
from sakura_core.schedule.store import ScheduleStore
from sakura_core.schedule.sync import ingest
from tests.schedule_support import FIXTURE, ttable


@pytest.fixture
def env(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "SCHEDULE_REMIND_BEFORE_MIN", 90)
    monkeypatch.setattr(config, "SCHEDULE_STALE_DAYS", 7)
    # Тест не должен зависеть от локального .env (eios/direct): только закладка.
    monkeypatch.setattr(config, "SCHEDULE_SOURCES", ("push",))
    store = ScheduleStore(str(tmp_path / "s.json"))
    sent: list[str] = []
    quiet = {"on": False}

    async def deliver(text):
        sent.append(text)
    n = Notifier(store, deliver=deliver, quiet=lambda: quiet["on"])
    ingest(FIXTURE.read_text(encoding="utf-8"), "push", datetime(2026, 11, 4, 12), store, n)
    return store, n, sent, quiet


def tick(n, at):
    return asyncio.run(n.tick(at))


def test_reminder_once_in_window(env):
    _, n, _, _ = env
    assert tick(n, datetime(2026, 11, 5, 17, 0)) == []                 # 100 мин до пары — рано
    got = tick(n, datetime(2026, 11, 5, 17, 15))                       # 85 мин — пора
    assert got == ["В 18:40 Технологическая практика, ауд. 531."]
    assert tick(n, datetime(2026, 11, 5, 17, 30)) == []                # один раз за день
    want = "В 18:40 Математические и инструментальные методы анализа данных, ауд. 319."
    assert tick(n, datetime(2026, 11, 6, 17, 15)) == [want]


def test_reminder_disabled(env, monkeypatch):
    _, n, _, _ = env
    monkeypatch.setattr(config, "SCHEDULE_REMIND_BEFORE_MIN", 0)
    assert tick(n, datetime(2026, 11, 5, 17, 15)) == []


def test_quiet_and_night_postpone_not_cancel(env):
    _, n, _, quiet = env
    quiet["on"] = True
    assert tick(n, datetime(2026, 11, 5, 17, 15)) == []
    quiet["on"] = False
    assert len(tick(n, datetime(2026, 11, 5, 17, 20))) == 1
    assert tick(n, datetime(2026, 11, 5, 23, 30)) == []                # ночь — молчим


def test_urgent_change_delivered_far_change_not(env):
    store, n, _, _ = env
    now = datetime(2026, 11, 9, 12, 0)
    text = FIXTURE.read_text(encoding="utf-8")
    changed = (text.replace("ауд.505", "ауд.512")                        # 10.11 — в пределах 48 ч
                   .replace("ауд.507", "ауд.600"))                        # 17.11 — далеко
    res = ingest(changed, "push", now, store, n)
    assert len(res.changes) == 2
    got = tick(n, now)
    assert len(got) == 1 and "512" in got[0] and "600" not in got[0]
    assert got[0].startswith("Расписание поменялось.")
    assert tick(n, now) == []                                           # очередь очищена


def test_stale_nag_once_a_day(env):
    _, n, _, _ = env
    assert tick(n, datetime(2026, 11, 12, 9, 0)) == []                  # до 10:00 не дёргаем
    got = tick(n, datetime(2026, 11, 12, 11, 0))
    assert len(got) == 1 and "от 04.11" in got[0] and "закладку" in got[0]
    assert tick(n, datetime(2026, 11, 12, 15, 0)) == []


def test_no_data_no_nag(tmp_path):
    sent = []

    async def deliver(t):
        sent.append(t)
    n = Notifier(ScheduleStore(str(tmp_path / "x.json")), deliver=deliver, quiet=lambda: False)
    assert asyncio.run(n.tick(datetime(2026, 11, 12, 11, 0))) == []


def test_state_survives_restart(env):
    store, n, _, _ = env
    tick(n, datetime(2026, 11, 5, 17, 15))
    fresh = Notifier(ScheduleStore(store.path), deliver=n.deliver, quiet=lambda: False)
    assert asyncio.run(fresh.tick(datetime(2026, 11, 5, 17, 40))) == []


def test_two_lessons_tail(tmp_path):
    store = ScheduleStore(str(tmp_path / "s.json"))
    sent = []

    async def deliver(t):
        sent.append(t)
    n = Notifier(store, deliver=deliver, quiet=lambda: False)
    d = date(2026, 11, 20)
    ingest(ttable((d, "09:00-10:30", "Первая", "101", "Лекции", "А"),
                  (d, "10:40-12:10", "Вторая", "102", "Лекции", "Б")), "push",
           datetime(2026, 11, 19, 12), store, n)
    got = asyncio.run(n.tick(datetime(2026, 11, 20, 8, 0)))
    assert got == ["В 09:00 Первая, ауд. 101. Всего сегодня пар: 2."]
