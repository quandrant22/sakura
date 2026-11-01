"""providers — откуда берутся результаты поиска.

  parallel — Parallel Search MCP: бесплатно для агентов, выдержки уже сжаты
             под вопрос (лучшее для модели), но это сервис одной компании;
  searxng  — свой метапоисковик на VPS (Google, Bing, DuckDuckGo, Википедия…):
             без ключей и квот, широта выдачи; ограничение — капча у
             поисковиков при большом потоке с одного IP (одному человеку не грозит).

Оба опрашиваются параллельно; результаты сливаются по нормализованному адресу,
порядок — поочерёдно из каждого (лучшие каждого — вперёд). Один поставщик лёг —
работает второй. Включение — SEARCH_PROVIDERS, адрес SearXNG — SEARXNG_URL.
"""

from __future__ import annotations

import asyncio
import logging
import re
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

log = logging.getLogger("sakura.search")

PER_QUERY = 6
SNIPPET_MAX = 600
_TRACKING = re.compile(r"^(utm_\w+|fbclid|gclid|yclid|ref|ref_src)$", re.IGNORECASE)


def norm_url(url: str) -> str:
    """Ключ для дублей: без схемы, www, хвостового «/», якоря и меток utm."""
    try:
        parts = urlsplit((url or "").strip())
    except ValueError:
        return (url or "").strip().lower()
    host = parts.netloc.lower().removeprefix("www.")
    query = urlencode([(k, v) for k, v in parse_qsl(parts.query) if not _TRACKING.match(k)])
    path = parts.path.rstrip("/") or "/"
    return urlunsplit(("", host, path, query, "")).lstrip("/")


def merge(*lists: list[dict]) -> list[dict]:
    """Поочерёдно из каждого списка, без дублей по адресу; у дубля берётся
    более длинная выдержка и недостающий заголовок."""
    out: list[dict] = []
    index: dict[str, dict] = {}
    longest = max((len(x) for x in lists), default=0)
    for i in range(longest):
        for lst in lists:
            if i >= len(lst):
                continue
            item = dict(lst[i])
            key = norm_url(item.get("url", ""))
            if not key:
                continue
            if key in index:
                kept = index[key]
                if len(item.get("text") or "") > len(kept.get("text") or ""):
                    kept["text"] = item["text"]
                kept["title"] = kept.get("title") or item.get("title") or ""
                kept["via"] = f"{kept.get('via', '')}+{item.get('via', '')}".strip("+")
                continue
            index[key] = item
            out.append(item)
    return out


# ── Parallel ───────────────────────────────────────────────────────

async def parallel(queries: list[str], objective: str, *, limit: int = 8) -> list[dict]:
    from modules.parallel_search import parallel_search
    items: list[dict] = []
    await parallel_search(objective, max_results=limit, queries=queries, items_out=items)
    for it in items:
        it["via"] = "parallel"
    return items


# ── SearXNG ────────────────────────────────────────────────────────

def parse_searxng(data: dict, limit: int = PER_QUERY) -> list[dict]:
    """Ответ /search?format=json → [{url, title, text, image?, via}]."""
    out = []
    for r in (data or {}).get("results") or []:
        if not isinstance(r, dict) or not r.get("url"):
            continue
        item = {"url": str(r["url"]).strip(), "title": " ".join(str(r.get("title") or "").split()),
                "text": " ".join(str(r.get("content") or "").split())[:SNIPPET_MAX], "via": "searxng"}
        if r.get("img_src") or r.get("thumbnail"):
            item["thumb"] = r.get("img_src") or r.get("thumbnail")
        out.append(item)
        if len(out) >= limit:
            break
    return out


async def searxng(queries: list[str], *, base_url: str, timeout: float = 8.0) -> list[dict]:
    """Все запросы плана параллельно; результаты — поочерёдно по запросам."""
    import httpx

    from modules.web_search import HEADERS
    base = base_url.rstrip("/")

    async def one(client, q: str) -> list[dict]:
        try:
            r = await client.get(f"{base}/search", params={"q": q, "format": "json", "safesearch": 0})
            if r.status_code != 200:
                log.info(f"[search] searxng: HTTP {r.status_code} на «{q[:40]}»")
                return []
            return parse_searxng(r.json())
        except Exception as e:
            log.info(f"[search] searxng: {type(e).__name__} на «{q[:40]}»")
            return []

    async with httpx.AsyncClient(timeout=timeout, headers=HEADERS) as client:
        per_query = await asyncio.gather(*(one(client, q) for q in queries))
    return merge(*per_query)


# ── все включённые ─────────────────────────────────────────────────

def enabled() -> list[str]:
    import config
    names = [n.strip().lower() for n in (getattr(config, "SEARCH_PROVIDERS", "parallel") or "").split(",")]
    out = [n for n in names if n in ("parallel", "searxng")]
    if "searxng" in out and not getattr(config, "SEARXNG_URL", ""):
        out.remove("searxng")
    return out or ["parallel"]


async def fetch_all(queries: list[str], objective: str, *, timeout: float) -> list[dict]:
    """Все включённые поставщики параллельно; сбой одного не мешает другим."""
    import config
    names = enabled()
    jobs = []
    for name in names:
        if name == "parallel":
            jobs.append(parallel(queries, objective))
        else:
            jobs.append(searxng(queries, base_url=config.SEARXNG_URL, timeout=min(timeout, 8.0)))
    results = await asyncio.gather(*(asyncio.wait_for(j, timeout) for j in jobs), return_exceptions=True)
    lists, counts = [], {}
    for name, res in zip(names, results, strict=True):
        if isinstance(res, BaseException):
            log.info(f"[search] {name}: {type(res).__name__}")
            counts[name] = "сбой"
            continue
        lists.append(res)
        counts[name] = len(res)
    merged = merge(*lists)
    log.info(f"[search] поставщики {counts} → {len(merged)} без дублей")
    return merged
