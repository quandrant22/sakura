"""pipeline — единый поиск Сакуры: тема → план → поиск → отбор → дочитка → доказательства.

Все пути, которым нужен интернет (голос, текст, вопрос по экрану, Telegram,
фоновые «исследования»), идут сюда. Бюджет времени — по каналу: голосу нельзя
ждать 20 с, Telegram собирается фоном.

Нет фактов — ok=False и пустые факты. Никаких «ответов из памяти модели» под
видом интернета: вызывающий честно говорит, что не нашёл.
"""

from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass, field

log = logging.getLogger("sakura.search")


@dataclass(frozen=True)
class Budget:
    total: float          # весь поиск, с
    plan: float           # вызов модели на план
    judge: float          # вызов модели-судьи (0 — только правило по словам)
    enrich: bool          # дочитывать лучшую страницу
    facts_max: int        # символов фактов в промпт


BUDGETS = {
    "voice": Budget(total=9.0, plan=3.0, judge=2.5, enrich=False, facts_max=2500),
    "text": Budget(total=18.0, plan=4.0, judge=4.0, enrich=True, facts_max=4000),
    "tg": Budget(total=25.0, plan=4.0, judge=4.0, enrich=True, facts_max=5000),
    "background": Budget(total=25.0, plan=4.0, judge=0.0, enrich=False, facts_max=3000),
}
CACHE_TTL_S = 30 * 60
MAX_RESULTS = 8


@dataclass
class Evidence:
    ok: bool = False
    entity: str = ""
    queries: list[str] = field(default_factory=list)
    items: list[dict] = field(default_factory=list)      # отобранные: url, title, text[, content, image]
    found: int = 0                                       # сколько вернул поисковик
    facts: str = ""
    timings: dict = field(default_factory=dict)

    @property
    def sources(self) -> list[str]:
        return [it["url"] for it in self.items if it.get("url")]

    @property
    def image_urls(self) -> list[str]:
        return [it["image"] for it in self.items if it.get("image")]


_cache: dict[tuple, tuple[float, Evidence]] = {}


def _key(question: str, entity: str, channel: str) -> tuple:
    return (" ".join(question.lower().split()), entity.lower(), "deep" if BUDGETS[channel].enrich else "fast")


def reset_cache() -> None:
    _cache.clear()


def build_facts(items: list[dict], limit: int) -> str:
    parts = []
    for it in items:
        head = f"{it['title']}: " if it.get("title") else ""
        if it.get("text"):
            parts.append(head + it["text"])
        if it.get("content"):
            parts.append(f"Подробно со страницы «{it.get('title') or it.get('url')}»: {it['content']}")
    return "\n\n".join(parts).strip()[:limit]


async def _fetch(queries: list[str], objective: str, timeout: float = 8.0) -> list[dict]:
    """Все включённые поставщики (search/providers.py), без дублей."""
    from sakura_core.search import providers
    return await providers.fetch_all(queries, objective, timeout=timeout)


async def run(question: str, *, channel: str = "text", subject: str | None = None,
              active_window: str | None = None, dialogue: str = "", screen: str = "",
              hint: str = "") -> Evidence:
    """Найти доказательства для ответа. Не бросает исключений."""
    from sakura_core.search import context, pages, plan, rank
    budget = BUDGETS.get(channel, BUDGETS["text"])
    t0 = time.monotonic()
    marks: dict[str, float] = {}

    def left() -> float:
        return max(0.5, budget.total - (time.monotonic() - t0))

    def mark(name: str, since: float) -> float:
        now = time.monotonic()
        marks[name] = round(now - since, 2)
        return now

    question = " ".join((question or "").split())
    if not question:
        return Evidence()
    if subject is None:
        subject = context.resolve_subject(active_window)

    t = time.monotonic()
    p = await plan.make(question, subject=subject, dialogue=dialogue, screen=screen, hint=hint,
                        timeout=min(budget.plan, left()))
    t = mark("план", t)
    entity = p.entity or subject

    key = _key(question, entity, channel)
    cached = _cache.get(key)
    if cached and time.monotonic() - cached[0] < CACHE_TTL_S:
        log.info(f"[search] кэш: «{entity}» {len(cached[1].items)} стр.")
        return cached[1]

    try:
        remaining = left()
        items = await asyncio.wait_for(_fetch(p.queries, question if not entity else f"{entity}: {question}",
                                              remaining), remaining + 0.5)
    except Exception as e:
        log.info(f"[search] поиск: {type(e).__name__}")
        items = []
    t = mark("поиск", t)

    if budget.judge > 0 and items:
        picked = await rank.judge(items, question, entity, timeout=min(budget.judge, left()))
    else:
        picked = rank.by_words(items, entity) if entity else items
    t = mark("отбор", t)

    if budget.enrich and picked and left() > 2.0:
        top = picked[0]
        try:
            content, image = await asyncio.wait_for(pages.read(top["url"]), min(pages.FETCH_TIMEOUT_S, left()))
        except Exception as e:
            log.info(f"[search] дочитка: {type(e).__name__}")
            content, image = "", None
        if content:
            top["content"] = content
        if image:
            top["image"] = image
        mark("дочитка", t)

    ev = Evidence(ok=bool(picked), entity=entity, queries=p.queries, items=picked, found=len(items),
                  facts=build_facts(picked, budget.facts_max), timings=marks)
    ev.ok = bool(ev.facts)
    total = round(time.monotonic() - t0, 2)
    log.info(f"[search] канал={channel} тема=«{entity or '—'}» план={p.source} запросы={p.queries} "
             f"найдено={len(items)} отобрано={len(picked)} за {total}с {marks}")
    if ev.ok:
        _cache[key] = (time.monotonic(), ev)
    return ev
