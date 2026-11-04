"""Источник eios: личное расписание из ЭИОС (e.muiv.ru, Moodle).

Сервер входит под учёткой Мастера (EIOS_USERNAME / EIOS_PASSWORD из .env) —
так же, как человек в браузере, — и забирает страницу
/local/student_timetable/view.php. ЭИОС отвечает серверу без JS-проверки
(проверено с VPS 2026-11-04); если проверка появится — статус Blocked, как у
direct, без попыток её пройти (R2).

Безопасность:
- логин и пароль не логируются и не пишутся на диск; сессионная кука живёт
  только в памяти процесса;
- неверный логин/пароль → AuthError и стоп до перезапуска (чтобы не
  заблокировать учётку повторными входами).
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from urllib.parse import urljoin

import httpx
from bs4 import BeautifulSoup

import config
from sakura_core.schedule.fetch import USER_AGENT, Blocked, Fetched, FetchError

log = logging.getLogger("sakura.schedule")

TIMEOUT_S = 20.0
_STUB_MARKERS = ("__jhash_", "get_jhash", "gorizontal-vertikal")


@dataclass(frozen=True)
class AuthError:
    reason: str = "auth"


def _stub(text: str) -> bool:
    return any(m in text[:20000] for m in _STUB_MARKERS)


def _is_login_page(url: httpx.URL, text: str) -> bool:
    return "/login/" in url.path or 'type="password"' in text


def login_form(html: str, base: str) -> tuple[str, dict[str, str]] | None:
    """Форма входа: адрес отправки и поля (скрытые + имена логина/пароля).
    Ищем форму с полем пароля, а не по id: тема ЭИОС своя (new_vitte)."""
    soup = BeautifulSoup(html, "html.parser")
    pw = soup.find("input", attrs={"type": "password"})
    form = pw.find_parent("form") if pw else None
    if form is None:
        return None
    fields: dict[str, str] = {}
    user_name = None
    for inp in form.find_all("input"):
        name = inp.get("name")
        if not name:
            continue
        kind = (inp.get("type") or "text").lower()
        if kind == "hidden":
            fields[name] = inp.get("value", "")
        elif kind in ("text", "email") and user_name is None:
            user_name = name
    if user_name is None:
        return None
    fields[user_name] = "\x00user"
    fields[pw.get("name") or "password"] = "\x00pass"
    action = urljoin(base, form.get("action") or "/login/index.php")
    return action, fields


class EiosClient:
    """Сессия ЭИОС в памяти. Повторный вход — только когда сессия истекла."""

    def __init__(self, client: httpx.AsyncClient | None = None):
        self._client = client
        self.auth_failed = False
        self.last_url = ""          # путь последней страницы — для диагностики (без query)

    def _http(self) -> httpx.AsyncClient:
        if self._client is None:
            self._client = httpx.AsyncClient(
                timeout=TIMEOUT_S, follow_redirects=True,
                headers={"User-Agent": USER_AGENT, "Accept-Language": "ru"})
        return self._client

    async def aclose(self) -> None:
        if self._client is not None:
            await self._client.aclose()
            self._client = None

    async def _login(self) -> None | Blocked | FetchError | AuthError:
        http = self._http()
        base = config.EIOS_URL.rstrip("/")
        r = await http.get(f"{base}/login/index.php")
        if _stub(r.text):
            return Blocked()
        form = login_form(r.text, str(r.url))
        if form is None:
            return FetchError("no_login_form")
        action, fields = form
        data = {k: (config.EIOS_USERNAME if v == "\x00user" else
                    config.EIOS_PASSWORD if v == "\x00pass" else v) for k, v in fields.items()}
        r = await http.post(action, data=data)
        if _stub(r.text):
            return Blocked()
        if _is_login_page(r.url, r.text):
            return AuthError()
        return None

    async def fetch(self) -> Fetched | Blocked | FetchError | AuthError:
        if not (config.EIOS_USERNAME and config.EIOS_PASSWORD):
            return FetchError("no_credentials")
        if self.auth_failed:
            return AuthError("auth_stopped")
        url = config.EIOS_URL.rstrip("/") + "/local/student_timetable/view.php"
        try:
            for attempt in (1, 2):
                r = await self._http().get(url)
                if _stub(r.text):
                    return Blocked()
                if r.status_code != 200:
                    return FetchError(f"http_{r.status_code}")
                if not _is_login_page(r.url, r.text):
                    self.last_url = r.url.path
                    return Fetched(r.text)
                if attempt == 2:
                    return FetchError("session_lost")
                err = await self._login()
                if isinstance(err, AuthError):
                    self.auth_failed = True
                    log.warning("[schedule] ЭИОС: неверный логин или пароль — "
                                "входы остановлены до перезапуска")
                    return err
                if err is not None:
                    return err
            return FetchError("unreachable")
        except httpx.TimeoutException:
            return FetchError("timeout")
        except httpx.HTTPError as e:
            return FetchError(type(e).__name__)


_client: EiosClient | None = None


def get_client() -> EiosClient:
    global _client
    if _client is None:
        _client = EiosClient()
    return _client


async def fetch_eios() -> Fetched | Blocked | FetchError | AuthError:
    return await get_client().fetch()
