"""Команды расписания: маршрутизация фраз, ответы голосом и в Telegram, контекст."""
# Наивное локальное время — как в коде Сакуры (R10).
# ruff: noqa: DTZ001

import asyncio
from datetime import datetime

import pytest

import config
from sakura_core.executor import ExecutionContext
from sakura_core.schedule import store as store_mod
from sakura_core.schedule.store import ScheduleStore
from sakura_core.schedule.sync import ingest
from tests.schedule_support import FIXTURE, FakeNotifier


@pytest.fixture(scope="module")
def index():
    from sakura_core.bridge import _load_capabilities
    from sakura_core.registry import build_index, load
    _load_capabilities()
    return build_index(load())


@pytest.fixture
def loaded(monkeypatch, tmp_path):
    """Хранилище с фикстурой и «сейчас» = чт 05.11.2026 12:00."""
    import capabilities.schedule as cap
    path = str(tmp_path / "s.json")
    monkeypatch.setattr(config, "SCHEDULE_PATH", path)
    monkeypatch.setattr(store_mod, "_store", None)
    ingest(FIXTURE.read_text(encoding="utf-8"), "push", datetime(2026, 11, 4, 12),
           ScheduleStore(path), FakeNotifier())
    store_mod.get_store().reload()
    now = {"t": datetime(2026, 11, 5, 12, 0)}
    monkeypatch.setattr(cap, "_now", lambda: now["t"])
    return cap, now


def call(cap, aid, source=None):
    return asyncio.run(cap.SCHEDULE_HANDLERS[aid](ExecutionContext(extra={"source": source})))


@pytest.mark.parametrize("phrase,aid", [
    ("расписание на сегодня", "schedule.today"),
    ("что сегодня по расписанию", "schedule.today"),
    ("какие сегодня пары", "schedule.today"),
    ("какие пары завтра", "schedule.tomorrow"),
    ("расписание на неделю", "schedule.week"),
    ("где у меня пара", "schedule.next"),
    ("какая аудитория", "schedule.next"),
    ("когда следующая пара", "schedule.next"),
    ("обнови расписание", "schedule.refresh"),
    ("покажи ближайшие события", "calendar.list"),
    ("календарь", "calendar.list"),
])
def test_routing(index, phrase, aid):
    m = index.match(phrase)
    assert m is not None and m[1].id == aid


def test_all_ids_vps_and_registered(index):
    from sakura_core.executor import get_handler
    from sakura_core.registry import load
    ids = {d.id: d for d in load() if d.id.startswith("schedule.")}
    assert set(ids) == {"schedule.today", "schedule.tomorrow", "schedule.week",
                        "schedule.next", "schedule.refresh"}
    assert all(d.executor == "vps" and get_handler(i) for i, d in ids.items())


def test_today_voice_and_telegram(loaded):
    cap, _ = loaded
    voice, ok = call(cap, "schedule.today")
    assert ok and voice == "Сегодня 1 пара: в 18:40 Технологическая практика, ауд. 531."
    tg, _ = call(cap, "schedule.today", source="telegram")
    assert tg.startswith("Сегодня:\n— 18:40–21:50 Технологическая (проектно-технологическая) практика")
    assert "Иванов Иван Иванович" in tg


def test_tomorrow_and_next(loaded):
    cap, now = loaded
    assert call(cap, "schedule.tomorrow")[0].startswith("Завтра 1 пара: в 18:40 Математические")
    now["t"] = datetime(2026, 11, 10, 19, 0)
    assert call(cap, "schedule.next")[0] == ("Сейчас идёт Криптографические методы защиты "
                                             "информации, ауд. 505, до 21:50.")
    now["t"] = datetime(2026, 11, 7, 12, 0)
    assert call(cap, "schedule.next")[0] == ("Вторник, 10.11 в 18:40 Криптографические методы "
                                             "защиты информации, ауд. 505.")


def test_stale_note(loaded):
    cap, now = loaded
    now["t"] = datetime(2026, 11, 16, 12, 0)
    text, _ = call(cap, "schedule.today")
    assert "Данные от 04.11" in text


