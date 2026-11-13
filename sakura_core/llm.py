"""Клиенты LLM (этап 4+6): genai.Client создаётся один раз за процесс и живёт
в кэше. В v2 клиент создавался заново на каждый вызов
(modules/intent_classifier.py:176, modules/command_router.py:573) —
TLS-хендшейк на каждый вызов. У всех вызовов есть таймаут (в v2 их не было:
зависший запрос подвешивал весь голосовой путь) и фолбэк моделей.

Этап 6: NO_SAFETY, _thinking,ooled в модуле. Вся генерация текста — через
generate() / stream_tokens().
"""

from __future__ import annotations

import asyncio
import inspect
import json
import logging
import random
import re
import time
from dataclasses import dataclass
from typing import AsyncIterator, Optional

import config
from sakura_core.nlu import IntentParse, LlmUnavailable
from sakura_core.tasks import spawn

log = logging.getLogger("sakura.llm")

_clients: dict[str, object] = {}
_created = 0  # счётчик созданий клиента — тест этапа 4 следит, что он не растёт

DEFAULT_TIMEOUT_S = 20.0
_TRANSIENT_RETRY_DELAYS = (1.0, 2.0)
# Доля общего бюджета на модель, у которой в цепочке есть запасная:
# зависшая первая модель не должна съедать весь ход (20 с → 12 с ей, 8 с запасной).
NON_LAST_MODEL_SHARE = 0.6

# Фолбэк моделей: основная → запасная (config не менять, имена из v2)
FALLBACK_MODELS = (config.MAIN_MODEL, config.FALLBACK_MODEL)

# Импорт из prompt.py — ленивый внутри ask_gemini, но нужен для патчинга в тестах.
# Цикл llm ↔ prompt не возникает: prompt.py не импортирует llm.py.
from sakura_core.prompt import (  # noqa: E402
    _build_system,
    _build_guest_system,
)


# ── Безопасность и мышление ──────────────────────────────────────────────

def _thinking(model: str):
    """ThinkingConfig: minimal для Gemini 3.x, None для Gemma."""
    from google.genai import types as _t
    return _t.ThinkingConfig(thinking_level="minimal") if model.startswith("gemini-3") else None


def _no_safety():
    """Список SafetySetting с выключенным фильтром (для generate)."""
    from google.genai import types as _t
    return [
        _t.SafetySetting(category="HARM_CATEGORY_HARASSMENT",        threshold="OFF"),
        _t.SafetySetting(category="HARM_CATEGORY_HATE_SPEECH",       threshold="OFF"),
        _t.SafetySetting(category="HARM_CATEGORY_SEXUALLY_EXPLICIT", threshold="OFF"),
        _t.SafetySetting(category="HARM_CATEGORY_DANGEROUS_CONTENT", threshold="OFF"),
        _t.SafetySetting(category="HARM_CATEGORY_CIVIC_INTEGRITY",   threshold="OFF"),
    ]


AUDIENCES = ("master", "guest")


def _guest_safety():
    """Фильтры для гостей, Химари и общего чата: откровенное режется уже на
    среднем уровне, остальное — только высокое (I5)."""
    from google.genai import types as _t
    return [
        _t.SafetySetting(category="HARM_CATEGORY_HARASSMENT",        threshold="BLOCK_ONLY_HIGH"),
        _t.SafetySetting(category="HARM_CATEGORY_HATE_SPEECH",       threshold="BLOCK_ONLY_HIGH"),
        _t.SafetySetting(category="HARM_CATEGORY_SEXUALLY_EXPLICIT", threshold="BLOCK_MEDIUM_AND_ABOVE"),
        _t.SafetySetting(category="HARM_CATEGORY_DANGEROUS_CONTENT", threshold="BLOCK_ONLY_HIGH"),
        _t.SafetySetting(category="HARM_CATEGORY_CIVIC_INTEGRITY",   threshold="BLOCK_ONLY_HIGH"),
    ]


def _safety_settings(audience: str):
    """Настройки безопасности по аудитории ответа. Неизвестная → гостевые."""
    return _no_safety() if audience == "master" else _guest_safety()


def _part_value(part, name):
    if isinstance(part, dict):
        return part.get(name)
    return getattr(part, name, None)


def _has_image(contents) -> bool:
    for content in contents if isinstance(contents, (list, tuple)) else (contents,):
        parts = _part_value(content, "parts") or ()
        if not parts and any(_part_value(content, field) is not None
                             for field in ("inline_data", "file_data")):
            parts = (content,)
        for part in parts:
            for field in ("inline_data", "file_data"):
                blob = _part_value(part, field)
                mime_type = _part_value(blob, "mime_type") if blob is not None else None
                if isinstance(mime_type, str) and mime_type.lower().startswith("image/"):
                    return True
    return False


def _models_to_try(model: Optional[str], chain=None, contents=None) -> tuple[str, ...]:
    if _has_image(contents):
        chain = getattr(config, "VISION_MODEL_CHAIN", ())
    elif chain is None:
        chain = getattr(config, "MODEL_CHAIN", None)
    if chain is not None:
        models = tuple(dict.fromkeys(m for m in chain if m))
        if models:
            return models
    if model:
        return tuple(dict.fromkeys((model, config.FALLBACK_MODEL)))
    return tuple(dict.fromkeys(FALLBACK_MODELS))


def _chain_path(chain, contents) -> str:
    if _has_image(contents):
        return "vision"
    if chain is config.VOICE_MODEL_CHAIN:
        return "voice"
    if chain is config.BACKGROUND_MODEL_CHAIN:
        return "background"
    return "chat"


def _chain_for_request(history_limit: int, save_history: bool):
    if not save_history:
        caller = inspect.stack()[2].function
        log.warning(
            "[llm] save_history=False without explicit chain in %s; using MODEL_CHAIN",
            caller,
        )
        return config.MODEL_CHAIN
    if history_limit == config.VOICE_HISTORY_LIMIT:
        return config.VOICE_MODEL_CHAIN
    return config.MODEL_CHAIN


def _error_code(error: Exception) -> str:
    code = getattr(error, "code", None)
    if callable(code):
        try:
            code = code()
        except Exception:
            code = None
    if code is None:
        code = getattr(error, "status_code", None)
    if code is not None:
        return str(getattr(code, "value", code))
    text = str(error).upper()
    for marker in ("RESOURCE_EXHAUSTED", "UNAVAILABLE", "INTERNAL"):
        if marker in text:
            return marker
    match = re.search(r"\b(400|403|404|408|429|500|502|503|504)\b", text)
    if match:
        return match.group(1)
    if isinstance(error, (asyncio.TimeoutError, TimeoutError)) or "TIMEOUT" in text:
        return "TIMEOUT"
    if any(marker in text for marker in ("SSL", "DECRYPTION", "BAD RECORD MAC")):
        return "SSL"
    return type(error).__name__


def _error_kind(error: Exception) -> str:
    code = _error_code(error).upper()
    text = str(error).upper()
    if code in ("429", "RESOURCE_EXHAUSTED") or "QUOTA" in text:
        return "rate_limit"
    if code in ("503", "UNAVAILABLE", "500", "INTERNAL", "408", "TIMEOUT", "SSL"):
        return "transient"
    if code in ("400", "403", "404"):
        return "request"
    return "other"


def _key_number(api_key: str) -> str:
    try:
        return str(config.GEMINI_KEYS.index(api_key) + 1)
    except (ValueError, AttributeError):
        return "?"


# Пауза после 429 — на пару (ключ, модель), а не на ключ целиком: квоты у
# Gemini раздельные по моделям. 429 от gemma (16K TPM) не должен выключать
# gemini-*-flash-lite на том же ключе («no active Gemini API key»).
RATE_LIMIT_COOLDOWN_S = 60.0
_model_cooldown: dict[tuple[str, str], float] = {}


