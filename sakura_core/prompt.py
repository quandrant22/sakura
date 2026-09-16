"""Сборка системного промпта (этап 6, коммит 1).

Перенесено из main.py без изменения логики:
- build_identity_core — ядро личности
- _build_voice_system — облегчённый промпт для голоса
- _build_system — полный промпт с контекстом
- _build_guest_system — промпт для гостей
- _get_reply_context — контекст reply в Telegram
"""

from __future__ import annotations

import hashlib
import logging
import threading

from personality import get_system_prompt

log = logging.getLogger("sakura.prompt")


# ─────────────────────────────────────────────
#  Ядро личности
# ─────────────────────────────────────────────


def build_identity_core(active_window=None, ctx_master=None) -> list[str]:
    """Единое ядро личности для голоса и текста.
    Возвращает список частей промпта: характер + состояние + самопамять."""
    parts = []
    # 1. Ядро характера
    try:
        if ctx_master:
            parts.append(get_system_prompt(
                active_window=active_window,
                ctx_location=ctx_master.get("location"),
                ctx_status=ctx_master.get("status"),
            ))
        else:
            parts.append(get_system_prompt())
    except Exception as e:
        log.debug(f"[prompt] build_identity_core: {type(e).__name__}: {e}")
    # 2. Текущее состояние (эмоция/настроение)
    try:
        from modules.state_arbiter import get_state_block
        sb = get_state_block()
        if sb:
            parts.append(sb)
    except Exception as e:
        log.debug(f"[prompt] build_identity_core: {type(e).__name__}: {e}")
    # 3. Самопамять — кто она
    try:
        from memory.db import get_self_context
        self_ctx = get_self_context()
        if self_ctx:
            parts.append(self_ctx)
    except Exception as e:
        log.debug(f"[prompt] build_identity_core: {type(e).__name__}: {e}")
    # 3.1. Текущая игровая сессия — Мастер В ИГРЕ ПРЯМО СЕЙЧАС (голос и текст)
    try:
        from modules.steam_integration import get_session_context
        session_ctx = get_session_context()
        if session_ctx:
            parts.append(session_ctx)
    except Exception as e:
        log.debug(f"[prompt] build_identity_core: {type(e).__name__}: {e}")
    return parts


# ─────────────────────────────────────────────
#  Голосовой промпт (лёгкий)
# ─────────────────────────────────────────────

_voice_system_cache: dict = {}