def test_no_data(monkeypatch, tmp_path):
    import capabilities.schedule as cap
    monkeypatch.setattr(config, "SCHEDULE_PATH", str(tmp_path / "none.json"))
    monkeypatch.setattr(store_mod, "_store", None)
    # Без автоисточника — подсказка про закладку (независимо от локального .env).
    monkeypatch.setattr(config, "SCHEDULE_SOURCES", ("push",))
    text, ok = call(cap, "schedule.today")
    assert ok and text.startswith("Расписания у меня пока нет") and "закладку" in text
    # С автоисточником — обещание загрузить, без противоречащей просьбы о закладке.
    monkeypatch.setattr(config, "SCHEDULE_SOURCES", ("direct",))
    text, ok = call(cap, "schedule.today")
    assert ok and "сейчас загружу" in text and "закладку" not in text


def test_refresh_push_only_gives_hint(loaded, monkeypatch):
    cap, _ = loaded
    monkeypatch.setattr(config, "SCHEDULE_SOURCES", ("push",))
    assert "закладку" in call(cap, "schedule.refresh")[0]


def test_refresh_direct_blocked(loaded, monkeypatch):
    cap, _ = loaded
    from sakura_core.schedule import sync
    from sakura_core.schedule.sync import SyncResult
    monkeypatch.setattr(config, "SCHEDULE_SOURCES", ("direct", "push"))

    async def blocked(source, now):
        assert source == "direct"
        return SyncResult(False, "direct", error="blocked")
    monkeypatch.setattr(sync, "sync_auto", blocked)
    text, ok = call(cap, "schedule.refresh")
    assert not ok and "Сайт вуза не пускает" in text


def test_refresh_eios(loaded, monkeypatch):
    cap, _ = loaded
    from sakura_core.schedule import sync
    from sakura_core.schedule.sync import SyncResult
    monkeypatch.setattr(config, "SCHEDULE_SOURCES", ("eios", "push"))
    monkeypatch.setattr(config, "EIOS_USERNAME", "u")
    monkeypatch.setattr(config, "EIOS_PASSWORD", "p")

    async def ok(source, now):
        assert source == "eios"
        return SyncResult(True, "eios", count=5)
    monkeypatch.setattr(sync, "sync_auto", ok)
    assert call(cap, "schedule.refresh") == ("Обновила расписание: 5 занятий, без изменений.", True)


def test_eios_without_credentials_is_not_auto(monkeypatch):
    from sakura_core.schedule.sync import auto_source
    monkeypatch.setattr(config, "SCHEDULE_SOURCES", ("eios", "push"))
    monkeypatch.setattr(config, "EIOS_USERNAME", "")
    assert auto_source() is None


# ── контекст (modules/context.py) ─────────────────────────────────────

def _freeze(monkeypatch, d):
    import datetime as _dt

    import modules.context as ctx

    class FD(_dt.date):
        @classmethod
        def today(cls):
            return d
    monkeypatch.setattr(ctx, "date", FD)


def test_location_on_lesson(loaded, monkeypatch):
    from datetime import date

    import modules.context as ctx
    _freeze(monkeypatch, date(2026, 11, 10))
    loc = ctx.get_location_context(19, 0, 1)
    assert loc["location"] == "vuz" and loc["status"] == "studying"
    assert "Криптографические методы защиты информации, ауд. 505 (до 21:50)" in loc["desc"]


def test_location_before_lesson_and_no_maybe_vuz(loaded, monkeypatch):
    from datetime import date

    import modules.context as ctx
    _freeze(monkeypatch, date(2026, 11, 10))
    loc = ctx.get_location_context(18, 10, 1)
    assert loc["location"] == "home" and "сегодня в 18:40 пара" in loc["desc"]
    _freeze(monkeypatch, date(2026, 11, 9))                           # понедельник без пар
    assert ctx._location_by_clock(19, 0, 0)["location"] == "maybe_vuz"
    loc = ctx.get_location_context(19, 0, 0)
    assert loc == {"location": "home", "status": "free", "desc": "дома, свободен"}


def test_location_without_data_is_unchanged(monkeypatch, tmp_path):
    import modules.context as ctx
    monkeypatch.setattr(config, "SCHEDULE_PATH", str(tmp_path / "none.json"))
    monkeypatch.setattr(store_mod, "_store", None)
    loc = ctx.get_location_context(19, 0, 1)
    assert loc == ctx._location_by_clock(19, 0, 1)


def test_presence_lesson_mode():
    import modules.context as ctx
    c = {"time": {"hour": 19}, "master": {"activity": "unknown", "status": "studying",
                                          "location": "vuz", "is_gaming": False, "current_app": None},
         "body": {}}
    assert ctx.get_presence(c)["mode"] == "lesson"
