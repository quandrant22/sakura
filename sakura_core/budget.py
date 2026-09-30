"""Бюджеты этапов v3 (этап 4): замеры с предупреждением о превышении.

| путь | бюджет |
|---|---|
| детерминированная команда (реестр) | 200 мс |
| команда через LLM | 1.5 с |
| первый звук голосового ответа (от приёма) | 2 с |
| LLM-ответ готов (от приёма) | 3 с |

Голосовые бюджеты (п.5 perf/voice-latency) считаются ОТ ПРИЁМА голоса
(received_at), а не от старта стрима: классификатор роутера и подготовка
ответа идут параллельно (п.2), и время классификации обязано попадать в
замер — иначе бюджет врёт ровно на ту задержку, которую убрали.
Точка отсчёта: budget.since(received_at, t0).

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
    "voice_first_audio": 2000,   # приём голоса → первый TTS-пакет
    "voice_llm_done": 3000,      # приём голоса → весь ответ отдан в TTS
}

_WARN_INTERVAL_S = 5.0
_last_warn: dict[str, float] = {}


def since(received_at: float | None, t0: float) -> float:
    """Точка отсчёта голосовых бюджетов: приём голоса, иначе старт стрима.

    received_at — time.monotonic() момента получения голосового сообщения
    (ставит ws-хендлер). None (Telegram/v2-пути) → прежнее t0.
    """
    return t0 if received_at is None else received_at


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
