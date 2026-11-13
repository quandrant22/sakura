"""followup — продолжение разговора после вопроса по экрану.

Мастер спросил «глянь на экран», Сакура увидела Scrap Mechanic и ответила.
Следующая реплика («делать по квесту „Механическая станция“») уже не про
экран и не похожа на вопрос — поиск по ней не включался, и Сакура отвечала
из головы. Окно продолжения: FOLLOWUP_S после вопроса по экрану реплики
по делу (не «спасибо», не «ок») ищутся в интернете вместе с названием игры
или программы с экрана, а в промпт добавляется, о чём речь.
"""

from __future__ import annotations

import re
import time

FOLLOWUP_S = 600.0
QUERY_MAX = 160
MIN_WORDS = 3
_SMALL_TALK = re.compile(
    r"^(спасибо|спс|благодарю|понятно|ясно|ок|окей|ага|угу|хорошо|ладно|пока|круто|класс|"
    r"супер|отлично|понял|поняла|забей|неважно|стоп|хватит)\b",
    re.IGNORECASE)
_SYSTEM_PROMPT = re.compile(
    r"^(?:Мастер\s+(?:хочет|уходит|только|попросил|очистил)|"
    r"Скажи\s+Мастеру|"
    r"Результат(?:\s+выполнения)?\:|"
    r"Приложение\s+|"
    r"Запомнила\s+|"
    r"Событие\:|Подтверди|Ответь|Сгенерируй|Опиши)",
    re.IGNORECASE)


def plan(user_message: str, *, now: float | None = None) -> tuple[str | None, str]:
    """→ (запрос для поиска или None, дополнительный контекст для промпта).

    Вне окна продолжения или без темы — (None, "")."""
    from sakura_core.vision import seen
    now = time.monotonic() if now is None else now
    s = seen.latest(now=now)
    if s is None or s.purpose != "ask" or not s.subject or now - s.at > FOLLOWUP_S:
        return None, ""
    context = (f"Мастер продолжает разговор про то, что у него на экране: {s.subject} "
               f"({s.saw}). Отвечай про это, не здоровайся.")
    msg = " ".join((user_message or "").split())
    if _SYSTEM_PROMPT.match(msg):
        return None, ""
    if len(msg.split()) < MIN_WORDS or _SMALL_TALK.match(msg):
        return None, context
    query = msg if s.subject.lower() in msg.lower() else f"{s.subject} {msg}"
    return query[:QUERY_MAX], context
