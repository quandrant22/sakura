"""Прямой запрос расписания с VPS (источник direct) с прохождением JS-проверки."""
from __future__ import annotations

import asyncio
import logging
import urllib.parse
from dataclasses import dataclass

import httpx

import config

log = logging.getLogger("sakura.schedule")

TIMEOUT_S = 20.0
USER_AGENT = (
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"
)
PAGE_URL = "https://www.muiv.ru/studentu/fakultet-it/raspisaniya/"
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


def _get_jhash(b: int) -> int:
    x, k = 123456789, 0
    for i in range(1677696):
        x = ((x + b) ^ (x + (x % 3) + (x % 17) + b) ^ i) % 16776960
        if x % 117 == 0:
            k = (k + 1) % 1111
    return k


def _encode_ua(s: str) -> str:
    res = urllib.parse.quote(s, safe="-_.!~*'()")
    for ch in "!'()*":
        res = res.replace(ch, f"%{ord(ch):02x}")
    return res


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
    client = client or httpx.AsyncClient(
        timeout=TIMEOUT_S,
        headers={"User-Agent": USER_AGENT},
        follow_redirects=True,
    )
    try:
        r = await client.post(config.MUIV_TIMETABLE_URL, data=form())
        res = classify(r.status_code, r.headers.get("content-type", ""), r.text)
        if not isinstance(res, Blocked):
            return res

        js_p = r.cookies.get("__js_p_") or client.cookies.get("__js_p_")
        if not js_p:
            return res

        code = int(js_p.split(",")[0])
        jhash = _get_jhash(code)
        await asyncio.sleep(1.2)

        cookie_hdr = f"__js_p_={js_p}; __jhash_={jhash}; __jua_={_encode_ua(USER_AGENT)}"
        r_page = await client.get(PAGE_URL, headers={"Cookie": cookie_hdr, "Referer": PAGE_URL})
        extra = "; ".join(f"{k}={v}" for k, v in r_page.cookies.items())
        if extra:
            cookie_hdr = f"{cookie_hdr}; {extra}"

        r2 = await client.post(
            config.MUIV_TIMETABLE_URL,
            data=form(),
            headers={
                "Cookie": cookie_hdr,
                "Referer": PAGE_URL,
                "X-Requested-With": "XMLHttpRequest",
            },
        )
        return classify(r2.status_code, r2.headers.get("content-type", ""), r2.text)
    except httpx.TimeoutException:
        return FetchError("timeout")
    except httpx.HTTPError as e:
        return FetchError(type(e).__name__)
    finally:
        if own:
            await client.aclose()