# Пауза после сбоя (TIMEOUT, 5xx после повторов) — тоже на пару (ключ, модель)
# и только если в цепочке есть запасная: иначе каждый вызов снова ждал бы
# зависшую модель весь её срок (живой прогон 04.11: по 12 с на зрение,
# ответ и фон — «долго думала», обрыв хода по сторожу).
TRANSIENT_COOLDOWN_S = 120.0


def _cooling(key: str, model: str) -> bool:
    return time.monotonic() < _model_cooldown.get((key, model), 0.0)


def _cool_after_failure(key: str, model: str) -> None:
    until = time.monotonic() + TRANSIENT_COOLDOWN_S
    if _model_cooldown.get((key, model), 0.0) < until:
        _model_cooldown[(key, model)] = until
        log.info("[llm] key=%s model=%s на паузе %.0fс (сбой)", _key_number(key), model,
                 TRANSIENT_COOLDOWN_S)


def _candidate_keys(preferred: str | None) -> list[str]:
    keys: list[str] = []
    for key in (preferred, *getattr(config, "GEMINI_KEYS", ())):
        if key and key not in keys:
            keys.append(key)
    return keys


def _key_for_model(model: str, preferred: str | None) -> str | None:
    """Первый ключ без паузы для этой модели; None — у модели все ключи на паузе."""
    return next((k for k in _candidate_keys(preferred) if not _cooling(k, model)), None)


def _next_key_after_limit(api_key: str, tried: set[str], model: str | None = None,
                          error: Exception | None = None) -> str | None:
    if model:
        delay = None
        if error is not None:
            delay = retry_delay(error)
        _model_cooldown[(api_key, model)] = time.monotonic() + (delay or RATE_LIMIT_COOLDOWN_S)
        log.info("[llm] key=%s model=%s на паузе %.0fс", _key_number(api_key), model,
                 delay or RATE_LIMIT_COOLDOWN_S)
    else:
        try:
            config.mark_key_rate_limited(api_key)
        except Exception as err:
            log.debug("[llm] could not mark rate-limited key: %s", type(err).__name__)
    try:
        preferred = config.get_active_key()
    except Exception:
        preferred = None
    for key in _candidate_keys(preferred):
        if key in tried or (model and _cooling(key, model)):
            continue
        return key
    return None


def _log_attempt_failure(model: str, api_key: str, error: Exception,
                         elapsed: float) -> None:
    code = _error_code(error)
    log.info("[llm] attempt failed model=%s key=%s code=%s elapsed=%.2fs",
             model, _key_number(api_key), code, elapsed)
    if _error_kind(error) == "request":
        log.warning("[llm] model=%s rejected request with code=%s", model, code)


class _EmptyResponseError(Exception):
    code = "empty"


def _initial_key(api_key: Optional[str]) -> Optional[str]:
    if api_key:
        return api_key
    try:
        return config.get_active_key()
    except Exception:
        return None


# ── Параметры генерации по модели (S4) ───────────────────────────────────

def filter_params(model: str, cfg: dict) -> dict:
    """Параметры GenerateContentConfig, которые модель принимает.

    gemma-* — только подтверждённые scripts/probe_gemma.py (config.GEMMA_PARAMS),
    thinking_config — только с полем thinking_level (остальное вырезается);
    модели из config.NO_SAMPLING_MODELS (gemini-3.5-flash-lite) не принимают
    пользовательские temperature/top_p — они не передаются."""
    name = (model or "").lower()
    out = dict(cfg)
    if name.startswith("gemma-"):
        allowed = set(getattr(config, "GEMMA_PARAMS", ()))
        out = {k: v for k, v in out.items() if k in allowed or v is None}
        if cfg.get("thinking_config") is not None:
            # Gemma 4 принимает только thinking_level; thinking_budget — 400.
            tc = _gemma_thinking(cfg["thinking_config"])
            if tc is not None:
                out["thinking_config"] = tc
    if name.startswith(tuple(getattr(config, "NO_SAMPLING_MODELS", ()))):
        out.pop("temperature", None)
        out.pop("top_p", None)
    dropped = sorted(k for k in cfg if k not in out and cfg[k] is not None)
    if dropped:
        log.debug("[llm] model=%s: не передаю %s", model, ",".join(dropped))
    return out


def _gemma_thinking(tc):
    """ThinkingConfig только с thinking_level; без него — None (не передавать)."""
    from google.genai import types as _t
    level = tc.get("thinking_level") if isinstance(tc, dict) else getattr(tc, "thinking_level", None)
    return _t.ThinkingConfig(thinking_level=level) if level else None


# ── Клиент ───────────────────────────────────────────────────────────────


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
                   api_key: Optional[str] = None,
                   safety: bool = True, thinking: bool = True,
                   response_mime_type: Optional[str] = None,
                   chain=None, audience: str = "master") -> str:
    """Generate with bounded retries and a single request-wide time budget."""
    models = _models_to_try(model, chain, contents)
    chain_path = _chain_path(chain, contents)
    started = time.monotonic()
    first_key = _initial_key(api_key)
    if not first_key:
        log.error("[llm] no active Gemini API key")
        return ""

    for model_index, model_name in enumerate(models):
        preferred = first_key if model_index == 0 else (_initial_key(None) or first_key)
        current_key = preferred if api_key else _key_for_model(model_name, preferred)
        if not current_key:
            log.info("[llm] model=%s: все ключи на паузе — следующая модель", model_name)
            continue
        tried_keys: set[str] = set()
        transient_retries = 0
        has_fallback = model_index < len(models) - 1
        # Срок этой модели: у не последней — доля бюджета, у последней — весь остаток.
        model_deadline = started + timeout
        if has_fallback:
            model_deadline = min(model_deadline,
                                 time.monotonic() + timeout * NON_LAST_MODEL_SHARE)
        while current_key:
            remaining = model_deadline - time.monotonic()
            if remaining <= 0:
                break
            attempt_started = time.monotonic()
            try:
                client = await asyncio.wait_for(
                    asyncio.to_thread(get_client, current_key), timeout=remaining,
                )
                remaining = model_deadline - time.monotonic()
                if remaining <= 0:
                    raise asyncio.TimeoutError()

                def _invoke(m=model_name, c=client):
                    from google.genai import types as _t

                    cfg_kwargs = dict(
                        system_instruction=system or None,
                        max_output_tokens=max_tokens,
                        temperature=temperature,
                    )
                    if safety:
                        cfg_kwargs["safety_settings"] = _safety_settings(audience)
                    if thinking:
                        tc = _thinking(m)
                        if tc is not None:
                            cfg_kwargs["thinking_config"] = tc
                    if response_mime_type:
                        cfg_kwargs["response_mime_type"] = response_mime_type
                    return c.models.generate_content(
                        model=m,
                        contents=contents,
                        config=_t.GenerateContentConfig(**filter_params(m, cfg_kwargs)),
                    )

                response = await asyncio.wait_for(asyncio.to_thread(
                    _invoke,
                ), timeout=remaining)
                text = (response.text or "").strip()
                if not text:
                    raise _EmptyResponseError("model returned empty text")
                log.info(
                    "[llm] success model=%s chain=%s elapsed=%.2fs",
                    model_name, chain_path, time.monotonic() - started,
                )
                return text
            except Exception as error:
                elapsed = time.monotonic() - attempt_started
                _log_attempt_failure(model_name, current_key, error, elapsed)
                kind = _error_kind(error)
                if kind == "rate_limit":
                    tried_keys.add(current_key)
                    next_key = _next_key_after_limit(current_key, tried_keys, model_name, error)
                    if next_key:
                        current_key = next_key
                        transient_retries = 0
                        continue
                elif _error_code(error) == "TIMEOUT" and has_fallback:
                    # Модель зависла — повтор на ней же только съест остаток; к запасной.
                    if not api_key:
                        _cool_after_failure(current_key, model_name)
                    break
                elif kind == "transient" and transient_retries < len(_TRANSIENT_RETRY_DELAYS):
                    delay = _TRANSIENT_RETRY_DELAYS[transient_retries] + random.random() * 0.5
                    transient_retries += 1
                    if delay < model_deadline - time.monotonic():
                        await asyncio.sleep(delay)
                        continue
                if kind == "transient" and has_fallback and not api_key:
                    _cool_after_failure(current_key, model_name)
                break
        if time.monotonic() - started >= timeout:
            break
    return ""