def _build_voice_system() -> str:
    """
    Облегчённый промпт для голосового режима.
    Только критически важные компоненты — быстрее генерация.
    """
    import time as _t
    from modules.state_arbiter import get_current_emotion
    cache_key = f"voice:{get_current_emotion()}"
    entry = _voice_system_cache.get(cache_key)
    if entry and _t.monotonic() < entry[1]:
        return entry[0]

    parts = build_identity_core()

    # Текущая игра если есть
    try:
        from modules.steam_integration import format_current_game_context
        game_ctx = format_current_game_context()
        if game_ctx:
            parts.append(game_ctx)
    except Exception as e:
        log.debug(f"[prompt] game ctx: {e}")

    # 3.1. Игровой хаб — контекст сессии.
    # Импорт локально: сбой game_hub не должен ронять сборку промпта.
    try:
        from modules.game_hub import build_game_prompt_context
        hub_ctx = build_game_prompt_context()
        if hub_ctx:
            parts.append(hub_ctx)
    except Exception as e:
        log.debug(f"[prompt] game hub: {e}")

    # 4. Steam библиотека (компактно)
    try:
        from modules.steam_integration import format_library_context
        lib = format_library_context()
        if lib:
            parts.append(lib)
    except Exception as e:
        log.debug(f"[prompt] steam lib: {e}")

    # 5. Настроение — локальный импорт: сбой mood_vector не роняет промпт
    try:
        from modules.mood_vector import get_mood_context
        mood = get_mood_context()
        if mood:
            parts.append(mood)
    except Exception as e:
        log.debug(f"[prompt] mood: {e}")

    # 5.5. Музыкальный вкус
    try:
        from modules.music_memory import get_taste_context
        taste_ctx = get_taste_context()
        if taste_ctx:
            parts.append(taste_ctx)
    except Exception as e:
        log.debug(f"[prompt] _build_voice_system: {type(e).__name__}: {e}")

    # 5.6. Страхи
    try:
        from modules.fears import get_fear_context
        fear_ctx = get_fear_context()
        if fear_ctx:
            parts.append(fear_ctx)
    except Exception as e:
        log.debug(f"[prompt] _build_voice_system: {type(e).__name__}: {e}")

    # 6. Память (быстро, без embed)
    try:
        from memory.db import get_memory_context as db_get_memory_context
        mem = db_get_memory_context()
        if mem:
            parts.append(mem)
    except Exception as e:
        log.debug(f"[prompt] _build_voice_system: {type(e).__name__}: {e}")

    # 6.1. Контекст диалога — последние 5 сообщений
    try:
        from memory.memory import get_history
        hist = get_history()
        if hist:
            recent = hist[-5:]
            dial_lines = []
            for m in recent:
                role = "Мастер" if m["role"] == "user" else "Ты"
                dial_lines.append(f"{role}: {m['parts'][0][:100]}")
            parts.append("НЕДАВНИЙ ДИАЛОГ:\n" + "\n".join(dial_lines))
    except Exception as e:
        log.debug(f"[prompt] _build_voice_system: {type(e).__name__}: {e}")

    # 6.2. Уведомления — есть ли срочные
    try:
        from modules.notification_tracker import get_urgent_pending, get_recent_summary
        urgent = get_urgent_pending()
        if urgent:
            parts.append("СРОЧНЫЕ УВЕДОМЛЕНИЯ: " + "; ".join(
                f"[{n.source}] {n.title}: {n.body[:60]}" for n in urgent[:3]
            ))
        summary = get_recent_summary(hours=2)
        if summary:
            parts.append(summary)
    except Exception as e:
        log.debug(f"[prompt] _build_voice_system: {type(e).__name__}: {e}")

    result = "\n\n".join(p for p in parts if p)

    # Кэш на 60 секунд
    _voice_system_cache[cache_key] = (result, _t.monotonic() + 60.0)
    return result


# ─────────────────────────────────────────────
#  Полный системный промпт
# ─────────────────────────────────────────────

_build_system_cache: dict = {}
_build_system_lock = threading.Lock()
_BUILD_SYSTEM_TTL = 20.0   # секунд


