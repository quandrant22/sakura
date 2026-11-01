"""intent — вопрос про игру во время игры сам идёт через зрение.

«А что сейчас по квесту сделать надо?» без «глянь на экран» уходило
классификатору и попадало в список задач Мастера («Активных задач нет»).
Правило до классификатора: вопрос про игру (квест, задание, босс, «где
найти», «куда идти», «что делать дальше»…) и игра идёт (Steam, заголовок
окна или недавно увиденное на экране) → vision.ask: кадр, факты, поиск,
ответ Сакуры.
"""

from __future__ import annotations

import logging
import re
import time

log = logging.getLogger("sakura.vision")

RECENT_SEEN_S = 900.0        # игра «идёт», если её видели на экране за последние 15 мин

_GAME_TOPIC = re.compile(
    r"(?<!\w)(квест\w*|задани[еяю]\w*|мисси[яиюе]\w*|босс\w*|уров(?:ень|ня|не)|прохожд\w*|"
    r"пройти|куда\s+(?:идти|бежать|ехать)|где\s+(?:найти|взять|лежит|лежат|купить|достать|искать)|"
    r"как\s+(?:скрафтить|сделать|построить|собрать|открыть|победить|убить|пройти|починить|получить)|"
    r"скрафт\w*|крафт\w*|рецепт\w*|"
    r"что\s+(?:мне\s+)?(?:сейчас\s+)?(?:делать|сделать)(?:\s+дальше)?|что\s+дальше|"
    r"в\s+(?:этой\s+)?игре)(?!\w)",
    re.IGNORECASE)
_EXPLICIT_GAME = re.compile(r"(?<!\w)(квест\w*|в\s+(?:этой\s+)?игре|босс\w*)(?!\w)", re.IGNORECASE)
_QUESTION = re.compile(
    r"\?|(?<!\w)(что|как|где|куда|какой|какая|какое|какие|зачем|почему|сколько|чем|подскажи|"
    r"помоги|скажи|объясни|расскажи|нужно|надо)(?!\w)",
    re.IGNORECASE)
# Явные команды не перехватываем, даже если в них есть «в игре».
_COMMAND = re.compile(r"^\s*(?:сакура[,\s]+)?(включи|выключи|поставь|открой|закрой|запусти|сделай громче|"
                      r"сделай тише|громче|тише|напомни|запомни|добавь задачу)(?!\w)", re.IGNORECASE)


def game_on(active_window: str | None, *, now: float | None = None) -> bool:
    """Идёт игра: Steam, заголовок окна или недавно увиденное на экране."""
    try:
        from modules import steam_integration
        if steam_integration._current_game:
            return True
    except Exception as e:
        log.debug(f"[intent] steam: {type(e).__name__}")
    try:
        from personality import is_game_active
        if is_game_active(active_window):
            return True
    except Exception as e:
        log.debug(f"[intent] окно: {type(e).__name__}")
    from sakura_core.vision import seen
    now = time.monotonic() if now is None else now
    s = seen.latest(now=now)
    if s and s.subject and now - s.at <= RECENT_SEEN_S:
        return True
    # То же окно, что Сакура видела раньше (любой давности): игра всё ещё открыта.
    last = seen.last_any()
    window = (active_window or "").lower()
    if last and last.subject and window:
        names = [n.lower() for n in (last.title, last.subject) if n and len(n) >= 3]
        if any(n in window or window in n for n in names):
            return True
    return False


def wants_screen(text: str, active_window: str | None = None, *, now: float | None = None) -> bool:
    """Вопрос про игру, на который стоит ответить, посмотрев на экран."""
    t = " ".join((text or "").split())
    if not t or _COMMAND.search(t) or not _GAME_TOPIC.search(t) or not _QUESTION.search(t):
        return False
    from sakura_core.send import has_tg_trigger
    if has_tg_trigger(t.lower()):           # «скинь в телегу, где найти …» — это отправка (tg_share)
        return False
    return bool(_EXPLICIT_GAME.search(t)) or game_on(active_window, now=now)