async def stream_tokens(contents, *, system: str = "", model: Optional[str] = None,
                        max_tokens: int = 200, temperature: float = 0.85,
                        timeout: float = DEFAULT_TIMEOUT_S,
                        api_key: Optional[str] = None,
                        safety: bool = True, thinking: bool = True,
                        chain=None, audience: str = "master") -> AsyncIterator[str]:
    """Stream incrementally, retrying only before the first emitted token."""
    loop = asyncio.get_running_loop()
    import threading

    async def _one_stream(client, model_name: str, deadline: float):
        queue: asyncio.Queue = asyncio.Queue()

        def _enqueue(item) -> None:
            try:
                loop.call_soon_threadsafe(queue.put_nowait, item)
            except RuntimeError:
                pass

        def _produce() -> None:
            try:
                from google.genai import types as _t

                cfg_kwargs = dict(
                    system_instruction=system or None,
                    max_output_tokens=max_tokens,
                    temperature=temperature,
                )
                if safety:
                    cfg_kwargs["safety_settings"] = _safety_settings(audience)
                if thinking:
                    tc = _thinking(model_name)
                    if tc is not None:
                        cfg_kwargs["thinking_config"] = tc
                for chunk in client.models.generate_content_stream(
                    model=model_name,
                    contents=contents,
                    config=_t.GenerateContentConfig(**filter_params(model_name, cfg_kwargs)),
                ):
                    text = getattr(chunk, "text", None)
                    if text:
                        _enqueue(text)
            except Exception as error:
                _enqueue(error)
            finally:
                _enqueue(None)

        threading.Thread(target=_produce, daemon=True).start()
        while True:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise asyncio.TimeoutError()
            item = await asyncio.wait_for(queue.get(), timeout=remaining)
            if item is None:
                return
            if isinstance(item, Exception):
                raise item
            yield item

    models = _models_to_try(model, chain, contents)
    chain_path = _chain_path(chain, contents)
    started = time.monotonic()
    deadline = started + timeout
    first_key = _initial_key(api_key)
    if not first_key:
        log.error("[llm] no active Gemini API key")
        return

    for model_index, model_name in enumerate(models):
        preferred = first_key if model_index == 0 else (_initial_key(None) or first_key)
        current_key = preferred if api_key else _key_for_model(model_name, preferred)
        if not current_key:
            log.info("[llm] model=%s: все ключи на паузе — следующая модель", model_name)
            continue
        tried_keys: set[str] = set()
        transient_retries = 0
        has_fallback = model_index < len(models) - 1
        while current_key:
            remaining = timeout - (time.monotonic() - started)
            if remaining <= 0:
                return
            attempt_started = time.monotonic()
            emitted = False
            first_token_elapsed = None
            try:
                client = await asyncio.wait_for(
                    asyncio.to_thread(get_client, current_key), timeout=remaining,
                )
                remaining = timeout - (time.monotonic() - started)
                if remaining <= 0:
                    raise asyncio.TimeoutError()
                async for text in _one_stream(client, model_name, deadline):
                    emitted = True
                    if first_token_elapsed is None:
                        first_token_elapsed = time.monotonic() - started
                    yield text
                if not emitted:
                    raise RuntimeError("empty stream")
                log.info(
                    "[llm] success model=%s chain=%s first_token=%.2fs",
                    model_name, chain_path, first_token_elapsed,
                )
                return
            except Exception as error:
                elapsed = time.monotonic() - attempt_started
                _log_attempt_failure(model_name, current_key, error, elapsed)
                if emitted:
                    log.info(
                        "[llm] partial model=%s chain=%s first_token=%.2fs",
                        model_name, chain_path, first_token_elapsed,
                    )
                    log.warning("[llm] stream model=%s stopped after first token; returning partial text",
                                model_name)
                    return
                kind = _error_kind(error)
                if kind == "rate_limit":
                    tried_keys.add(current_key)
                    next_key = _next_key_after_limit(current_key, tried_keys, model_name, error)
                    if next_key:
                        current_key = next_key
                        transient_retries = 0
                        continue
                elif kind == "transient" and transient_retries < len(_TRANSIENT_RETRY_DELAYS):
                    delay = _TRANSIENT_RETRY_DELAYS[transient_retries] + random.random() * 0.5
                    transient_retries += 1
                    if delay < timeout - (time.monotonic() - started):
                        await asyncio.sleep(delay)
                        continue
                if kind == "transient" and has_fallback and not api_key:
                    _cool_after_failure(current_key, model_name)
                break

# ── Контракт LlmClassify (роутер, этап 2): (текст, каталог) → id | None ──

CLASSIFY_SYSTEM = (
    "Ты — классификатор команд голосового ассистента Сакуры в стиле J.A.R.V.I.S. "
    "Твоя задача — определить, хочет ли Мастер выполнить действие из каталога прямо сейчас, "
    "или это просто разговор/рассуждение.\n\n"
    "ЖЕСТКИЕ ПРАВИЛА ВЫБОРА:\n"
    "1. Выбирай действие ТОЛЬКО тогда, когда Мастер прямо или косвенно "
    "(в стиле Тони Старка / J.A.R.V.I.S., например: «тут слишком громко» → music.volume_down, "
    "«что там за окном?» → weather.now, «поставь чайник» → kettle.boil) "
    "просит ассистента выполнить действие или запросить данные ПРЯМО СЕЙЧАС.\n"
    "2. Возвращай ровно null, если Мастер:\n"
    "   - Просто делится мыслями, историями из прошлого или планами на будущее "
    "(«вчера слушал музыку», «надо будет почистить буфер», «не люблю такую погоду»).\n"
    "   - Задает философский, общий или разговорный вопрос Сакуре "
    "(«какую музыку ты любишь?», «как думаешь, стоит идти на пары?»).\n"
    "   - Использует отрицание («не выключай звук», «не открывай браузер», «не надо чайник»).\n"
    "   - Просит о том, чего нет в каталоге действий.\n\n"
    "ФОРМАТ ОТВЕТА:\n"
    "- Если действие без параметра (или параметр не указан): ответь ровно id действия одной строкой (например: music.next).\n"
    "- Если у действия в каталоге указан (param: ...) и в фразе Мастера есть значение этого параметра: "
    "ответь в формате: action_id | param_value (например: music.play_track | nirvana, kettle.heat | 85, files.open | README.md). "
    "Извлекай значение параметра в чистом нормализованном виде.\n"
    "- Если действие не требуется: ответь ровно null.\n"
    "- Никаких лишних слов, кавычек, markdown и пояснений. Строго одна строка."
)

_ID_RE = re.compile(r"[a-z0-9_.]+")


class ClassifyResult(tuple):
    """Результат классификации: (action_id, param).

    Поддерживает:
      - распаковку: action, param = res
      - атрибуты: res.action, res.param
      - обратную совместимость: res == "music.next" вернёт True!
    """

    def __new__(cls, action: str, param: Optional[str] = None):
        return super().__new__(cls, (action, param))

    @property
    def action(self) -> str:
        return self[0]

    @property
    def param(self) -> Optional[str]:
        return self[1]

    def __eq__(self, other):
        if isinstance(other, str):
            return self[0] == other
        return super().__eq__(other)

    def __ne__(self, other):
        return not (self == other)

    # Свой __eq__ обнуляет __hash__: без него результат нельзя положить
    # в set/dict. Хеш — по id действия, согласован с равенством строке.
    def __hash__(self):
        return hash(self[0])

    def __str__(self):
        if self[1] is not None:
            return f"{self[0]} | {self[1]}"
        return self[0]

    def __repr__(self):
        return f"ClassifyResult(action={self[0]!r}, param={self[1]!r})"


