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
import re
from typing import AsyncIterator, Optional

import config

log = logging.getLogger("sakura.llm")

_clients: dict[str, object] = {}
_created = 0  # счётчик созданий клиента — тест этапа 4 следит, что он не растёт

DEFAULT_TIMEOUT_S = 12.0

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
                   response_mime_type: Optional[str] = None) -> str:
    """generate_content с таймаутом, фолбэком моделей, NO_SAFETY и thinking.
    '' при полном провале."""
    from google.genai import types as _t

    client = get_client(pick_key(api_key))
    models = (model,) if model else FALLBACK_MODELS
    last_exc: Optional[Exception] = None
    for m in models:
        try:
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
            r = await asyncio.wait_for(asyncio.to_thread(
                lambda m=m, cfg=cfg_kwargs: client.models.generate_content(
                    model=m,
                    contents=contents,
                    config=_t.GenerateContentConfig(**cfg),
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
                        api_key: Optional[str] = None,
                        safety: bool = True, thinking: bool = True) -> AsyncIterator[str]:
    """Стриминг текста LLM: токены по мере поступления.

    Итератор google-genai блокирующий → читается в отдельном треде, чанки
    кладутся в asyncio-очередь. Именно здесь v2 (tts_server._drain) читала
    весь поток до конца — это и делало «стриминг» фикцией.
    """
    from google.genai import types as _t

    client = get_client(pick_key(api_key))
    loop = asyncio.get_event_loop()
    q: asyncio.Queue = asyncio.Queue()
    _model = model or FALLBACK_MODELS[0]

    def _produce() -> None:
        try:
            cfg_kwargs = dict(
                system_instruction=system or None,
                max_output_tokens=max_tokens,
                temperature=temperature,
            )
            if safety:
                cfg_kwargs["safety_settings"] = _no_safety()
            if thinking:
                tc = _thinking(_model)
                if tc is not None:
                    cfg_kwargs["thinking_config"] = tc
            for chunk in client.models.generate_content_stream(
                model=_model,
                contents=contents,
                config=_t.GenerateContentConfig(**cfg_kwargs),
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


# ── Синхронный мост: LlmClassify — синхронный контракт, classify_action — нет ──

_classify_pool = None  # один поток со своим циклом на процесс (лениво)


def _run_classify(coro):
    """Выполнить корутину классификации вне работающего цикла адаптеров.

    route() синхронный и вызывается из-под живого event loop'а, поэтому
    asyncio.run() здесь нельзя — корутина уходит в отдельный поток со своим
    циклом. Вызывается только когда реестр не смог ответить без LLM, то есть
    на разговорных формулировках, — не на горячем пути команд.
    """
    global _classify_pool
    if _classify_pool is None:
        import concurrent.futures
        _classify_pool = concurrent.futures.ThreadPoolExecutor(
            max_workers=1, thread_name_prefix="sakura-classify")
    return _classify_pool.submit(asyncio.run, coro).result()


def make_llm_classify(*, model: Optional[str] = None,
                      timeout: float = DEFAULT_TIMEOUT_S,
                      api_key: Optional[str] = None):
    """Собрать LlmClassify для Router(llm_classify=...).

    Ошибки (сеть, ключи) не поднимаются: классификация — последний шаг
    перед разговором, провал означает «это разговор».
    """
    def classify(text: str, catalog: str) -> Optional[str]:
        try:
            return _run_classify(
                classify_action(text, catalog, model=model,
                                 timeout=timeout, api_key=api_key))
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

def _build_contents(user_message: str, extra_system: str = "") -> list:
    from google.genai import types as _t
    from memory.memory import get_history
    history  = get_history()[-60:]
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
    from memory.memory import get_guest_history
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


async def ask_gemini(user_message: str, save_history: bool = True) -> str:
    from config import MAIN_MODEL, get_active_key, mark_key_used

    _t_mono = __import__("time").monotonic
    _t0 = _t_mono()

    full_system = _build_system(query="")
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
    contents = _build_contents(user_message)
    try:
        _t_prep = _t_mono() - _t0
        response = await generate(contents, system=full_system, model=MAIN_MODEL)
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
        from modules.memories import extract_and_remember
        asyncio.create_task(extract_and_remember(user_message, reply))
        from memory.memory import should_summarize, summarize_session
        if should_summarize():
            asyncio.create_task(summarize_session())
        from modules.context import get_full_context
        ctx_snap = get_full_context()
        from modules.timeline import extract_and_save_from_dialogue
        asyncio.create_task(asyncio.to_thread(
            extract_and_save_from_dialogue, user_message, reply, ctx_snap
        ))
        from modules.mood_vector import mark_interaction, auto_detect_mood_from_reply
        mark_interaction()
        asyncio.create_task(asyncio.to_thread(
            auto_detect_mood_from_reply, reply, user_message
        ))
        try:
            from modules.self_correction import process_conversation
            asyncio.create_task(asyncio.to_thread(
                process_conversation, user_message, reply
            ))
        except Exception as e:
            log.debug(f"[llm] ask_gemini: {type(e).__name__}: {e}")
        try:
            from modules.secret_diary import write_entry as diary_write
            asyncio.create_task(diary_write(
                f"Мастер: {user_message[:200]}\nСакура: {reply[:200] if reply else ''}",
                "neutral"
            ))
        except Exception as e:
            log.debug(f"[llm] ask_gemini: {type(e).__name__}: {e}")

    return reply


async def _handle_gemini_error(e: Exception, user_message: str, save_history: bool) -> str:
    from config import MAIN_MODEL, FALLBACK_MODEL, get_active_key, mark_key_used

    err = str(e)
    if "429" in err or "quota" in err.lower():
        await asyncio.sleep(60)
        return await ask_gemini(user_message, save_history)
    if "500" in err or "INTERNAL" in err:
        await asyncio.sleep(5)
        return await ask_gemini(user_message, save_history)
    if "SSL" in err or "DECRYPTION" in err or "bad record mac" in err:
        await asyncio.sleep(3)
        return await ask_gemini(user_message, save_history)
    if "503" in err or "UNAVAILABLE" in err:
        log.warning("Основная модель недоступна → Gemma fallback")
        key = get_active_key()
        if key:
            try:
                full_system = _build_system(query="")
                contents    = _build_contents(user_message)
                r2          = await generate(contents, system=full_system, model=FALLBACK_MODEL)
                reply       = clean_reply(r2)
                mark_key_used(key)
                if save_history:
                    from memory.memory import add_to_history
                    add_to_history("user", user_message)
                    add_to_history("model", reply)
                return reply or "Мастер, серверы перегружены. Попробуй позже."
            except Exception as e2:
                log.error(f"Fallback error: {e2}")
    log.error(f"Gemini error: {e}")
    return f"Мастер, что-то пошло не так. Ошибка: {err[:100]}"


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
    full_system = _build_system(query=user_message)
    len_hint = _LEN_HINT.get(length, "")
    if len_hint:
        full_system = f"{full_system}\n\n{len_hint}"
    max_tok = _LEN_TOKENS.get(length, 150)
    log.info(f"[voice] len={length} → hint={'да' if len_hint else 'нет'}, max_tokens={max_tok}")
    log.info(f"[voice] _build_system за {__import__('time').monotonic()-_t_build:.2f}с")

    contents  = _build_contents(user_message)
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
            from modules.mood_vector import get_current_emotion
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
            )
        else:
            response  = await generate(contents, system=full_system, model=MAIN_MODEL,
                                       max_tokens=max_tok, temperature=0.85)
            full_text = response
            mark_key_used(key)
    except Exception as e:
        log.error(f"[Voice] {e}")
        try:
            if websocket:
                from adapters.voice import stream_llm_to_tts
                from modules.mood_vector import get_current_emotion
                full_text, emotion = await stream_llm_to_tts(
                    contents, full_system, websocket, device_id,
                    model=FALLBACK_MODEL, max_tokens=max_tok,
                    api_key=key, emotion=get_current_emotion(),
                )
            else:
                r = await generate(contents, system=full_system, model=FALLBACK_MODEL,
                                   max_tokens=max_tok)
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
        from modules.mood_vector import get_current_emotion
        asyncio.create_task(broadcast_mood_after_reply(
            clean_text, user_message, emotion
        ))
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
    from memory.memory import add_guest_message

    key = get_active_key()
    if not key:
        return "Извини, сейчас недоступна."

    try:
        full_system = _build_guest_system(role, user_name, user_id)
        contents    = _build_guest_contents(user_id, user_message)

        response = await generate(contents, system=full_system, model=MAIN_MODEL)
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
