"""Единый поиск Сакуры в интернете (feat/search-core).

    from sakura_core.search import run
    ev = await run("где найти хлопок", channel="voice")
    if ev.ok: ... ev.facts, ev.sources, ev.items

Шаги: context (о чём речь) → plan (сущность и запросы) → pipeline._fetch
(Parallel) → rank (судья) → pages (дочитка лучшей страницы) → Evidence.
Документ: docs/SEARCH.md.
"""

from sakura_core.search.pipeline import BUDGETS, Evidence, run  # noqa: F401