def _parse_classify_response(raw: str) -> tuple[Optional[str], Optional[str]]:
    """Разобрать ответ модели: action_id | param_value, JSON или голый id; null → (None, None)."""
    if not raw:
        return None, None
    text = raw.strip()
    if text.startswith("```"):
        lines = text.splitlines()
        if len(lines) >= 2 and lines[-1].strip().startswith("```"):
            text = "\n".join(lines[1:-1]).strip()
        else:
            text = text.strip("`").strip()
    text = text.strip('`"\'').strip()
    if not text:
        return None, None

    # Попытка разобрать JSON
    if text.startswith("{") and text.endswith("}"):
        try:
            import json
            data = json.loads(text)
            if isinstance(data, dict):
                raw_id = str(data.get("id") or "").strip().lower()
                raw_param = data.get("param")
                param_str = str(raw_param).strip() if raw_param is not None else None
                if param_str and param_str.lower() in ("null", "none"):
                    param_str = None
                if not raw_id or raw_id in ("null", "none", "-"):
                    return None, None
                if _ID_RE.fullmatch(raw_id):
                    return raw_id, param_str
                return None, None
        except Exception:
            pass

    # Разбор первой строки
    first_line = text.splitlines()[0].strip()
    # Формат action_id | param_value
    if "|" in first_line:
        parts = first_line.split("|", 1)
        raw_id = parts[0].strip().strip('`"\'').lower().rstrip(".,;:")
        raw_param = parts[1].strip().strip('`"\'')
        if raw_param.lower() in ("null", "none", ""):
            raw_param = None
        if not raw_id or raw_id in ("null", "none", "-"):
            return None, None
        if _ID_RE.fullmatch(raw_id):
            return raw_id, raw_param
        return None, None

    # Одиночный action_id
    first = first_line.strip().strip('`"\'').rstrip(".,;:").lower()
    if not first or first in ("null", "none", "-"):
        return None, None
    if _ID_RE.fullmatch(first):
        return first, None
    return None, None


async def generate_raw(model: str, contents, *, api_key: str | None = None,
                       timeout: float = 120.0, **cfg):
    """Один вызов одной модели без фолбэков, повторов и фильтра параметров:
    сырой ответ (function_calls, usage_metadata) или исключение API как есть.
    Для scripts/probe_gemma.py и вызовов browser agent (generate_agent)."""
    key = _initial_key(api_key)
    if not key:
        raise RuntimeError("нет активного ключа Gemini")
    client = get_client(key)
    from google.genai import types as _t
    # Асинхронный клиент: таймаут отменяет сам HTTP-запрос. Прежний
    # to_thread + wait_for оставлял поток висеть на сети — зависшие вызовы
    # (кадры Gemma) занимали пул, и очередь за ними тоже упиралась в 120 с
    # (замер решателя 02.11: p50 вызова = 120,0 с).
    return await asyncio.wait_for(
        client.aio.models.generate_content(
            model=model, contents=contents, config=_t.GenerateContentConfig(**cfg)),
        timeout=timeout)


# ── Вызовы browser agent: квоты Gemma и 429 (S2/S3) ──────────────────────

AGENT_TIMEOUT_S = 120.0                 # Gemma на API отвечает 15–75 с (probe_gemma)
AGENT_INLINE_WAIT_S = 5.0               # ждать квоту дольше — status:wait на desktop


class QuotaWait(Exception):
    """Квоты сейчас нет: повторить шаг через retry_after секунд."""

    def __init__(self, retry_after: float, model: str = ""):
        super().__init__(f"quota wait {retry_after:.0f}s ({model})")
        self.retry_after = max(1.0, float(retry_after))
        self.model = model


class ChainExhausted(Exception):
    """Все модели цепочки выведены; resume_at — когда первая вернётся;
    reason — quota (429/RPD) или unavailable (500/503 после повторов)."""

    def __init__(self, resume_at: float, reason: str = "quota"):
        super().__init__(f"chain exhausted ({reason}) until {resume_at:.0f}")
        self.resume_at = resume_at
        self.reason = reason


class AgentLLMError(Exception):
    """Модели цепочки не ответили (сбой, таймаут, отказ запроса)."""


@dataclass(frozen=True)
class AgentResponse:
    model: str
    response: object
    tokens: int


def _error_details(error: Exception) -> list:
    details = getattr(error, "details", None)
    err = details.get("error", details) if isinstance(details, dict) else None
    items = err.get("details") if isinstance(err, dict) else None
    return items if isinstance(items, list) else []


def retry_delay(error: Exception) -> float | None:
    """retryDelay из RetryInfo ответа 429 («37s»), иначе из текста ошибки."""
    for item in _error_details(error):
        if str(item.get("@type", "")).endswith("RetryInfo"):
            m = re.match(r"([\d.]+)s", str(item.get("retryDelay") or ""))
            if m:
                return float(m.group(1))
    m = re.search(r"retry in ([\d.]+)\s*s", str(error), re.IGNORECASE)
    return float(m.group(1)) if m else None


def _server_error(error: Exception) -> bool:
    """500/503 (INTERNAL/UNAVAILABLE) — сбой бэкенда, не отказ запроса."""
    return _error_code(error).upper() in ("500", "503", "INTERNAL", "UNAVAILABLE")


def quota_ids(error: Exception) -> list[str]:
    """quotaId из QuotaFailure ответа 429 (имена метрик, не секреты)."""
    out = []
    for item in _error_details(error):
        if str(item.get("@type", "")).endswith("QuotaFailure"):
            out += [str(v.get("quotaId") or v.get("quotaMetric") or "")[:80]
                    for v in item.get("violations") or []]
    return [q for q in out if q]


def quota_per_day(error: Exception) -> bool:
    """429 из-за суточной квоты (QuotaFailure: quotaId …PerDay…)."""
    for item in _error_details(error):
        if str(item.get("@type", "")).endswith("QuotaFailure"):
            for v in item.get("violations") or []:
                if "perday" in f"{v.get('quotaId', '')}{v.get('quotaMetric', '')}".lower():
                    return True
    return False


