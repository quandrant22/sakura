"""plan — что искать: сущность и 1–3 запроса (по-русски, по-английски, вики).

Один быстрый вызов модели (без «размышления», с потолком). Не успела —
запасной план: тема + вопрос как есть. Английский запрос важен для игр:
лучшие источники — английские вики (Fandom).
"""

from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass, field

log = logging.getLogger("sakura.search")

MAX_QUERIES = 3
QUERY_MAX = 120

PROMPT = (
    "Составь план веб-поиска для ответа Мастеру.\n"
    "Вопрос Мастера: «{question}»\n"
    "Тема разговора (игра/программа, если известна): «{subject}»\n"
    "{extra}"
    "Ответь ТОЛЬКО JSON-объектом:\n"
    '{{"entity": "о чём вопрос: точное название игры, программы, человека, места; '
    'если в вопросе названо явно — оно важнее темы; иначе тема; неизвестно — пусто", '
    '"queries": ["3–7 слов по-русски с entity", "3–7 слов по-английски с entity '
    '(предмет переведи на английский)", "для игр: entity wiki и предмет по-английски"]}}\n'
    "Правила: русскую транслитерацию названий заменяй оригиналом («скрап механик» → "
    "Scrap Mechanic); сохраняй точные названия предметов, навыков, квестов; без воды; "
    "для вопросов не про игры третий запрос — уточняющий по-русски."
)


@dataclass
class Plan:
    entity: str = ""
    queries: list[str] = field(default_factory=list)
    source: str = "fallback"          # model | fallback


def _clean_query(q: str) -> str:
    from modules.parallel_search import _strip_wrap_quotes
    q = _strip_wrap_quotes(" ".join(str(q or "").split()))
    return q.replace("«", '"').replace("»", '"')[:QUERY_MAX]


def parse(text: str) -> Plan | None:
    m = re.search(r"\{.*\}", text or "", re.DOTALL)
    if not m:
        return None
    try:
        data = json.loads(m.group(0))
    except json.JSONDecodeError:
        return None
    if not isinstance(data, dict):
        return None
    queries = []
    for q in data.get("queries") or []:
        q = _clean_query(q)
        if q and q.lower() not in (x.lower() for x in queries):
            queries.append(q)
    if not queries:
        return None
    entity = " ".join(str(data.get("entity") or "").split())[:80]
    return Plan(entity=entity, queries=queries[:MAX_QUERIES], source="model")


def fallback(question: str, subject: str = "", hint: str = "") -> Plan:
    from modules.parallel_search import _fallback_query
    base = _fallback_query(question)
    queries = []
    for q in (hint, f"{subject} {base}".strip() if subject and subject.lower() not in base.lower() else base):
        q = _clean_query(q)
        if q and q.lower() not in (x.lower() for x in queries):
            queries.append(q)
    return Plan(entity=subject, queries=queries[:MAX_QUERIES], source="fallback")


async def make(question: str, *, subject: str = "", dialogue: str = "", screen: str = "",
               hint: str = "", timeout: float = 4.0) -> Plan:
    extra = ""
    if hint:
        extra += f"Готовый запрос (используй как первый): «{hint}»\n"
    if screen:
        extra += f"С экрана Мастера: {screen[:400]}\n"
    if dialogue:
        extra += f"Недавний разговор:\n{dialogue[-800:]}\n"
    from config import MAIN_MODEL
    from sakura_core.llm import generate
    try:
        raw = await generate(PROMPT.format(question=question[:300], subject=subject or "неизвестна",
                                           extra=extra),
                             model=MAIN_MODEL, max_tokens=300, temperature=0.2,
                             safety=False, thinking=False, timeout=timeout)
    except Exception as e:
        log.info(f"[search] план: модель не ответила ({type(e).__name__}) — запасной")
        return fallback(question, subject, hint)
    plan = parse(raw)
    if plan is None:
        log.info("[search] план: ответ модели не разобран — запасной")
        return fallback(question, subject, hint)
    if hint and hint.lower() not in (q.lower() for q in plan.queries):
        plan.queries = [_clean_query(hint)] + plan.queries[:MAX_QUERIES - 1]
    if not plan.entity:
        plan.entity = subject
    return plan
