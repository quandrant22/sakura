"""Steam-механики (этап 5, 3/3): «во что поиграть» и гайды. Данные берутся
асинхронно (recommend_games / find_guide) и прогоняются через LLM — модуль
только распознаёт запрос и отдаёт действие адаптеру."""

from __future__ import annotations

from . import Reply

_RECOMMEND_TRIGGERS = (
    "во что поиграть", "что поиграть", "порекомендуй игру", "выбери игру",
    "из избранного", "любимые игры", "топ игр", "лучшие игры", "мои игры",
    "что поставить", "во что сыграть",
)

_GUIDE_TRIGGERS = ("гайд", "как играть", "как пройти",
                   "подскажи по игре", "совет по")


def try_handle(text: str, ctx: dict) -> "Reply | None":
    tl = text.lower()
    if any(w in tl for w in _RECOMMEND_TRIGGERS):
        return Reply(actions=(("steam_recommend",),))
    if any(w in tl for w in _GUIDE_TRIGGERS):
        return Reply(actions=(("steam_guide", text),))
    return None