async def generate_agent(contents, *, chain, system: str = "", tools=None,
                         tool_config=None, response_schema=None,
                         response_mime_type: str | None = None,
                         max_tokens: int = 2048, temperature: float | None = None,
                         thinking_level: str | None = None,
                         limiter=None, timeout: float = AGENT_TIMEOUT_S,
                         inline_wait: float = AGENT_INLINE_WAIT_S,
                         sleep=asyncio.sleep, on_event=None,
                         fast_failover: bool = False) -> AgentResponse:
    """Вызов browser agent: модели цепочки по порядку через лимитер квот.

    Квоты нет дольше inline_wait — QuotaWait (desktop получит status:wait).
    429 — модель блокируется на retry delay (иначе 4→8→16→32 с), до 5
    повторов, затем следующая модель. 500/503 — до 3 повторов через 5→10→20 с,
    затем так же следующая модель; fast_failover — при 500/503, таймауте или
    паузе модели сразу следующая модель, ждать только на последней (решатель:
    замер 02.11 — ~60 ошибок 500/503 за прогон, паузы ~500 с). Все выведены — ChainExhausted (пауза
    задачи). Прочие ошибки — AgentLLMError. thinking_level — для Gemma
    ThinkingConfig(thinking_level=…); без него мысли по умолчанию модели.
    Параметры — через filter_params (S4). on_event(kind, **data) — метрики:
    "call" (model, latency, ok, code) на каждую попытку, "wait" (seconds) на
    каждое ожидание лимитера внутри вызова."""
    def emit(kind: str, **data) -> None:
        if on_event is not None:
            try:
                on_event(kind, **data)
            except Exception as error:  # noqa: BLE001 — метрики не ломают вызов
                log.debug("[agent-llm] метрика: %s", type(error).__name__)

    from sakura_core import rate_limiter
    limiter = limiter or rate_limiter.get()
    models = tuple(dict.fromkeys(m for m in chain if m))
    if not models:
        raise AgentLLMError("пустая цепочка моделей")
    cfg = {"system_instruction": system or None, "max_output_tokens": max_tokens,
           "temperature": temperature, "tools": tools, "tool_config": tool_config,
           "response_schema": response_schema,
           "response_mime_type": response_mime_type}
    if tools is not None or thinking_level:
        from google.genai import types as _t
        if tools is not None:
            cfg["automatic_function_calling"] = _t.AutomaticFunctionCallingConfig(disable=True)
        if thinking_level:
            cfg["thinking_config"] = _t.ThinkingConfig(thinking_level=thinking_level)
    last_error: Exception | None = None
    for pos, model in enumerate(models):
        has_next = pos + 1 < len(models)
        while True:
            if limiter.exhausted_until(model) is not None:
                break                                   # следующая модель
            # Квота проверяется заново после каждого сна: параллельные вызовы
            # (решатель) не должны забрать один и тот же токен.
            wait = limiter.wait(model)
            if fast_failover and has_next and wait > 0:
                break                                   # не ждать — следующая модель
            if wait > inline_wait:
                raise QuotaWait(wait, model)
            if wait > 0:
                emit("wait", seconds=wait)
                await sleep(wait)
                continue
            reserved = limiter.take(model) or 0.0
            params = {k: v for k, v in filter_params(model, cfg).items() if v is not None}
            started = time.monotonic()
            try:
                response = await generate_raw(model, contents, timeout=timeout, **params)
            except Exception as error:  # noqa: BLE001 — разбор кода ошибки API ниже
                last_error = error
                limiter.on_tokens(model, 0, reserved)       # не дошёл — резерв назад
                kind = _error_kind(error)
                log.info("[agent-llm] model=%s code=%s elapsed=%.1fs", model,
                         _error_code(error), time.monotonic() - started)
                emit("call", model=model, latency=time.monotonic() - started, ok=False,
                     code="429" if kind == "rate_limit" else _error_code(error))
                if kind == "rate_limit":
                    log.info("[agent-llm] 429 model=%s quota=%s retry_delay=%s", model,
                             ",".join(quota_ids(error)) or "?", retry_delay(error))
                    limiter.on_429(model, retry_delay(error), quota_per_day(error))
                    continue                            # wait()/exhausted решат
                if _server_error(error):
                    limiter.on_server_error(model)
                    if fast_failover and has_next:
                        break                           # сразу следующая модель
                    continue                            # 5→10→20 с, затем модель выведена
                break
            limiter.on_success(model)
            emit("call", model=model, latency=time.monotonic() - started, ok=True, code="")
            usage = getattr(response, "usage_metadata", None)
            tokens = int(getattr(usage, "total_token_count", 0) or 0)
            limiter.on_tokens(model, tokens or int(reserved), reserved)
            log.info("[agent-llm] success model=%s elapsed=%.1fs tokens=%d", model,
                     time.monotonic() - started, tokens)
            return AgentResponse(model, response, tokens)
    resumes = [(t, m) for m in models if (t := limiter.exhausted_until(m)) is not None]
    if len(resumes) == len(models):
        at, first = min(resumes)
        raise ChainExhausted(at, limiter.exhausted_reason(first))
    code = _error_code(last_error) if last_error else "none"
    raise AgentLLMError(f"модели не ответили: {code}")


async def classify_action(text: str, catalog: str, *, model: Optional[str] = None,
                          timeout: float = DEFAULT_TIMEOUT_S,
                          api_key: Optional[str] = None) -> Optional[ClassifyResult]:
    """Клей между generate() (сырой текст) и LlmClassify (id действия и параметр).

    Промпт-классификатор: каталог из реестра → ответ-идентификатор с параметром; «null»,
    проза и пустой ответ → None. Проверку «id известен реестру» НЕ делает —
    это ответственность роутера (sakura_core/router.py): неизвестный id
    считается разговором.
    """
    if not (text or "").strip() or not (catalog or "").strip():
        return None
    raw = await generate(
        text,
        system=f"{CLASSIFY_SYSTEM}\n\nКаталог действий:\n{catalog}",
        model=model, max_tokens=48, temperature=0.0, timeout=timeout,
        api_key=api_key,
    )
    action_id, param_val = _parse_classify_response(raw)
    if not action_id:
        return None
    return ClassifyResult(action_id, param_val)


# ── Структурированный разбор намерений (роутер, этап 3) ──────────────────

INTENT_SYSTEM = (
    "Ты — разбор намерений голосового ассистента Сакуры (стиль J.A.R.V.I.S.). "
    "По фразе Мастера и контексту определи, какие действия из каталога нужно "
    "выполнить ПРЯМО СЕЙЧАС и есть ли во фразе разговорная часть.\n\n"
    "ПРАВИЛА:\n"
    "1. Действие выбирай, только если Мастер прямо или косвенно просит его сейчас "
    "(«тут слишком громко» → music.volume_down, «что там за окном?» → weather.now, "
    "«что-то прохладно» при разговоре о чае → kettle.boil).\n"
    "2. Несколько просьб в одной фразе — несколько действий в порядке произнесения "
    "(«включи музыку и сделай погромче» → два действия).\n"
    "3. Действий НЕТ, если Мастер рассказывает о прошлом или планах, жалуется, "
    "рассуждает, задаёт вопрос самой Сакуре, цитирует чужие слова или использует "
    "отрицание («не выключай», «не надо чайник»).\n"
    "4. Отложенное время («через час», «в 23:00») для выключения, перезагрузки и сна "
    "— НЕ действие: верни пустой список и chat=true.\n"
    "5. chat=true, если кроме команд есть реплика, на которую нужно ответить словами "
    "(рассказ, вопрос, просьба поговорить), или команд нет вовсе.\n"
    "6. Параметр бери из фразы в нормализованном виде (число, название, город и день "
    "для погоды: «Санкт-Петербург завтра»). Нет параметра — null.\n"
    "7. Учитывай контекст: что играет, какое окно активно, о чём шла речь.\n\n"
    "ФОРМАТ ОТВЕТА — строго одна строка JSON без пояснений и markdown:\n"
    '{"actions":[{"id":"music.volume_down","param":null}],"chat":false}\n'
    "Команд нет: {\"actions\":[],\"chat\":true}"
)


def _intent_context_block(context: Optional[dict]) -> str:
    """Контекст хода → строки для промпта разбора (только непустое)."""
    if not context:
        return ""
    lines = []
    ctx = context.get("context")
    if ctx:
        lines.append(f"- состояние: {ctx}")
    if context.get("window"):
        lines.append(f"- активное окно: {str(context['window'])[:80]}")
    if context.get("track"):
        lines.append(f"- сейчас играет: {str(context['track'])[:80]}")
    if context.get("pending"):
        lines.append(f"- Сакура ждёт ответа на вопрос: {str(context['pending'])[:120]}")
    for item in (context.get("recent") or [])[-4:]:
        lines.append(f"- {str(item)[:160]}")
    return ("\n\nКонтекст:\n" + "\n".join(lines)) if lines else ""


