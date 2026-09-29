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
import logging
import random
import re
import time
from typing import AsyncIterator, Optional

import config
from sakura_core.tasks import spawn

log = logging.getLogger("sakura.llm")

_clients: dict[str, object] = {}
_created = 0  # счётчик созданий клиента — тест этапа 4 следит, что он не растёт

DEFAULT_TIMEOUT_S = 20.0
_TRANSIENT_RETRY_DELAYS = (1.0, 2.0)

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


def _chain_for_request(history_limit: int, save_history: bool):
    if history_limit == config.VOICE_HISTORY_LIMIT:
        return config.VOICE_MODEL_CHAIN
    if save_history:
        return config.MODEL_CHAIN
    return config.BACKGROUND_MODEL_CHAIN


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


def _next_key_after_limit(api_key: str, tried: set[str]) -> Optional[str]:
    try:
        config.mark_key_rate_limited(api_key)
    except Exception as error:
        log.debug("[llm] could not mark rate-limited key: %s", type(error).__name__)
    try:
        next_key = config.get_active_key()
    except Exception:
        next_key = None
    if next_key and next_key not in tried:
        return next_key
    return next((key for key in config.GEMINI_KEYS if key and key not in tried), None)


def _log_attempt_failure(model: str, api_key: str, error: Exception,
                         elapsed: float) -> None:
    code = _error_code(error)
    log.info("[llm] attempt failed model=%s key=%s code=%s elapsed=%.2fs",
             model, _key_number(api_key), code, elapsed)
    if _error_kind(error) == "request":
        log.warning("[llm] model=%s rejected request with code=%s", model, code)


def _initial_key(api_key: Optional[str]) -> Optional[str]:
    if api_key:
        return api_key
    try:
        return config.get_active_key()
    except Exception:
        return None


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
                   chain=None) -> str:
    """Generate with bounded retries and a single request-wide time budget."""
    models = _models_to_try(model, chain, contents)
    started = time.monotonic()
    first_key = _initial_key(api_key)
    if not first_key:
        log.error("[llm] no active Gemini API key")
        return ""

    for model_index, model_name in enumerate(models):
        current_key = first_key if model_index == 0 else (_initial_key(None) or first_key)
        tried_keys: set[str] = set()
        transient_retries = 0
        while current_key:
            remaining = timeout - (time.monotonic() - started)
            if remaining <= 0:
                break
            attempt_started = time.monotonic()
            try:
                client = await asyncio.wait_for(
                    asyncio.to_thread(get_client, current_key), timeout=remaining,
                )
                remaining = timeout - (time.monotonic() - started)
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
                        cfg_kwargs["safety_settings"] = _no_safety()
                    if thinking:
                        tc = _thinking(m)
                        if tc is not None:
                            cfg_kwargs["thinking_config"] = tc
                    if response_mime_type:
                        cfg_kwargs["response_mime_type"] = response_mime_type
                    return c.models.generate_content(
                        model=m,
                        contents=contents,
                        config=_t.GenerateContentConfig(**cfg_kwargs),
                    )

                response = await asyncio.wait_for(asyncio.to_thread(
                    _invoke,
                ), timeout=remaining)
                return (response.text or "").strip()
            except Exception as error:
                elapsed = time.monotonic() - attempt_started
                _log_attempt_failure(model_name, current_key, error, elapsed)
                kind = _error_kind(error)
                if kind == "rate_limit":
                    tried_keys.add(current_key)
                    next_key = _next_key_after_limit(current_key, tried_keys)
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
                break
        if time.monotonic() - started >= timeout:
            break
    return ""


