"""rank — какие найденные страницы действительно про то, о чём спросили.

Хлопок есть и в Scrap Mechanic, и в V Rising, и в статье про ткани: поисковик
возвращает всё. Судья — быстрый вызов модели по заголовкам и началу выдержек
(понимает транслит и сокращения). Не успел — правило по словам названия.
Подходящих нет — пусто: лучше честное «не нашла», чем чужая игра.
"""

from __future__ import annotations

import json
import logging
import re

log = logging.getLogger("sakura.search")

MAX_JUDGED = 10
EXCERPT_CHARS = 280

PROMPT = (
    "Вопрос Мастера: «{question}»\n"
    "Речь именно про: «{entity}»\n"
    "Найденные страницы:\n{items}\n\n"
    "Верни ТОЛЬКО JSON-массив номеров страниц, которые относятся именно к «{entity}» "
    "и помогают ответить на вопрос, лучшие первыми. Страницы про другую игру, "
    "программу или другое значение слова — не включай. Подходящих нет — []."
)


def _norm(text: str) -> str:
    return " ".join(re.sub(r"[\W_]+", " ", (text or "").lower()).split())


def by_words(items: list[dict], entity: str) -> list[dict]:
    """Все слова названия есть в адресе, заголовке или выдержке."""
    words = [w for w in _norm(entity).split() if len(w) >= 3]
    if not words:
        return list(items)
    return [it for it in items
            if all(w in _norm(" ".join((it.get("url", ""), it.get("title", ""), it.get("text", ""))))
                   for w in words)]


def parse(text: str, count: int) -> list[int] | None:
    m = re.search(r"\[[\d,\s]*\]", text or "")
    if not m:
        return None
    try:
        arr = json.loads(m.group(0))
    except json.JSONDecodeError:
        return None
    out = []
    for n in arr:
        if isinstance(n, int) and 1 <= n <= count and n not in out:
            out.append(n)
    return out


async def judge(items: list[dict], question: str, entity: str, *, timeout: float = 4.0) -> list[dict]:
    """Отобранные страницы (порядок — по судье). Без сущности — все как есть."""
    items = [it for it in items if it.get("text") or it.get("title")][:MAX_JUDGED]
    if not items or not entity:
        return items
    listing = "\n".join(
        f"[{i}] {it.get('title') or '—'} | {it.get('url', '')} | {(it.get('text') or '')[:EXCERPT_CHARS]}"
        for i, it in enumerate(items, 1))
    from config import MAIN_MODEL
    from sakura_core.llm import generate
    try:
        raw = await generate(PROMPT.format(question=question[:300], entity=entity, items=listing),
                             model=MAIN_MODEL, max_tokens=60, temperature=0.0,
                             safety=False, thinking=False, timeout=timeout)
    except Exception as e:
        log.info(f"[search] судья: {type(e).__name__} — правило по словам")
        raw = ""
    picked = parse(raw, len(items))
    if picked is None:
        return by_words(items, entity)
    return [items[n - 1] for n in picked]