def _parse_intent_response(raw) -> IntentParse:
    """Ответ модели → IntentParse.

    Принимает JSON-план, а также прежние формы классификатора («id | param»,
    голый id, «null») — старые модели и заглушки отвечают ими. Пустой или
    нестроковый ответ — LlmUnavailable: это сбой, а не вердикт «разговор».
    """
    if not isinstance(raw, str) or not raw.strip():
        raise LlmUnavailable("пустой ответ модели")
    text = raw.strip()
    if text.startswith("```"):
        text = re.sub(r"^```[a-zA-Z]*\s*|\s*```$", "", text).strip()
    start, end = text.find("{"), text.rfind("}")
    if start != -1 and end > start:
        try:
            data = json.loads(text[start:end + 1])
        except ValueError:
            data = None
        if isinstance(data, dict):
            if "actions" not in data and data.get("id"):
                data = {"actions": [data], "chat": False}      # прежний JSON {"id","param"}
            actions = []
            for item in data.get("actions") or []:
                if isinstance(item, str):
                    item = {"id": item}
                if not isinstance(item, dict):
                    continue
                action_id = str(item.get("id") or "").strip().lower()
                if not _ID_RE.fullmatch(action_id) or action_id in ("null", "none"):
                    continue
                param = item.get("param")
                param = None if param is None else str(param).strip()
                if param is not None and param.lower() in ("", "null", "none"):
                    param = None
                actions.append((action_id, param))
            chat = bool(data.get("chat")) or not actions
            return IntentParse(actions=tuple(actions[:4]), chat=chat)
    action_id, param = _parse_classify_response(text)
    if action_id:
        return IntentParse(actions=((action_id, param),), chat=False)
    return IntentParse(actions=(), chat=True)


async def parse_intent(text: str, catalog: str, *, context: Optional[dict] = None,
                       model: Optional[str] = None, timeout: float = 3.0,
                       api_key: Optional[str] = None) -> IntentParse:
    """Структурированный разбор намерений: план действий + флаг разговора.

    Любой сбой (сеть, ключи, таймаут, пустой ответ) — LlmUnavailable.
    Проверку id и параметров по реестру делает роутер.
    """
    try:
        raw = await asyncio.wait_for(
            generate(
                text,
                system=(f"{INTENT_SYSTEM}\n\nКаталог действий:\n{catalog}"
                        f"{_intent_context_block(context)}"),
                model=model, max_tokens=160, temperature=0.0, timeout=timeout,
                api_key=api_key,
            ),
            timeout=timeout + 0.5,
        )
    except LlmUnavailable:
        raise
    except Exception as e:
        raise LlmUnavailable(f"{type(e).__name__}: {e}") from e
    return _parse_intent_response(raw)


def make_llm_parse(*, model: Optional[str] = None, timeout: float = 3.0,
                   api_key: Optional[str] = None):
    """Замыкание-разбор для Router(llm_parse=...): (текст, каталог, контекст).

    В отличие от make_llm_classify ошибки НЕ глотаются: роутер по
    LlmUnavailable переходит на локальный разбор, а не считает фразу болтовнёй.
    """
    async def parse(text: str, catalog: str, context: Optional[dict] = None) -> IntentParse:
        return await parse_intent(text, catalog, context=context, model=model,
                                  timeout=timeout, api_key=api_key)

    return parse


def make_llm_classify(*, model: Optional[str] = None,
                      timeout: float = DEFAULT_TIMEOUT_S,
                      api_key: Optional[str] = None):
    """Собрать async LlmClassify для Router(llm_classify=...).

    Ошибки (сеть, ключи) не поднимаются: классификация — последний шаг
    перед разговором, провал означает «это разговор».
    """
    async def classify(text: str, catalog: str) -> Optional[ClassifyResult]:
        try:
            return await classify_action(text, catalog, model=model,
                                         timeout=timeout, api_key=api_key)
        except Exception as e:
            log.warning(f"[llm] classify провалился: {type(e).__name__}: {e}")
            return None
    return classify


# ── Утилиты ──────────────────────────────────────────────────────────────

def _strip_tone(text: str) -> str:
    """Убирает теги [ТОН: …] (общая функция tts_server)."""
    from modules.tts_server import strip_tone as _st
    return _st(text)[1]


def clean_reply(text: str) -> str:
    if not text:
        return ""
    import re as _re
    text = _re.sub(r'\{.*?\}', '', text, flags=_re.DOTALL).strip()
    bad_keys = ('"thought"', '"action"', '"action_input"', 'dalle.text2im', '"text":', '"role":')
    lines = [
        l for l in text.split('\n')
        if not any(k in l for k in bad_keys)
        and not (l.strip().startswith('"') and l.strip().endswith('",'))
        and l.strip() not in (',', '"')
    ]
    return '\n'.join(lines).strip()


# ── Сборка contents ──────────────────────────────────────────────────────

def _build_contents(
    user_message: str, extra_system: str = "", history_limit: int = 60
) -> list:
    from google.genai import types as _t
    from memory.memory import get_history
    history = get_history()
    history = history[-history_limit:] if history_limit > 0 else []
    contents = [
        _t.Content(role=m["role"], parts=[_t.Part(text=m["parts"][0])])
        for m in history
    ]
    msg = f"{extra_system}\n\n{user_message}" if extra_system else user_message
    contents.append(_t.Content(role="user", parts=[_t.Part(text=msg)]))
    return contents


def _build_guest_contents(user_id: int, user_message: str) -> list:
    """История конкретного гостя/Химари."""
    from google.genai import types as _t
    from modules.users import get_guest_history
    history = get_guest_history(user_id)[-20:]
    contents = []
    for msg in history:
        gemini_role = "user" if msg["role"] == "user" else "model"
        contents.append(_t.Content(
            role  = gemini_role,
            parts = [_t.Part(text=msg["text"])]
        ))
    contents.append(_t.Content(role="user", parts=[_t.Part(text=user_message)]))
    return contents


# ── Основные LLM-функции ────────────────────────────────────────────────

_LEN_TOKENS = {"short": 120, "medium": 200, "long": 800}
_LEN_HINT = {
    "short":  "Ответь коротко, 1-2 предложения. Идёт живой разговор — без монологов.",
    "medium": "Ответь компактно, 2-3 предложения, без лишних рассуждений.",
    "long":   "Мастер просит подробно — разверни ответ полноценно.",
}


VOICE_LLM_TIMEOUT_S = 8.0
VOICE_SEARCH_TIMEOUT_S = 14.0
VOICE_FACTS_MAX = 2500
VOICE_EMPTY_REPLY = "Не успела ответить — повтори, пожалуйста."


SEARCH_NOT_FOUND = (
    "\n\nПоиск в интернете подходящих данных не дал. Если для ответа нужны "
    "актуальные или точные данные — честно скажи Мастеру, что не нашла, и не "
    "выдумывай факты; общеизвестное можно сказать, но не выдавай за найденное."
)


async def _web_search(user_message: str, channel: str, *, hint: str = ""):
    """Поиск через единый конвейер с разговором для контекста; сбой — пусто."""
    from sakura_core.search import Evidence, run
    try:
        from sakura_core.vision.ask import recent_dialogue
        dialogue = recent_dialogue()
    except Exception:
        dialogue = ""
    try:
        return await run(user_message, channel=channel, hint=hint, dialogue=dialogue)
    except Exception as e:
        log.warning(f"[search] конвейер: {type(e).__name__}: {e}")
        return Evidence()


def _vision_followup(user_message: str) -> tuple[str | None, str]:
    """(запрос поиска, контекст) для реплики после вопроса по экрану
    (sakura_core/vision/followup.py); сбой — как будто экрана не было."""
    try:
        from sakura_core.vision.followup import plan
        return plan(user_message)
    except Exception as e:
        log.debug(f"[llm] vision followup: {type(e).__name__}: {e}")
        return None, ""


