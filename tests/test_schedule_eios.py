"""Источник eios: разбор страницы ЭИОС и вход в Moodle (сеть замокана)."""
# Наивное локальное время — как в коде Сакуры (R10).
# ruff: noqa: DTZ001
import asyncio
import logging
from datetime import date, datetime
from pathlib import Path

import httpx
import pytest

import config
from sakura_core.schedule import eios
from sakura_core.schedule.fetch import Blocked, Fetched, FetchError
from sakura_core.schedule.parse import ParseError, parse_eios
from sakura_core.schedule.store import ScheduleStore
from sakura_core.schedule.sync import auto_due, ingest, sync_auto
from tests.schedule_support import FIXTURE, FakeNotifier

EIOS = Path(__file__).parent / "fixtures" / "eios_timetable_2026-11-04.html"
GROUP = "ИД 86.1/М1-25"
USER, PASS = "student-login", "s3cret-pass"

LOGIN_PAGE = """<html><body><form class="login-form" action="https://e.muiv.ru/login/index.php" method="post" id="login">
<input type="hidden" name="anchor" value=""><input type="hidden" name="logintoken" value="TOKEN123">
<input type="text" name="username" id="username"><input type="password" name="password" id="password">
<button type="submit" id="loginbtn">Вход</button></form></body></html>"""
STUB = "<html><style>.gorizontal-vertikal{}</style><script>function get_jhash(b){}</script></html>"


# ── разбор ────────────────────────────────────────────────────────────

def test_parse_eios_fixture():
    xs = parse_eios(EIOS.read_text(encoding="utf-8"), GROUP)
    assert [x.date for x in xs] == [date(2026, 11, 5), date(2026, 11, 6), date(2026, 11, 10),
                                    date(2026, 11, 16), date(2026, 11, 17)]
    x = xs[2]
    assert (x.subject, x.room, x.kind, x.teacher, x.group) == (
        "Криптографические методы защиты информации", "505", "lecture", "Сидоров Пётр Павлович", GROUP)
    assert x.department == "Кафедра информационных систем"


def test_eios_and_www_give_same_uids():
    """Один и тот же семестр из двух мест сайта — те же занятия (смена источника
    не порождает «изменений»)."""
    from sakura_core.schedule.parse import parse_ttable
    a = parse_eios(EIOS.read_text(encoding="utf-8"), GROUP)
    b = parse_ttable(FIXTURE.read_text(encoding="utf-8"))
    assert [x.uid for x in a] == [x.uid for x in b]
    assert [(x.room, x.kind) for x in a] == [(x.room, x.kind) for x in b]


def test_parse_eios_rejects_login_and_stub_and_empty_section():
    with pytest.raises(ParseError):
        parse_eios(LOGIN_PAGE, GROUP)
    with pytest.raises(ParseError):
        parse_eios(STUB, GROUP)
    with pytest.raises(ParseError):
        parse_eios("<html><body>Главная</body></html>", GROUP)
    assert parse_eios('<div class="main_container_studtimetable"></div>', GROUP) == []


def test_login_form_generic():
    action, fields = eios.login_form(LOGIN_PAGE, "https://e.muiv.ru/login/index.php")
    assert action == "https://e.muiv.ru/login/index.php"
    assert fields["logintoken"] == "TOKEN123" and fields["anchor"] == ""
    assert set(fields) == {"anchor", "logintoken", "username", "password"}
    assert eios.login_form("<html>нет формы</html>", "https://e.muiv.ru/") is None


# ── вход и получение (Moodle имитируется MockTransport) ───────────────

class FakeMoodle:
    def __init__(self, *, stub_on=None, page=None):
        self.logins = 0
        self.posted: dict | None = None
        self.stub_on = stub_on
        self.page = page or EIOS.read_text(encoding="utf-8")

    def __call__(self, request: httpx.Request) -> httpx.Response:
        path = request.url.path
        if self.stub_on and self.stub_on in path:
            return httpx.Response(200, text=STUB, headers={"content-type": "text/html"})
        authed = "MoodleSession=ok" in (request.headers.get("cookie") or "")
        if path == "/local/student_timetable/view.php":
            if not authed:
                return httpx.Response(303, headers={"location": "https://e.muiv.ru/login/index.php"})
            return httpx.Response(200, text=self.page, headers={"content-type": "text/html"})
        if path == "/login/index.php" and request.method == "GET":
            return httpx.Response(200, text=LOGIN_PAGE, headers={"content-type": "text/html"})
        if path == "/login/index.php" and request.method == "POST":
            self.logins += 1
            from urllib.parse import parse_qs
            self.posted = {k: v[0] for k, v in parse_qs(request.content.decode(),
                                                        keep_blank_values=True).items()}
            if self.posted.get("username") == USER and self.posted.get("password") == PASS \
                    and self.posted.get("logintoken") == "TOKEN123":
                return httpx.Response(303, headers={"location": "https://e.muiv.ru/my/",
                                                    "set-cookie": "MoodleSession=ok; Path=/"})
            return httpx.Response(200, text=LOGIN_PAGE + "Неверный логин или пароль",
                                  headers={"content-type": "text/html"})
        if path == "/my/":
            return httpx.Response(200, text="<html>Личный кабинет</html>")
        return httpx.Response(404)


