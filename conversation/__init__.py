"""Разговорный слой v3 (этап 5, 3/3): разговорные ветки вынуты из
handle_message / handle_voice_command в отдельные модули.

Контракт: def try_handle(text, ctx) -> Reply | None. Модули смотрят на
ТЕКСТ, не на Decision; синхронные, без LLM и без сетевого I/O. Всё, что
требует LLM или побочных действий, возвращается в Reply (промпт / команда
/ отправка) — исполняет поверхность, из которой пришёл текст. Это не
middleware и не цепочка перехватчиков: каждый модуль — перенесённая ветка.

Порядок опроса — явный список HANDLERS ниже. Место в router.route():
сессия → реестр (точное) → реестр (границы слов) → conversation → LLM →
разговор.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, Optional

@dataclass(frozen=True)
class Reply:
    """Ответ механизма.

    text          — готовый текст поверхности;
    prompt        — отдать в LLM, ответить его результатом (save_history=False);
    ws_command    — команда агенту до ответа (не ушла → fallback_text);
    fallback_text — текст, если ws_command не доставлена (нет агента);
    send_tg       — (user_id, composed|None, name): отправить человеку;
                    composed=None → текст придёт из prompt (LLM);
    run_clean_slate — выполнить протокол «чистый лист».
    """

    text: Optional[str] = None
    prompt: Optional[str] = None
    ws_command: Optional[str] = None
    fallback_text: Optional[str] = None
    send_tg: Optional[tuple] = None
    run_clean_slate: bool = False
    actions: tuple = ()               # запросы данных/действий адаптера:
                                      # ("steam_recommend",) | ("steam_guide", текст)


# Механизмы импортируются ПОСЛЕ Reply: каждый из них делает `from . import
# Reply`, и на момент его импорта имя уже должно существовать — иначе
# циклический импорт частично инициализированного пакета.
from . import calculator, clean_slate, fears, fortune, games  # noqa: E402
from . import remember_kv, translate, vip_message, word_game  # noqa: E402


# Явный порядок опроса — относительный порядок механизмов из хендлеров:
# переводчик → страхи → игра в слова → калькулятор → печенье → написать VIP →
# чистый лист → запомнить (app/правила) → steam. Первые шесть в обоих
# хендлерах шли именно так (TG: 3024/3034/3040/3084/3090; голос: 1364/1379/
# 1387/1450/1458); хвост взят из TG-порядка (vip 3123 → чистый лист 3163 →
# запомнить 3227), а steam-ветка в TG стояла позже остальных разговорных
# (3538) и в голосовом пути отсутствовала — поэтому она последняя.
HANDLERS: tuple[Callable, ...] = (
    translate.try_handle,
    fears.try_handle,
    word_game.try_handle,
    calculator.try_handle,
    fortune.try_handle,
    vip_message.try_handle,
    clean_slate.try_handle,
    remember_kv.try_handle,
    games.try_handle,
)


def try_handle(text: str, ctx: Optional[dict] = None) -> Optional[Reply]:
    """Опросить механизмы по порядку; первый непустой ответ — итог."""
    for handler in HANDLERS:
        reply = handler(text, ctx if ctx is not None else {})
        if reply is not None:
            return reply
    return None