async def ask_gemini(
    user_message: str, save_history: bool = True, history_limit: int = 60,
    chain=None, *, extra_system: str = "", search: bool | None = None,
    channel: str | None = None,
) -> str:
    """Ответ Сакуры с характером, историей и (при необходимости) поиском.

    extra_system — дополнительный контекст хода (например, что на экране
    Мастера: sakura_core/vision/ask.py); search=None — поиск по
    needs_search(user_message), False — не искать (вызывающий уже нашёл и
    передал факты в extra_system)."""
    from config import MAIN_MODEL, get_active_key, mark_key_used

    _t_mono = __import__("time").monotonic
    _t0 = _t_mono()

    full_system = await _build_system(query="", channel=channel)
    if extra_system:
        full_system += "\n\n" + extra_system
    _t_build = _t_mono() - _t0

    try:
        from modules.steam_integration import search_game
        game_hit = await asyncio.to_thread(search_game, user_message)
        if game_hit:
            from modules import steam_integration as _steam_mod
            current_game = _steam_mod._current_game
            if not current_game or game_hit.get('appid') != current_game.get('appid'):
                h = game_hit.get('playtime_forever', 0) // 60
                full_system += (
                    f"\n\nИГРА ИЗ БИБЛИОТЕКИ МАСТЕРА: {game_hit['name']} "
                    f"(наиграно {h}ч) — Мастер спрашивает про эту игру."
                )
    except Exception as e:
        log.debug(f"[llm] ask_gemini: {type(e).__name__}: {e}")

    search_facts = None
    search_sources = []
    from modules.web_search import (
        needs_search, facts_prompt, format_sources,
        wants_sources, is_pure_sources_request,
        get_latest_sources, set_latest_sources,
    )

    if is_pure_sources_request(user_message):
        recent_sources = get_latest_sources()
        if recent_sources:
            reply = "Вот источники:\n" + "\n".join(f"• {u}" for u in recent_sources[:3])
        else:
            reply = "Мастер, я отвечала по памяти, без поиска в интернете, поэтому ссылок нет."
        if save_history:
            from memory.memory import add_to_history
            add_to_history("user", user_message)
            add_to_history("model", reply)
        return reply

    # Продолжение разговора после вопроса по экрану: поиск с темой экрана.
    vf_query, vf_context = _vision_followup(user_message) if search is not False else (None, "")
    if vf_context:
        full_system += "\n\n" + vf_context
    if search is not False and (vf_query or needs_search(user_message)):
        # Единый конвейер (sakura_core/search). Не нашли — честно, без «ответа
        # из памяти модели» под видом интернета.
        ev = await _web_search(user_message, "text", hint=vf_query or "")
        if ev.ok:
            search_facts = ev.facts
            search_sources = ev.sources
            set_latest_sources(search_sources)
        else:
            full_system += SEARCH_NOT_FOUND

    url_ctx = await maybe_read_url(user_message)
    if url_ctx:
        full_system += f"\n\n{url_ctx}"

    if search_facts:
        full_system += facts_prompt(search_facts)
    _t_ctx = _t_mono() - _t0

    key = get_active_key()
    _t_prep = _t_ctx
    _t_llm = None
    if not key:
        return "Мастер, все API ключи исчерпаны на сегодня."
    contents = _build_contents(user_message, history_limit=history_limit)
    try:
        _t_prep = _t_mono() - _t0
        request_chain = chain or _chain_for_request(history_limit, save_history)
        response = await generate(
            contents, system=full_system, model=MAIN_MODEL, chain=request_chain,
        )
        _t_llm = _t_mono() - _t0
        reply    = clean_reply(response)
        mark_key_used(key)
    except Exception as e:
        log.error(f"[ask_gemini] {e}")
        reply = ""

    if search_sources and reply and wants_sources(user_message):
        reply += format_sources(search_sources, limit=3)
    _t_total = _t_mono() - _t0
    _llm_s    = (_t_total - _t_prep) if _t_llm is None else (_t_llm - _t_prep)
    _proc_s   = (_t_total - _t_prep) if _t_llm is None else (_t_total - _t_llm)
    log.info(
        f"[ask_gemini time] всего={_t_total:.1f}с | сборка={_t_build:.2f}с | "
        f"контекст={_t_ctx - _t_build:.2f}с | LLM={_llm_s:.1f}с | "
        f"обработка={_proc_s:.2f}с | system={len(full_system)}симв | history={len(contents)}"
    )

    if not reply or not _strip_tone(reply).strip():
        reply = "Мастер, что-то мешает мне ответить. Попробуй ещё раз."

    if save_history:
        from modules.intimacy_mode import is_active as _im_active, is_intimate_content
        is_intimate = (
            _im_active()
            or (channel and _im_active(channel))
            or is_intimate_content(user_message)
            or is_intimate_content(reply)
        )
        if not is_intimate:
            from memory.memory import add_to_history
            add_to_history("user", user_message)
            add_to_history("model", reply)
            # Ленивый импорт: extract_and_remember → ask_gemini (цикл через функции)
            from sakura_core.memory_tasks import extract_and_remember
            spawn(extract_and_remember(user_message, reply), name="remember-from-chat")
            from memory.memory import should_summarize
            from sakura_core.memory_tasks import summarize_session
            if should_summarize():
                spawn(summarize_session(), name="summarize-session")
            from modules.context import get_full_context
            ctx_snap = get_full_context()
            from modules.timeline import extract_and_save_from_dialogue
            spawn(asyncio.to_thread(
                extract_and_save_from_dialogue, user_message, reply, ctx_snap
            ), name="save-dialogue-timeline")
            from modules.mood_vector import mark_interaction, auto_detect_mood_from_reply
            mark_interaction()
            spawn(asyncio.to_thread(
                auto_detect_mood_from_reply, reply, user_message
            ), name="update-mood-from-reply")
            try:
                from modules.self_correction import process_conversation
                spawn(asyncio.to_thread(
                    process_conversation, user_message, reply
                ), name="self-correction")
            except Exception as e:
                log.debug(f"[llm] ask_gemini: {type(e).__name__}: {e}")
            try:
                from modules.secret_diary import write_entry as diary_write
                spawn(diary_write(
                    f"Мастер: {user_message[:200]}\nСакура: {reply[:200] if reply else ''}",
                    "neutral"
                ), name="write-diary-entry")
            except Exception as e:
                log.debug(f"[llm] ask_gemini: {type(e).__name__}: {e}")
        else:
            log.info("[llm] memory skipped for intimate conversation turn")

    return reply


async def _handle_gemini_error(
    e: Exception, user_message: str, save_history: bool, history_limit: int = 60
) -> str:
    log.error("[llm] request failed after retries: %s", _error_code(e))
    return ""