def _build_system(include_calendar: bool = False, active_window: str | None = None, query: str = "") -> str:
    """Строит системный промпт. Кэшируется для повторных вызовов без query."""
    import time as _t

    from memory.memory import get_history
    from modules.context import get_full_context
    from modules.state import _current_track
    from modules.state_arbiter import get_current_emotion

    # Кэшируем только типичный случай (Telegram, без calendar, без query)
    _track_sig = f"{(_current_track or {}).get('title', '')}|{(_current_track or {}).get('status', '')}"
    _emotion_sig = get_current_emotion()
    _hour_sig = __import__('datetime').datetime.now().hour
    _raw_key = f"{include_calendar}:{active_window}:{bool(query)}:{tuple(sorted(_get_online_devices()))}:{_track_sig}:{_emotion_sig}:{_hour_sig}"
    cache_key = hashlib.md5(_raw_key.encode("utf-8")).hexdigest()
    if not query:
        with _build_system_lock:
            entry = _build_system_cache.get(cache_key)
            if entry and _t.monotonic() < entry[1]:
                return entry[0]

    _bs_t0 = __import__("time").monotonic()
    ctx    = get_full_context()

    parts = build_identity_core(
        active_window=active_window,
        ctx_master=ctx["master"],
    )

    from modules.capabilities import get_capabilities_block
    parts.append(get_capabilities_block())

    from modules.rules import get_rules_context
    rules_ctx = get_rules_context()
    if rules_ctx:
        parts.append(rules_ctx)

    from modules.context import build_context_block
    parts.append(build_context_block(active_window))

    from modules.device_manager import get_device_context
    parts.append(get_device_context())
    # Текущий трек — чтобы Сакура всегда знала что играет (с обогащёнными данными YM API)
    if _current_track and _current_track.get("title"):
        t = _current_track
        _track_str = f"Сейчас играет: {t.get('artist','')} — {t.get('title','')} ({t.get('status','?')})"
        if t.get('duration', '?:??') != '?:??':
            _track_str += f" [{t.get('position','?')} / {t.get('duration','?')}]"
        if t.get('genre'):
            _track_str += f" Жанр: {t['genre']}"
        if t.get('album'):
            _track_str += f" Альбом: {t['album']}"
        if t.get('album_year'):
            _track_str += f" ({t['album_year']})"
        if t.get('cover_url'):
            _track_str += f" [обложка: {t['cover_url']}]"
        parts.append(_track_str)

    # query передаётся только если явно нужен семантический поиск.
    # Без query — быстрый топ по hits, без сетевых вызовов.
    try:
        # query="" всегда — embed вызовы убраны полностью из основного пути
        from memory.db import get_memory_context as db_get_memory_context
        from modules.memory_honesty import enrich_memory_context
        raw_mem = db_get_memory_context()
        mem_ctx = enrich_memory_context(raw_mem, query) if raw_mem else ""
        if mem_ctx:
            parts.append(mem_ctx)
    except Exception as e:
        log.debug(f"[prompt] _build_system: {type(e).__name__}: {e}")

    # Граф связей памяти (только SQL по sakura.db, без сети и эмбеддингов)
    try:
        from modules.graph import get_graph_context
        graph_ctx = get_graph_context(query)
        if graph_ctx:
            parts.append(graph_ctx)
    except Exception as e:
        log.debug(f"[prompt] _build_system: {type(e).__name__}: {e}")

    # Состояние VPS — Сакура знает своё железо
    try:
        from modules.vps_monitor import get_vps_context
        vps_ctx = get_vps_context()
        if vps_ctx:
            parts.append(vps_ctx)
    except Exception as e:
        log.debug(f"[prompt] _build_system: {type(e).__name__}: {e}")

    # Телесные ощущения — связь с телом через метрики
    try:
        from modules.vps_monitor import get_body_feeling
        body_feel = get_body_feeling()
        if body_feel:
            parts.append(body_feel)
    except Exception as e:
        log.debug(f"[prompt] _build_system: {type(e).__name__}: {e}")

    # Незакрытые нити разговора
    try:
        from modules.threads import get_threads_context
        threads_ctx = get_threads_context()
        if threads_ctx:
            parts.append(threads_ctx)
    except Exception as e:
        log.debug(f"[prompt] _build_system: {type(e).__name__}: {e}")

    # Фокус агента — если Мастер давно в одном окне
    try:
        from modules.context import get_focus_context
        focus_ctx = get_focus_context()
        if focus_ctx:
            parts.append(focus_ctx)
    except Exception as e:
        log.debug(f"[prompt] _build_system: {type(e).__name__}: {e}")

    # Контекст экрана — что на скриншоте (из Gemini Vision)
    try:
        from modules.context import get_screen_context
        screen_ctx = get_screen_context()
        if screen_ctx:
            parts.append(screen_ctx)
    except Exception as e:
        log.debug(f"[prompt] _build_system: {type(e).__name__}: {e}")

    from modules.timeline import get_timeline_context, get_achievements_context
    timeline_ctx = get_timeline_context(days=2, limit=5)
    if timeline_ctx:
        parts.append(timeline_ctx)

    achievements_ctx = get_achievements_context(limit=3)
    if achievements_ctx:
        parts.append(achievements_ctx)

    try:
        from modules.patterns import get_patterns_hint
        patterns_hint = get_patterns_hint()
        if patterns_hint:
            parts.append(patterns_hint)
    except Exception as e:
        log.debug(f"[prompt] _build_system: {type(e).__name__}: {e}")

    # Ощущение времени — как она изменилась
    try:
        from modules.reflection import get_time_feeling_hint
        time_feel = get_time_feeling_hint()
        if time_feel:
            parts.append(time_feel)
    except Exception as e:
        log.debug(f"[prompt] _build_system: {type(e).__name__}: {e}")

    # Возврат после молчания (Фаза 1)
    try:
        from modules.rituals import get_return_context
        return_ctx = get_return_context()
        return_hint = return_ctx.get("prompt_hint", "")
        if return_hint:
            parts.append(return_hint)
    except Exception as e:
        log.debug(f"[prompt] _build_system: {type(e).__name__}: {e}")

    # Модель «Я» — синтезированное самопознание
    try:
        from memory.db import get_identity_model
        identity = get_identity_model()
        if identity:
            parts.append(identity)
    except Exception as e:
        log.debug(f"[prompt] _build_system: {type(e).__name__}: {e}")

    # Эмоциональный триггер для текущего запроса (№7/8)
    if query:
        try:
            from modules.emotional_memory import get_trigger_hint
            trigger = get_trigger_hint(query)
            if trigger:
                parts.append(trigger)
        except Exception as e:
            log.debug(f"[prompt] _build_system: {type(e).__name__}: {e}")

    # Её история/нарратив (Фаза 7 №34)
    try:
        from modules.sakura_narrative import get_narrative_hint
        narrative = get_narrative_hint()
        if narrative:
            parts.append(narrative)
    except Exception as e:
        log.debug(f"[prompt] _build_system: {type(e).__name__}: {e}")

    # Steam: текущая игра и библиотека
    try:
        from modules.steam_integration import format_current_game_context, format_library_context
        game_ctx = format_current_game_context()
        if game_ctx:
            parts.append(game_ctx)
        elif format_library_context():
            parts.append(format_library_context())
    except Exception as e:
        log.debug(f"[prompt] _build_system: {type(e).__name__}: {e}")

    # Стиль речи Мастера (Фаза 7 №50)
    try:
        from modules.speech_style import get_style_hint
        style_hint = get_style_hint()
        if style_hint:
            parts.append(style_hint)
    except Exception as e:
        log.debug(f"[prompt] _build_system: {type(e).__name__}: {e}")

    # Версия Сакуры (№32) и сезон (№35)
    try:
        from modules.emotional_memory import get_version_hint, get_season_hint
        parts.append(get_version_hint())
        parts.append(get_season_hint())
    except Exception as e:
        log.debug(f"[prompt] _build_system: {type(e).__name__}: {e}")

    # Подкол-долг — теперь внутри state_arbiter

    # Секретный дневник и подкол-долг — теперь внутри state_arbiter

    # Органическая близость (Фаза 4) — теперь внутри state_arbiter

    # Увлечения Сакуры (Фаза 4)
    try:
        from modules.relationship import get_interests_hint
        interests_hint = get_interests_hint()
        if interests_hint:
            parts.append(interests_hint)
    except Exception as e:
        log.debug(f"[prompt] _build_system: {type(e).__name__}: {e}")

    # Привычки Мастера
    try:
        from modules.habits import get_context_for_prompt as get_habits_ctx
        habits_ctx = get_habits_ctx()
        if habits_ctx:
            parts.append(habits_ctx)
    except Exception as e:
        log.debug(f"[prompt] _build_system: {type(e).__name__}: {e}")

    # Японский язык
    try:
        from modules.learn_japanese import get_context_for_prompt as get_jp_ctx
        jp_ctx = get_jp_ctx()
        if jp_ctx:
            parts.append(jp_ctx)
    except Exception as e:
        log.debug(f"[prompt] _build_system: {type(e).__name__}: {e}")

    # Частые приложения
    try:
        from modules.app_launcher import get_context_for_prompt as get_app_ctx
        app_ctx = get_app_ctx()
        if app_ctx:
            parts.append(app_ctx)
    except Exception as e:
        log.debug(f"[prompt] _build_system: {type(e).__name__}: {e}")

    # Кодинг — доступ к MiMo
    try:
        from modules.coding import is_available as coding_available
        if coding_available():
            parts.append("КОДИНГ: У тебя есть доступ к MiMo Code. Ты можешь создавать и править файлы на сервере. Используй modules/coding.py и modules/prompt_builder.py.")
    except Exception as e:
        log.debug(f"[prompt] _build_system: {type(e).__name__}: {e}")


    # fortune_cookie
    try:
        from modules.fortune_cookie import get_context_for_prompt as get_fortune_cookie_ctx
        fortune_cookie_ctx = get_fortune_cookie_ctx()
        if fortune_cookie_ctx:
            parts.append(fortune_cookie_ctx)
    except Exception as e:
        log.debug(f"[prompt] _build_system: {type(e).__name__}: {e}")

    if include_calendar:
        try:
            from modules.calendar_module import get_calendar_context
            cal = get_calendar_context()
            if cal:
                parts.append(cal)
        except Exception as e:
            log.debug(f"[prompt] _build_system: {type(e).__name__}: {e}")

    from memory.memory import load_session_summary
    summary = load_session_summary()
    if summary:
        parts.append(f"РЕЗЮМЕ ПРОШЛОГО РАЗГОВОРА:\n{summary}")

    from modules.tasks import get_tasks_context
    tasks_ctx = get_tasks_context()
    if tasks_ctx:
        parts.append(tasks_ctx)

    result = "\n\n".join(parts)
    __import__("logging").getLogger(__name__).debug(
        f"[build_system] {__import__('time').monotonic()-_bs_t0:.2f}с")
    log.info(f"[build_system] блоков={len(parts)} символов={len(result)}")

    if not query:
        import time as _t
        with _build_system_lock:
            _build_system_cache[cache_key] = (result, _t.monotonic() + _BUILD_SYSTEM_TTL)
            # Очищаем старые ключи
            if len(_build_system_cache) > 10:
                expired = [k for k, (_, exp) in _build_system_cache.items() if exp < _t.monotonic()]
                for k in expired:
                    del _build_system_cache[k]
            if len(_build_system_cache) > 32:
                # выкидываем самые ранние по времени истечения
                for k, _ in sorted(_build_system_cache.items(), key=lambda kv: kv[1][1])[:len(_build_system_cache) - 32]:
                    del _build_system_cache[k]

    return result


