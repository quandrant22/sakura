"""Клиенты LLM (этап 4): genai.Client создаётся один раз за процесс и живёт
в кэше. В v2 клиент создавался заново на каждый вызов
(modules/intent_classifier.py:176, modules/command_router.py:573) —
TLS-хендшейк на каждый вызов. У всех вызовов есть таймаут (в v2 их не было:
зависший запрос подвешивал весь голосовой путь) и фолбэк моделей.
"""

from __future__ import annotations

import asyncio
import logging
from typing import AsyncIterator, Optional

import config

log = logging.getLogger("sakura.llm")

_clients: dict[str, object] = {}
_created = 0  # счётчик созданий клиента — тест этапа 4 следит, что он не растёт

DEFAULT_TIMEOUT_S = 12.0

# Фолбэк моделей: основная → запасная (config не менять, имена из v2)
FALLBACK_MODELS = (config.MAIN_MODEL, config.FALLBACK_MODEL)


def get_client(api_key: str):
    """Клиент на ключ, закэшированный на процесс."""
    global _created
    client = _clients.get(api_key)
    if client is None:
        from google import genai
        client = genai.Client(api_key=api_key)
        _clients[api_key] = client
        _created += 1
        log.debug("[llm] создан genai.Client (ключ …%s)", api_key[-6:])
    return client


def created_count() -> int:
    """Сколько клиентов создано за процесс (в v2 — по одному на вызов)."""
    return _created


def pick_key(api_key: Optional[str] = None) -> str:
    """Ключ для вызова. Ротация ключей остаётся в v2 (mark_key_used)."""
    if api_key:
        return api_key
    keys = [k for k in getattr(config, "GEMINI_KEYS", []) if k]
    if not keys:
        raise RuntimeError("нет GEMINI_KEY_* в конфигурации")
    return keys[0]


async def generate(contents, *, system: str = "", model: Optional[str] = None,
                   max_tokens: int = 512, temperature: float = 0.85,
                   timeout: float = DEFAULT_TIMEOUT_S,
                   api_key: Optional[str] = None) -> str:
    """generate_content с таймаутом и фолбэком моделей. '' при полном провале."""
    from google.genai import types as _t

    client = get_client(pick_key(api_key))
    models = (model,) if model else FALLBACK_MODELS
    last_exc: Optional[Exception] = None
    for m in models:
        try:
            r = await asyncio.wait_for(asyncio.to_thread(
                lambda m=m: client.models.generate_content(
                    model=m,
                    contents=contents,
                    config=_t.GenerateContentConfig(
                        system_instruction=system or None,
                        max_output_tokens=max_tokens,
                        temperature=temperature,
                    ),
                ),
            ), timeout=timeout)
            return (r.text or "").strip()
        except Exception as e:
            last_exc = e
            log.warning(f"[llm] {m}: {type(e).__name__}: {e}; фолбэк моделей")
    if last_exc is not None:
        log.error(f"[llm] все модели не ответили: {last_exc}")
    return ""


async def stream_tokens(contents, *, system: str = "", model: Optional[str] = None,
                        max_tokens: int = 200, temperature: float = 0.85,
                        timeout: float = DEFAULT_TIMEOUT_S,
                        api_key: Optional[str] = None) -> AsyncIterator[str]:
    """Стриминг текста LLM: токены по мере поступления.

    Итератор google-genai блокирующий → читается в отдельном треде, чанки
    кладутся в asyncio-очередь. Именно здесь v2 (tts_server._drain) читала
    весь поток до конца — это и делало «стриминг» фикцией.
    """
    from google.genai import types as _t

    client = get_client(pick_key(api_key))
    loop = asyncio.get_event_loop()
    q: asyncio.Queue = asyncio.Queue()

    def _produce() -> None:
        try:
            for chunk in client.models.generate_content_stream(
                model=model or FALLBACK_MODELS[0],
                contents=contents,
                config=_t.GenerateContentConfig(
                    system_instruction=system or None,
                    max_output_tokens=max_tokens,
                    temperature=temperature,
                ),
            ):
                t = getattr(chunk, "text", None)
                if t:
                    loop.call_soon_threadsafe(q.put_nowait, t)
        except Exception as e:  # ошибка потока → исключение в очередь
            loop.call_soon_threadsafe(q.put_nowait, e)
        finally:
            loop.call_soon_threadsafe(q.put_nowait, None)

    import threading
    threading.Thread(target=_produce, daemon=True).start()

    while True:
        item = await asyncio.wait_for(q.get(), timeout=timeout)
        if item is None:
            return
        if isinstance(item, Exception):
            raise item
        yield item