async def stream_tokens(contents, *, system: str = "", model: Optional[str] = None,
                        max_tokens: int = 200, temperature: float = 0.85,
                        timeout: float = DEFAULT_TIMEOUT_S,
                        api_key: Optional[str] = None,
                        safety: bool = True, thinking: bool = True,
                        chain=None) -> AsyncIterator[str]:
    """Stream incrementally, retrying only before the first emitted token."""
    loop = asyncio.get_running_loop()
    import threading

    async def _one_stream(client, model_name: str, remaining: float):
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
                    cfg_kwargs["safety_settings"] = _no_safety()
                if thinking:
                    tc = _thinking(model_name)
                    if tc is not None:
                        cfg_kwargs["thinking_config"] = tc
                for chunk in client.models.generate_content_stream(
                    model=model_name,
                    contents=contents,
                    config=_t.GenerateContentConfig(**cfg_kwargs),
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
            item = await asyncio.wait_for(queue.get(), timeout=remaining)
            if item is None:
                return
            if isinstance(item, Exception):
                raise item
            yield item

    models = _models_to_try(model, chain, contents)
    started = time.monotonic()
    first_key = _initial_key(api_key)
    if not first_key:
        log.error("[llm] no active Gemini API key")
        return

    for model_index, model_name in enumerate(models):
        current_key = first_key if model_index == 0 else (_initial_key(None) or first_key)
        tried_keys: set[str] = set()
        transient_retries = 0
        while current_key:
            remaining = timeout - (time.monotonic() - started)
            if remaining <= 0:
                return
            attempt_started = time.monotonic()
            emitted = False
            try:
                client = await asyncio.wait_for(
                    asyncio.to_thread(get_client, current_key), timeout=remaining,
                )
                remaining = timeout - (time.monotonic() - started)
                if remaining <= 0:
                    raise asyncio.TimeoutError()
                async for text in _one_stream(client, model_name, remaining):
                    emitted = True
                    yield text
                if not emitted:
                    raise RuntimeError("empty stream")
                return
            except Exception as error:
                elapsed = time.monotonic() - attempt_started
                _log_attempt_failure(model_name, current_key, error, elapsed)
                if emitted:
                    log.warning("[llm] stream model=%s stopped after first token; returning partial text",
                                model_name)
                    return
                kind = _error_kind(error)
                if kind == "rate_limit":
                    tried_keys.add(current_key)
                    next_key = _next_key_after_limit(current_key, tried_keys)
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
                break

# ── Контракт LlmClassify (роутер, этап 2): (текст, каталог) → id | None ──

CLASSIFY_SYSTEM = (
    "Ты — классификатор команд ассистента. По фразе пользователя выбери одно "
    "действие из каталога. Ответь ровно id действия одной строкой, без слов "
    "и пояснений. Если подходящего действия в каталоге нет — ответь ровно: null"
)

_ID_RE = re.compile(r"[a-z0-9_.]+")


async def classify_action(text: str, catalog: str, *, model: Optional[str] = None,
                          timeout: float = DEFAULT_TIMEOUT_S,
                          api_key: Optional[str] = None) -> Optional[str]:
    """Клей между generate() (сырой текст) и LlmClassify (id действия).

    Промпт-классификатор: каталог из реестра → ответ-идентификатор; «null»,
    проза и пустой ответ → None. Проверку «id известен реестру» НЕ делает —
    это ответственность роутера (sakura_core/router.py): неизвестный id
    считается разговором.
    """
    if not (text or "").strip() or not (catalog or "").strip():
        return None
    raw = await generate(
        text,
        system=f"{CLASSIFY_SYSTEM}\n\nКаталог действий:\n{catalog}",
        model=model, max_tokens=24, temperature=0.0, timeout=timeout,
        api_key=api_key,
    )
    answer = (raw or "").strip().strip('`"\'').strip()
    first = answer.splitlines()[0].strip().rstrip(".,;:") if answer else ""
    first = first.lower()
    if not first or first in ("null", "none", "-"):
        return None
    return first if _ID_RE.fullmatch(first) else None


def make_llm_classify(*, model: Optional[str] = None,
                      timeout: float = DEFAULT_TIMEOUT_S,
                      api_key: Optional[str] = None):
    """Собрать async LlmClassify для Router(llm_classify=...).

    Ошибки (сеть, ключи) не поднимаются: классификация — последний шаг
    перед разговором, провал означает «это разговор».
    """
    async def classify(text: str, catalog: str) -> Optional[str]:
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


async def ask_gemini(
    user_message: str, save_history: bool = True, history_limit: int = 60,
    chain=None,
) -> str:
    from config import MAIN_MODEL, get_active_key, mark_key_used

    _t_mono = __import__("time").monotonic
    _t0 = _t_mono()

    full_system = await _build_system(query="")
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
    from modules.web_search import needs_search, facts_prompt, format_sources
    if needs_search(user_message):
        from modules.web_search import search_grounded as _grounded
        g_answer, g_sources, g_ok = await _grounded(user_message)
        if g_ok and g_answer:
            search_facts = g_answer.strip()
            search_sources = list(g_sources or [])
            log.info("[search] parallel → факты в контекст LLM")
        else:
            web_ctx = await maybe_fetch_web(user_message)
            if web_ctx:
                full_system += f"\n\nКОНТЕНТ ИЗ ИНТЕРНЕТА:\n{web_ctx}"

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

    if search_sources and reply:
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
) -> tuple[str, str]:
    """Голосовой ответ с истинным стримингом LLM→TTS."""
    from config import MAIN_MODEL, FALLBACK_MODEL, get_active_key, mark_key_used
    from memory.memory import add_to_history

    key = get_active_key()
    if not key:
        if websocket:
            try:
                import json as _json
                await websocket.send(_json.dumps({
                    "type": "reply", "device_id": device_id, "text": "Все ключи исчерпаны.",
                }))
                await websocket.send(_json.dumps({
                    "type": "tts_end", "device_id": device_id,
                }))
            except Exception as e:
                log.debug(f"[llm] ask_gemini_voice: {type(e).__name__}: {e}")
        return ("Все ключи исчерпаны.", "neutral")

    _t_build = __import__("time").monotonic()
    full_system = await _build_system(query=user_message)
    len_hint = _LEN_HINT.get(length, "")
    if len_hint:
        full_system = f"{full_system}\n\n{len_hint}"
    max_tok = (config.VOICE_MAX_TOKENS if config.VOICE_MAX_TOKENS_OVERRIDE
               else _LEN_TOKENS.get(length, config.VOICE_MAX_TOKENS))
    log.info(f"[voice] len={length} → hint={'да' if len_hint else 'нет'}, max_tokens={max_tok}")
    log.info(f"[voice] _build_system за {__import__('time').monotonic()-_t_build:.2f}с")

    contents  = _build_contents(
        user_message, history_limit=config.VOICE_HISTORY_LIMIT
    )
    emotion   = "neutral"
    full_text = ""

    from modules.web_search import needs_search, facts_prompt
    search_needed = needs_search(user_message)
    search_facts  = None
    if search_needed:
        from modules.web_search import search_grounded as _grounded
        g_ans, _g_srcs, g_ok = await _grounded(user_message)
        if g_ok and g_ans:
            search_facts = g_ans.strip()
            log.info("[search] parallel → голосовой контекст")
        else:
            web_ctx = await maybe_fetch_web(user_message)
            if web_ctx:
                search_facts = web_ctx.strip()

    if search_facts:
        full_system += facts_prompt(search_facts)
    elif search_needed:
        full_system += (
            "\n\nПоиск свежих данных в интернете сейчас не удался. Если для ответа "
            "нужны актуальные данные — честно скажи Мастеру, что не нашла, и не "
            "выдумывай факты."
        )

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
                timeout     = 8.0,
                chain       = config.VOICE_MODEL_CHAIN,
            )
        else:
            response  = await generate(contents, system=full_system, model=MAIN_MODEL,
                                       max_tokens=max_tok, temperature=0.85,
                                       timeout=8.0, chain=config.VOICE_MODEL_CHAIN)
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
                    chain=config.VOICE_MODEL_CHAIN,
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
                    import json as _json
                    await websocket.send(_json.dumps({
                        "type": "tts_end", "device_id": device_id,
                    }))
                except Exception as e:
                    log.debug(f"[llm] ask_gemini_voice: {type(e).__name__}: {e}")

    clean_text = clean_reply(full_text.strip()) if full_text else ""

    if clean_text and websocket:
        try:
            import json as _json
            await websocket.send(_json.dumps({
                "type": "reply", "device_id": device_id, "text": clean_text,
            }))
        except Exception as e:
            log.debug(f"[llm] ask_gemini_voice: {type(e).__name__}: {e}")

    add_to_history("user",  user_message)
    add_to_history("model", clean_text)
    log.info(f"[голос] ответ: {clean_text!r}")

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
            chain=config.MODEL_CHAIN,
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
