"""Стилизация справочных ответов системы в стиле J.A.R.V.I.S. (этап: humanize_command_reply).

Информационные команды (weather.*, schedule.*, steam.*, vps.status, briefing.now)
возвращают сухие данные. Данный модуль преобразует их в реплики Сакуры:
спокойное достоинство, безупречный такт, обращение строго на «Вы», сохранение
всех фактов, цифр и названий без выдумывания.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any, Callable

log = logging.getLogger("sakura.stylize")

HUMANIZE_SYSTEM_PROMPT = (
    "Ты — Сакура (персональный ИИ-ассистент в стиле классического J.A.R.V.I.S.). "
    'Обращайся к Мастеру строго на "Вы", со спокойным достоинством, безупречным тактом и легким изяществом. '
    "Передай Мастеру эти данные от системы коротко и по делу (1–3 предложения, без списков и markdown-разметки, для голосовой озвучки). "
    "СТРОГОЕ ПРАВИЛО: сохрани все цифры, время, названия предметов, игр и фактов абсолютно точно, ничего не выдумывай от себя."
)

INFORMATIONAL_PREFIXES = ("weather.", "schedule.", "steam.", "music_stats.")
INFORMATIONAL_EXACT = ("vps.status", "vps.feeling", "briefing.now")
NON_INFORMATIONAL = ("schedule.refresh",)


def is_informational_action(action: str | None) -> bool:
    """Является ли действие информационной справочной командой."""
    if not action:
        return False
    if action in NON_INFORMATIONAL:
        return False
    return action.startswith(INFORMATIONAL_PREFIXES) or action in INFORMATIONAL_EXACT


async def humanize_command_reply(
    raw_text: str,
    action: str = "",
    *,
    timeout: float | None = None,
    llm_generator: Callable[..., Any] | None = None,
) -> str:
    """Быстрая обертка стилизации ответа под личность Сакуры (J.A.R.V.I.S.).

    Если action не входит в список информационных команд, текст пуст,
    LLM не ответил за таймаут, вернул пустую строку или нет API-ключей —
    мгновенно возвращает исходный raw_text.
    """
    if not raw_text or not raw_text.strip():
        return raw_text
    if not is_informational_action(action):
        return raw_text
    if timeout is None:
        import config as _config
        timeout = float(getattr(_config, "STYLIZE_TIMEOUT_S", 0.8))
    if timeout <= 0:
        return raw_text          # стилизация выключена — ответ звучит сразу

    try:
        if llm_generator is None:
            import config
            keys = [k for k in getattr(config, "GEMINI_KEYS", []) if k]
            if not keys:
                return raw_text
            from sakura_core.llm import generate
            gen_fn = generate
        else:
            gen_fn = llm_generator

        contents = f"Данные от системы:\n{raw_text.strip()}"
        res = await asyncio.wait_for(
            gen_fn(
                contents,
                system=HUMANIZE_SYSTEM_PROMPT,
                timeout=timeout,
                max_tokens=150,
            ),
            # Жёсткий потолок: ответ команды не ждёт стилизацию дольше timeout.
            timeout=timeout,
        )
        # Только непустая строка: любой другой ответ (None, объект SDK)
        # ушёл бы в speak/ack и уронил доставку ответа команды.
        if isinstance(res, str) and res.strip():
            return res.strip()
    except Exception as e:
        log.debug(f"[stylize] humanize_command_reply fallback ({type(e).__name__}: {e})")

    return raw_text
