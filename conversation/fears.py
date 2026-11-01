"""Страхи Сакуры (этап 5, 3/3): реакции на пугающие темы, без LLM.

Мгновенная реакция — только на короткую реплику-не-вопрос («гроза за окном»,
«ой, как громко»). Вопрос или длинная фраза идут дальше: «где взять хлопок в
Scrap Mechanic?» — это про растение, а не про звук (случай 01.11).
"""

from __future__ import annotations

import re

from modules.fears import detect_fear_trigger

from . import Reply

MAX_WORDS = 6
_QUESTION = re.compile(
    r"\?|^\s*(?:сакура[,\s]+)?(?:а\s+)?(где|как|что|чем|почему|зачем|сколько|какой|какая|какое|какие|"
    r"куда|откуда|когда|кто|чей|можно|подскажи|скажи|расскажи|объясни|найди|помоги)(?!\w)",
    re.IGNORECASE)


def try_handle(text: str, ctx: dict) -> "Reply | None":
    t = " ".join((text or "").split())
    if _QUESTION.search(t) or len(t.split()) > MAX_WORDS:
        return None
    fear = detect_fear_trigger(t)
    if fear:
        return Reply(text=fear["response"])
    return None