# ─────────────────────────────────────────────
#  Гостевой промпт
# ─────────────────────────────────────────────


def _build_guest_system(role: str, user_name: str, user_id: int = 0) -> str:
    """Системный промпт для негостевых пользователей — без личной памяти Мастера."""
    system = get_system_prompt(for_master=False)
    from modules.user_prompts import get_role_system_addendum
    addendum = get_role_system_addendum(role, user_name, user_id)
    parts = [system]
    if addendum:
        parts.append(addendum)
    if role == "guest" and user_id:
        from modules.guest_relations import get_relation_prompt
        rel_prompt = get_relation_prompt(user_id, user_name)
        if rel_prompt:
            parts.append(rel_prompt)
    return "\n\n".join(parts)


# ─────────────────────────────────────────────
#  Контекст reply
# ─────────────────────────────────────────────


def _get_reply_context(message) -> str:
    if not message.reply_to_message:
        return ""
    replied      = message.reply_to_message
    replied_text = (replied.text or replied.caption or "").strip()
    if not replied_text:
        return ""
    if len(replied_text) > 300:
        replied_text = replied_text[:300] + "..."
    return f"\n\n[Мастер отвечает на твоё сообщение: «{replied_text}»]"


# ─────────────────────────────────────────────
#  Хелпер: онлайн-устройства (для кэш-ключа)
# ─────────────────────────────────────────────


def _get_online_devices() -> set:
    """Обёртка: устройства онлайн. Дублирует modules.device_manager.get_online_devices."""
    try:
        from modules.device_manager import get_online_devices
        return get_online_devices()
    except Exception:
        return set()