@pytest.fixture
def creds(monkeypatch):
    monkeypatch.setattr(config, "EIOS_URL", "https://e.muiv.ru")
    monkeypatch.setattr(config, "EIOS_USERNAME", USER)
    monkeypatch.setattr(config, "EIOS_PASSWORD", PASS)


def client_for(moodle):
    return eios.EiosClient(httpx.AsyncClient(transport=httpx.MockTransport(moodle),
                                             follow_redirects=True))


def test_login_then_fetch_then_reuse_session(creds):
    m = FakeMoodle()
    c = client_for(m)

    async def run():
        a = await c.fetch()
        b = await c.fetch()
        await c.aclose()
        return a, b
    a, b = asyncio.run(run())
    assert isinstance(a, Fetched) and "studtimetable" in a.ttable
    assert isinstance(b, Fetched)
    assert m.logins == 1                                   # вторая выгрузка — по той же сессии
    assert m.posted == {"anchor": "", "logintoken": "TOKEN123", "username": USER, "password": PASS}


def test_wrong_password_stops_further_logins(creds, monkeypatch):
    monkeypatch.setattr(config, "EIOS_PASSWORD", "wrong")
    m = FakeMoodle()
    c = client_for(m)

    async def run():
        return await c.fetch(), await c.fetch()
    a, b = asyncio.run(run())
    assert isinstance(a, eios.AuthError) and a.reason == "auth"
    assert isinstance(b, eios.AuthError) and b.reason == "auth_stopped"
    assert m.logins == 1                                   # учётку не долбим


def test_no_credentials(monkeypatch):
    monkeypatch.setattr(config, "EIOS_USERNAME", "")
    got = asyncio.run(eios.EiosClient().fetch())
    assert isinstance(got, FetchError) and got.reason == "no_credentials"


@pytest.mark.parametrize("where", ["/login/index.php", "/local/student_timetable/view.php"])
def test_antibot_page_is_blocked(creds, where):
    got = asyncio.run(client_for(FakeMoodle(stub_on=where)).fetch())
    assert isinstance(got, Blocked)


def test_credentials_never_logged(creds, monkeypatch, caplog):
    caplog.set_level(logging.DEBUG)
    asyncio.run(client_for(FakeMoodle()).fetch())
    monkeypatch.setattr(config, "EIOS_PASSWORD", "another-secret")
    asyncio.run(client_for(FakeMoodle()).fetch())
    assert USER not in caplog.text and PASS not in caplog.text and "another-secret" not in caplog.text


# ── синхронизация ─────────────────────────────────────────────────────

def test_ingest_eios_and_switch_from_push_without_fake_changes(tmp_path):
    store = ScheduleStore(str(tmp_path / "s.json"))
    now = datetime(2026, 11, 4, 12)
    assert ingest(FIXTURE.read_text(encoding="utf-8"), "push", now, store, FakeNotifier()).ok
    res = ingest(EIOS.read_text(encoding="utf-8"), "eios", now, store, FakeNotifier())
    assert res.ok and res.count == 5 and res.changes == []
    assert store.source() == "eios"
    assert store.lessons()[0].department == "Кафедра информационных систем"


def test_sync_auto_eios_and_auth_notice(tmp_path, creds, monkeypatch):
    store = ScheduleStore(str(tmp_path / "s.json"))
    now = datetime(2026, 11, 4, 7, 50)

    async def ok():
        return Fetched(EIOS.read_text(encoding="utf-8"))
    res = asyncio.run(sync_auto("eios", now, store, fetch=ok, notifier=FakeNotifier()))
    assert res.ok and store.meta("eios_slot") == "2026-11-04-7"

    async def bad():
        return eios.AuthError()
    n = FakeNotifier()
    res = asyncio.run(sync_auto("eios", now, store, fetch=bad, notifier=n))
    assert res.error == "auth" and any("EIOS_PASSWORD" in str(x) for x in n.changes)
    assert "логин или пароль" in res.summary()


def test_auto_due_for_eios(tmp_path, monkeypatch):
    store = ScheduleStore(str(tmp_path / "s.json"))
    monkeypatch.setattr(config, "SCHEDULE_SOURCES", ("eios", "push"))
    monkeypatch.setattr(config, "SCHEDULE_SYNC_HOURS", (7, 19))
    assert auto_due(datetime(2026, 11, 4, 19, 59), store, "eios")
    assert not auto_due(datetime(2026, 11, 4, 12, 0), store, "eios")
    assert not auto_due(datetime(2026, 11, 4, 19, 59), store, "direct")   # direct не включён


def test_captcha_page_is_blocked(creds):
    captcha = "<html><head><title>Captcha</title></head><body><form>…</form></body></html>"
    m = FakeMoodle(page=captcha)
    got = asyncio.run(client_for(m).fetch())
    assert isinstance(got, Blocked)
