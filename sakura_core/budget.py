"""Бюджеты этапов v3 (этап 4): замеры с предупреждением о превышении.

| путь | бюджет |
|---|---|
| детерминированная команда (реестр) | 200 мс |
| команда через LLM | 1.5 с |
| первый звук голосового ответа | 800 мс |
| полный голосовой ответ | 4 с |

Превышение — log.warning, не чаще раза в 5 секунд на путь
(тот же троттлинг, что в замере блока слуха, этап 0.3).
"""

from __future__ import annotations

import logging
import time

log = logging.getLogger("sakura.budget")

BUDGETS_MS = {
    "command_registry": 200,     # приём текста → команда исполнителю
    "command_llm": 1500,         # то же, через LLM-роутер
    "voice_first_audio": 800,    # приём текста → первый TTS-пакет
    "voice_total": 4000,         # полный голосовой ответ (до tts_end)
}

_WARN_INTERVAL_S = 5.0
_last_warn: dict[str, float] = {}


def check(stage: str, elapsed_ms: float) -> float:
    """Сверить замер с бюджетом пути; предупредить при превышении.

    Возвращает elapsed_ms — удобно в одну строку: budget.check(stage, dt).
    """
    limit = BUDGETS_MS.get(stage)
    if limit is not None and elapsed_ms > limit:
        now = time.monotonic()
        if now - _last_warn.get(stage, 0.0) >= _WARN_INTERVAL_S:
            _last_warn[stage] = now
            log.warning(
                f"[budget] {stage}: {elapsed_ms:.0f}мс при бюджете {limit}мс — превышение"
            )
    return elapsed_ms


def timed(stage: str, t0: float) -> float:
    """Замер от t0 (time.monotonic()) до текущего момента со сверкой бюджета."""
    return check(stage, (time.monotonic() - t0) * 1000.0)
