"""Прямой запрос расписания с VPS (источник direct).

Работает только если вуз внёс IP сервера в исключения своей защиты. Иначе
сайт отдаёт страницу JS-проверки — это статус Blocked, а не ошибка, которую
надо чинить: проверку не проходим, не эмулируем, куки браузера не подставляем
(решение R2). После Blocked следующая попытка — не раньше чем через сутки.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass

import httpx

import config

log = logging.getLogger("sakura.schedule")

TIMEOUT_S = 15.0
USER_AGENT = "Sakura-schedule/1.0 (personal use)"
_STUB_MARKERS = ("__jhash_", "gorizontal-vertikal", "get_jhash")


@dataclass(frozen=True)
class Fetched:
    ttable: str


@dataclass(frozen=True)
class Blocked:
    reason: str = "antibot"


@dataclass(frozen=True)
class FetchError:
    reason: str


def form() -> dict[str, str]:
    """Тело запроса — как у страницы при выборе группы (el=groupnames)."""
    return {
        "el": "groupnames", "branch": config.MUIV_BRANCH, "year": config.MUIV_YEAR,
        "faculty": config.MUIV_FACULTY, "studyform": config.MUIV_STUDYFORM,
        "groupname": config.MUIV_GROUP, "edulevel": "",
    }


def classify(status: int, content_type: str, body: str) -> Fetched | Blocked | FetchError:
    if status != 200:
        return FetchError(f"http_{status}")
    if "json" not in (content_type or "").lower() or any(m in body[:20000] for m in _STUB_MARKERS):
        return Blocked()
    import json
    try:
        data = json.loads(body)
    except ValueError:
        return FetchError("bad_json")
    tt = data.get("ttable") if isinstance(data, dict) else None
    if not isinstance(tt, str):
        return FetchError("no_ttable")
    return Fetched(tt)


async def fetch_direct(client: httpx.AsyncClient | None = None) -> Fetched | Blocked | FetchError:
    own = client is None
    client = client or httpx.AsyncClient(timeout=TIMEOUT_S, headers={"User-Agent": USER_AGENT})
    try:
        r = await client.post(config.MUIV_TIMETABLE_URL, data=form())
        return classify(r.status_code, r.headers.get("content-type", ""), r.text)
    except httpx.TimeoutException:
        return FetchError("timeout")
    except httpx.HTTPError as e:
        return FetchError(type(e).__name__)
    finally:
        if own:
            await client.aclose()
