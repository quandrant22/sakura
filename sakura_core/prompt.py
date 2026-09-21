"""Сборка системного промпта (этап 6, коммит 1).

Перенесено из main.py без изменения логики:
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
#  Бюджет сборки промпта по типу пути
# ─────────────────────────────────────────────


def _path_budget(query: str) -> tuple[str, float]:
    """Бюджет сборки промпта по типу пути (этап 7.2, таблица в docs/v3/task.md).

    Команда и воспоминание, чей embed уже в кэше, — 50 мс. Воспоминание
    с первым embed платит один сетевой вызов — это признанная цена
    операции, а не провал: бюджет 600 мс.
    """
    if not (query or "").strip():
        return "команда", 0.050
    try:
        from modules.memory_honesty import is_recall_query
        if not is_recall_query(query):
            return "команда", 0.050
    except Exception:
        return "команда", 0.050
    try:
        from memory.db import embedding_cached
        if embedding_cached(query, "RETRIEVAL_QUERY"):
            return "воспоминание (embed из кэша)", 0.050
    except Exception:
        pass
    return "воспоминание (embed впервые)", 0.600


# ─────────────────────────────────────────────
#  Полный системный промпт
# ─────────────────────────────────────────────

# ── Релевантность блоков ─────────────────────────────────────────────
# Часть блоков полезна только в своём разговоре. Раньше они собирались
# на каждый вызов — даже когда Мастер говорил «Громче». Пустой query
# считается «данных нет» и не режет ничего: текстовый путь query не
# передаёт, и он должен остаться ровно таким, как был.

def _mentions(text: str, keys: tuple) -> bool:
    """Есть ли в запросе хоть одно из ключевых слов (подстрока, регистр не важен)."""
    t = (text or "").strip().lower()
    if not t:
        return True
    return any(k in t for k in keys)


_JP_KEYS = ("японск", "нихонго", "кандзи", "хирагана", "катакана", "jlpt")
_APP_KEYS = ("открой", "запусти", "включи", "закрой", "приложен", "программ",
             "калькулятор", "браузер", "ютуб", "youtube", "телеграм", "дискорд",
             "steam", "стим", "через приложение")
_CODE_KEYS = ("код", "скрипт", "файл", "баг", "ошибк", "исправь", "почини",
              "рефактор", "функци", "python", "питон", "терминал", "git",
              "mimo", "лог", "трейсбек", "traceback", "тест", "напиши")
_FORTUNE_KEYS = ("предсказ", "погада", "гада", "фортун", "удач", "судьб",
                 "гороскоп", "cookie", "ждёт", "ждет", "меня жд")
_GAME_KEYS = ("игр", "steam", "стим", "библиотек", "ачивк", "достижен",
              "прохожден", "патч", "сохранен")


def _window_category(window: str | None) -> str:
    """Категория активного окна вместо сырого заголовка (7.3).

    Заголовок окна меняется при каждом переключении вкладки — кэш
    промпта с сырым заголовком в ключе почти никогда не попадал.
    Категория (call/game/code/browser/media/other) стабильна.
    """
    try:
        from modules.window_watcher import _classify_window
        return _classify_window(window or "", False)
    except Exception:
        return "unknown"


_build_system_cache: dict = {}
_build_system_lock = threading.Lock()
_build_system_warm = False   # была ли хотя бы одна сборка в этом процессе
_BUILD_SYSTEM_TTL = 20.0   # секунд


async def _build_system(include_calendar: bool = False, active_window: str | None = None, query: str = "") -> str:
    """Строит системный промпт. Кэшируется для повторных вызовов без query.

    Блоки — независимые чтения, собираются параллельно (gather поверх
    to_thread): время сборки растёт как max, а не как сумма, и новые
    блоки её не ухудшают. Состав и порядок блоков прежние.
    """
    import asyncio
    import time as _t

    from modules.state import _current_track
    from modules.state_arbiter import get_current_emotion

    # Кэшируем только типичный случай (Telegram, без calendar, без query)
    _track_sig = f"{(_current_track or {}).get('title', '')}|{(_current_track or {}).get('status', '')}"
    _emotion_sig = get_current_emotion()
    _hour_sig = __import__('datetime').datetime.now().hour
    _raw_key = f"{include_calendar}:{_window_category(active_window)}:{bool(query)}:{tuple(sorted(_get_online_devices()))}:{_track_sig}:{_emotion_sig}:{_hour_sig}"
    cache_key = hashlib.md5(_raw_key.encode("utf-8")).hexdigest()
    if not query:
        with _build_system_lock:
            entry = _build_system_cache.get(cache_key)
            if entry and _t.monotonic() < entry[1]:
                return entry[0]

    _bs_t0 = _t.monotonic()
    # Классификация пути — на входе: embed, посчитанный этой сборкой,
    # попадает в кэш и исказил бы тип пути после сборки.
    _kind, _budget = _path_budget(query)

    async def _block(label, fn, *args):
        try:
            value = await asyncio.to_thread(fn, *args)
        except Exception as e:
            log.debug(f"[prompt] _build_system: {type(e).__name__}: {e}")
            value = None
        return label, value

    # Ядро личности: общий контекст нужен только характеру.
    async def _identity():
        _lbl, ctx = await _block("ctx", _full_ctx)
        persona = None
        try:
            if ctx:
                master = ctx.get("master") or {}
                persona = get_system_prompt(
                    active_window=active_window,
                    ctx_location=master.get("location"),
                    ctx_status=master.get("status"),
                )
            else:
                persona = get_system_prompt()
        except Exception as e:
            log.debug(f"[prompt] identity: {type(e).__name__}: {e}")
        self_blk, session_blk = await asyncio.gather(
            _block("self", _self_ctx),
            _block("session", _session_ctx),
        )
        return "identity", (persona, self_blk[1], session_blk[1])

    def _full_ctx():
        from modules.context import get_full_context
        return get_full_context()

    def _self_ctx():
        from memory.db import get_self_context
        return get_self_context()

    def _session_ctx():
        from modules.steam_integration import get_session_context
        return get_session_context()

    def _caps():
        from modules.capabilities import get_capabilities_block
        return get_capabilities_block()

    def _rules():
        from modules.rules import get_rules_context
        return get_rules_context()

    def _ctx_block():
        from modules.context import build_context_block
        return build_context_block(active_window)

    def _devices():
        from modules.device_manager import get_device_context
        return get_device_context()

    def _memory():
        # query передаётся только если явно нужен семантический поиск.
        # Без query — быстрый топ по hits, без сетевых вызовов.
        from memory.db import get_memory_context as db_get_memory_context
        from modules.memory_honesty import enrich_memory_context
        raw_mem = db_get_memory_context()
        return enrich_memory_context(raw_mem, query) if raw_mem else ""

    def _graph():
        from modules.graph import get_graph_context
        return get_graph_context(query)
    def _vps():
        from modules.vps_monitor import get_vps_context
        return get_vps_context()

    def _threads():
        from modules.threads import get_threads_context
        return get_threads_context()

    def _focus():
        from modules.context import get_focus_context
        return get_focus_context()

    def _screen():
        from modules.context import get_screen_context
        return get_screen_context()

    def _timeline():
        from modules.timeline import get_timeline_context
        return get_timeline_context(days=2, limit=5)

    def _achievements():
        from modules.timeline import get_achievements_context
        return get_achievements_context(limit=3)

    def _patterns():
        from modules.patterns import get_patterns_hint
        return get_patterns_hint()

    def _return_hint():
        from modules.rituals import get_return_context
        return (get_return_context() or {}).get("prompt_hint", "")

    def _identity_model():
        from memory.db import get_identity_model
        return get_identity_model()

    def _trigger():
        from modules.emotional_memory import get_trigger_hint
        return get_trigger_hint(query)

    def _narrative():
        from modules.sakura_narrative import get_narrative_hint
        return get_narrative_hint()

    def _steam():
        # Steam: текущая игра всегда, библиотека — только если разговор про игры
        from modules.steam_integration import format_current_game_context, format_library_context
        game_ctx = format_current_game_context()
        lib_ctx = None
        if not game_ctx and _mentions(query, _GAME_KEYS):
            lib_ctx = format_library_context()
        return game_ctx, lib_ctx

    def _style():
        from modules.speech_style import get_style_hint
        return get_style_hint()

    def _version_season():
        from modules.emotional_memory import get_version_hint, get_season_hint
        return get_version_hint(), get_season_hint()

    def _interests():
        from modules.relationship import get_interests_hint
        return get_interests_hint()

    def _habits():
        from modules.habits import get_context_for_prompt
        return get_context_for_prompt()

    def _jp():
        from modules.learn_japanese import get_context_for_prompt
        return get_context_for_prompt()

    def _apps():
        from modules.app_launcher import get_context_for_prompt
        return get_context_for_prompt()

    def _coding():
        from capabilities.coding import is_available
        if not is_available():
            return None
        return "КОДИНГ: У тебя есть доступ к MiMo Code. Ты можешь создавать и править файлы на сервере. Используй capabilities/coding.py и modules/prompt_builder.py."

    def _fortune():
        from modules.fortune_cookie import get_context_for_prompt
        return get_context_for_prompt()

    def _calendar():
        from modules.calendar_module import get_calendar_context
        return get_calendar_context()

    def _summary():
        from memory.memory import load_session_summary
        return load_session_summary()

    def _tasks_ctx():
        from modules.tasks import get_tasks_context
        return get_tasks_context()

    # Все задачи независимы — собираем одновременно, собираем в прежнем порядке.
    tasks = [
        _identity(),
        _block("caps", _caps),
        _block("rules", _rules),
        _block("ctx_block", _ctx_block),
        _block("devices", _devices),
        _block("memory", _memory),
        _block("graph", _graph),
        _block("vps", _vps),
        _block("threads", _threads),
        _block("focus", _focus),
        _block("screen", _screen),
        _block("timeline", _timeline),
        _block("achievements", _achievements),
        _block("patterns", _patterns),
        _block("return", _return_hint),
        _block("identity_model", _identity_model),
    ]
    if query:
        tasks.append(_block("trigger", _trigger))
    tasks += [
        _block("narrative", _narrative),
        _block("steam", _steam),
        _block("style", _style),
        _block("version", _version_season),
        _block("interests", _interests),
        _block("habits", _habits),
    ]
    if _mentions(query, _JP_KEYS):
        tasks.append(_block("jp", _jp))
    if _mentions(query, _APP_KEYS):
        tasks.append(_block("apps", _apps))
    if _mentions(query, _CODE_KEYS):
        tasks.append(_block("coding", _coding))
    if _mentions(query, _FORTUNE_KEYS):
        tasks.append(_block("fortune", _fortune))
    if include_calendar:
        tasks.append(_block("calendar", _calendar))
    tasks += [
        _block("summary", _summary),
        _block("tasks", _tasks_ctx),
    ]

    d = dict(await asyncio.gather(*tasks))

    parts: list[str] = []

    persona, self_ctx, session_ctx = d["identity"]
    if persona:
        parts.append(persona)
    if self_ctx:
        parts.append(self_ctx)
    if session_ctx:
        parts.append(session_ctx)

    parts.append(d["caps"] or "")
    if d["rules"]:
        parts.append(d["rules"])
    parts.append(d["ctx_block"] or "")
    parts.append(d["devices"] or "")

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

    if d["memory"]:
        parts.append(d["memory"])
    if d["graph"]:
        parts.append(d["graph"])
    if d["vps"]:
        parts.append(d["vps"])
    if d["threads"]:
        parts.append(d["threads"])
    if d["focus"]:
        parts.append(d["focus"])
    if d["screen"]:
        parts.append(d["screen"])
    if d["timeline"]:
        parts.append(d["timeline"])
    if d["achievements"]:
        parts.append(d["achievements"])
    if d["patterns"]:
        parts.append(d["patterns"])
    if d["return"]:
        parts.append(d["return"])
    if d["identity_model"]:
        parts.append(d["identity_model"])
    if query and d.get("trigger"):
        parts.append(d["trigger"])
    if d["narrative"]:
        parts.append(d["narrative"])
    game_ctx, lib_ctx = d["steam"] or (None, None)
    if game_ctx:
        parts.append(game_ctx)
    elif lib_ctx:
        parts.append(lib_ctx)
    if d["style"]:
        parts.append(d["style"])
    version_season = d["version"]
    if version_season is not None:
        parts.append(version_season[0])
        parts.append(version_season[1])

    if d["interests"]:
        parts.append(d["interests"])
    if d["habits"]:
        parts.append(d["habits"])
    if d.get("jp"):
        parts.append(d["jp"])
    if d.get("apps"):
        parts.append(d["apps"])
    if d.get("coding"):
        parts.append(d["coding"])
    if d.get("fortune"):
        parts.append(d["fortune"])
    if include_calendar and d.get("calendar"):
        parts.append(d["calendar"])
    if d["summary"]:
        parts.append(f"РЕЗЮМЕ ПРОШЛОГО РАЗГОВОРА:\n{d['summary']}")
    if d["tasks"]:
        parts.append(d["tasks"])

    result = "\n\n".join(parts)

    _dt = _t.monotonic() - _bs_t0
    # Холодный старт процесса платит за импорты и прогревы модулей — это
    # не превышение бюджета пути, а разовая цена запуска демона.
    global _build_system_warm
    if _dt > _budget and _build_system_warm:
        log.warning(f"[build_system] {_kind}: {_dt * 1000:.0f}мс при бюджете {_budget * 1000:.0f}мс")
    log.info(f"[build_system] {_kind}{'' if _build_system_warm else ' [холодный старт]'} "
             f"за {_dt:.2f}с, блоков={len(parts)} символов={len(result)}")
    _build_system_warm = True

    if not query:
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