async def ask_gemini_voice(
    user_message : str,
    websocket    = None,
    device_id    : str = "laptop",
    active_window: str | None = None,
    length       : str = "short",
    gate         = None,
    received_at  : float | None = None,
    channel      : str = "voice",
) -> tuple[str, str]:
    """Голосовой ответ с истинным стримингом LLM→TTS.

    gate — VoiceGate (п.2): шлюз «классификатор ∥ стрим»; без него
    (None) поведение прежнее — предложения уходят в TTS сразу.
    received_at — time.monotonic() приёма голоса (п.5): бюджеты
    «первый звук»/«ответ готов» считаются от приёма, а не от старта
    ответа (параллельная классификация входит в замер).
    """
    from config import MAIN_MODEL, FALLBACK_MODEL, get_active_key, mark_key_used
    from memory.memory import add_to_history

    key = get_active_key()
    if not key:
        if websocket:
            try:
                from sakura_core.voice_turns import send_reply
                await send_reply(websocket, device_id, "Все ключи исчерпаны.", kind="error")
                from modules.tts_server import _send_end
                await _send_end(websocket, device_id)
            except Exception as e:
                log.debug(f"[llm] ask_gemini_voice: {type(e).__name__}: {e}")
        return ("Все ключи исчерпаны.", "neutral")

    _t_build = __import__("time").monotonic()
    full_system = await _build_system(query=user_message,
                                      profile=config.VOICE_PROMPT_PROFILE,
                                      channel=channel)
    len_hint = _LEN_HINT.get(length, "")
    if len_hint:
        full_system = f"{full_system}\n\n{len_hint}"
    max_tok = (config.VOICE_MAX_TOKENS if config.VOICE_MAX_TOKENS_OVERRIDE
               else _LEN_TOKENS.get(length, config.VOICE_MAX_TOKENS))
    log.info(f"[voice] len={length} → hint={'да' if len_hint else 'нет'}, max_tokens={max_tok}")
    _t_now = __import__("time").monotonic()
    _from_recv = (f" (+{_t_now-received_at:.2f}с от приёма)"
                  if received_at is not None else "")
    log.info(f"[voice] _build_system за {_t_now-_t_build:.2f}с{_from_recv}")

    contents  = _build_contents(
        user_message, history_limit=config.VOICE_HISTORY_LIMIT
    )
    emotion   = "neutral"
    full_text = ""

    from modules.web_search import needs_search, facts_prompt
    # Продолжение разговора после вопроса по экрану: поиск с темой экрана.
    vf_query, vf_context = _vision_followup(user_message)
    if vf_context:
        full_system += "\n\n" + vf_context
    search_needed = bool(vf_query) or needs_search(user_message)
    search_facts  = None
    if search_needed:
        ev = await _web_search(user_message, "voice", hint=vf_query or "")
        search_facts = ev.facts if ev.ok else None
        if ev.ok and ev.sources:
            from modules.web_search import set_latest_sources
            set_latest_sources(ev.sources)

    # С фактами из поиска промпт длиннее: потолок ответа 14 с вместо 8 (ход
    # целиком всё равно под сторожем TURN_TIMEOUT_S), факты для голоса — короче.
    llm_timeout = VOICE_SEARCH_TIMEOUT_S if search_facts else VOICE_LLM_TIMEOUT_S
    if search_facts:
        full_system += facts_prompt(search_facts[:VOICE_FACTS_MAX])
    elif search_needed:
        full_system += SEARCH_NOT_FOUND

    try:
        if websocket:
            from adapters.voice import stream_llm_to_tts
            from modules.state_arbiter import get_current_emotion
            full_text, emotion = await stream_llm_to_tts(
                contents    = contents,
                system      = full_system,
                websocket   = websocket,
                device_id   = device_id,
                model       = MAIN_MODEL,
                max_tokens  = max_tok,
                temperature = 0.85,
                api_key     = key,
                emotion     = get_current_emotion(),
                timeout     = llm_timeout,
                chain       = config.VOICE_MODEL_CHAIN,
                gate        = gate,
                received_at = received_at,
            )
        else:
            response  = await generate(contents, system=full_system, model=MAIN_MODEL,
                                       max_tokens=max_tok, temperature=0.85,
                                       timeout=llm_timeout, chain=config.VOICE_MODEL_CHAIN)
            full_text = response
            mark_key_used(key)
    except Exception as e:
        log.error(f"[Voice] {e}")
        try:
            if websocket:
                from adapters.voice import stream_llm_to_tts
                from modules.state_arbiter import get_current_emotion
                full_text, emotion = await stream_llm_to_tts(
                    contents, full_system, websocket, device_id,
                    model=FALLBACK_MODEL, max_tokens=max_tok,
                    api_key=key, emotion=get_current_emotion(), timeout=8.0,
                    chain=config.VOICE_MODEL_CHAIN, gate=gate,
                    received_at=received_at,
                )
            else:
                r = await generate(contents, system=full_system, model=FALLBACK_MODEL,
                                   max_tokens=max_tok, timeout=8.0,
                                   chain=config.VOICE_MODEL_CHAIN)
                full_text = r
                mark_key_used(key)
        except Exception as e2:
            log.error(f"[Voice fallback] {e2}")
            if websocket:
                try:
                    from modules.tts_server import _send_end
                    await _send_end(websocket, device_id)
                except Exception as e:
                    log.debug(f"[llm] ask_gemini_voice: {type(e).__name__}: {e}")

    clean_text = clean_reply(full_text.strip()) if full_text else ""

    if not clean_text and websocket:
        # Модель не успела: не молчать — сказать прямо (раньше ход кончался тишиной).
        log.warning("[голос] пустой ответ модели — говорю, что не успела")
        try:
            from modules.tts_server import stream_tts_to_device
            await stream_tts_to_device(VOICE_EMPTY_REPLY, websocket, device_id,
                                       literal=True, reply_kind="error")
        except Exception as e:
            log.debug(f"[llm] пустой ответ: {type(e).__name__}: {e}")

    if clean_text and websocket:
        # Текст ответа в окно клиента — до tts_end хода (его шлёт
        # handle_voice_command в finally), с turn_id хода.
        from sakura_core.voice_turns import send_reply
        await send_reply(websocket, device_id, clean_text)
    if clean_text:
        from sakura_core.chat_hooks import note_spoken
        note_spoken(clean_text)

    from modules.intimacy_mode import is_active as _im_active, is_intimate_content, redact as _im_redact
    is_intimate = (
        _im_active()
        or (channel and _im_active(channel))
        or is_intimate_content(user_message)
        or is_intimate_content(clean_text)
    )
    if not is_intimate:
        add_to_history("user",  user_message)
        add_to_history("model", clean_text)
    else:
        log.info("[voice] history skipped for intimate turn")
    log.info(f"[{channel}] ответ: {_im_redact(clean_text, channel)}")

    try:
        from modules.mood_broadcast import broadcast_mood_after_reply
        from modules.state_arbiter import get_current_emotion
        spawn(broadcast_mood_after_reply(
            clean_text, user_message, emotion
        ), name="voice-mood-broadcast")
    except Exception as e:
        log.debug(f"[llm] ask_gemini_voice: {type(e).__name__}: {e}")

    return (clean_text, emotion)


# ── Веб-контекст ─────────────────────────────────────────────────────────

async def maybe_fetch_web(text: str) -> str:
    try:
        from modules.web_search import smart_search
        return await smart_search(text)
    except Exception:
        return ""


async def maybe_read_url(text: str) -> str:
    import re as _re
    urls = _re.findall(r'https?://[^\s]+', text)
    if not urls:
        return ""
    try:
        from modules.url_reader import process_url
        content = await process_url(urls[0])
        return f"СОДЕРЖИМОЕ ССЫЛКИ ({urls[0]}):\n{content}"
    except Exception as e:
        log.error(f"URL reader error: {e}")
        return ""


async def ask_gemini_as_guest(
    user_id      : int,
    user_message : str,
    user_name    : str,
    role         : str,
) -> str:
    from config import MAIN_MODEL, get_active_key, mark_key_used
    from modules.users import add_guest_message

    key = get_active_key()
    if not key:
        return "Извини, сейчас недоступна."

    try:
        full_system = _build_guest_system(role, user_name, user_id)
        contents    = _build_guest_contents(user_id, user_message)

        response = await generate(
            contents, system=full_system, model=MAIN_MODEL,
            chain=config.MODEL_CHAIN, audience="guest",
        )
        reply    = clean_reply(response)
        mark_key_used(key)

        if not reply:
            reply = "Не смогла ответить. Попробуй ещё раз."

        add_guest_message(user_id, "user",  user_message, name=user_name)
        add_guest_message(user_id, "model", reply)

        return reply

    except asyncio.TimeoutError:
        return "Не отвечаю. Попробуй позже."
    except Exception as e:
        log.error(f"ask_gemini_as_guest error: {e}")
        return "Что-то пошло не так."
