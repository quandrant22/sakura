"""
modules/mem_cache.py — кэш в памяти для всех файловых чтений.

Проблема: каждое сообщение вызывает 12+ синхронных json.load,
включая long_term.json (4.8 МБ) который парсится дважды.
На VPS это ~50-150мс накладных расходов на чтение файлов.

Решение: держим последнее значение каждого файла в памяти с TTL.
Файл читается один раз, затем отдаётся из памяти пока не устареет
или пока не будет явно инвалидирован после записи.

Интеграция: автоматическая через monkey-patch при старте.
Или явная: вместо json.load(f) → cache.get_json(path).

TTL по типу данных:
  memory/mood_vector.json   — 5с  (меняется часто, эмоции)
  memory/rules.json         — 60с (меняется редко)
  memory/tasks.json         — 10с (может измениться после команды)
  memory/long_term.json     — 30с (меняется при записи воспоминания)
  memory/timeline.json      — 30с
  memory/session_summary.json — 30с
  memory/devices.json       — 5с  (онлайн-статус устройств)
  memory/mood.json          — 5с
  memory/rituals.json       — 10с
  memory/proactive.json     — 10с
"""

import json
import logging
import os
import tempfile
import time
import threading
from typing import Any, Optional

log = logging.getLogger("sakura.cache")

# TTL в секундах для каждого файла
_TTL: dict[str, float] = {
    "mood_vector.json":     5.0,
    "mood.json":            5.0,
    "devices.json":         5.0,
    "rules.json":          60.0,
    "tasks.json":          10.0,
    "long_term.json":      30.0,
    "timeline.json":       30.0,
    "session_summary.json": 30.0,
    "rituals.json":        10.0,
    "proactive.json":      10.0,
    "reflection.json":     30.0,
    "window_watcher.json": 10.0,
    "briefing.json":       30.0,
    "first_run.json":     300.0,
    "evening_pulse.json":  30.0,
    # Всё остальное — 15 секунд
}
_DEFAULT_TTL = 15.0

# Кэш: path → (value, expires_at, mtime)
_cache: dict[str, tuple[Any, float, float]] = {}
_lock = threading.Lock()


def _get_ttl(path: str) -> float:
    name = os.path.basename(path)
    return _TTL.get(name, _DEFAULT_TTL)


def get_json(path: str, default=None) -> Any:
    """
    Читает JSON-файл с кэшированием.
    Если файл не изменился и TTL не истёк — возвращает из памяти.
    """
    now = time.monotonic()

    with _lock:
        entry = _cache.get(path)
        if entry is not None:
            value, expires_at, cached_mtime = entry
            if now < expires_at:
                # Проверяем mtime — файл не изменился?
                try:
                    current_mtime = os.path.getmtime(path)
                    if current_mtime == cached_mtime:
                        return value
                    # Файл изменился — читаем заново
                except FileNotFoundError:
                    return default

    # Кэш промахнулся — читаем файл
    return _read_and_cache(path, now, default)


def _read_and_cache(path: str, now: float, default=None) -> Any:
    try:
        mtime = os.path.getmtime(path)
        with open(path, "r", encoding="utf-8") as f:
            value = json.load(f)
        ttl = _get_ttl(path)
        with _lock:
            _cache[path] = (value, now + ttl, mtime)
        return value
    except FileNotFoundError:
        return default
    except Exception as e:
        log.debug(f"[cache] read error {path}: {e}")
        return default


def invalidate(path: str):
    """Явная инвалидация после записи."""
    with _lock:
        _cache.pop(path, None)


def invalidate_prefix(prefix: str):
    """Инвалидирует все ключи начинающиеся с prefix."""
    with _lock:
        keys = [k for k in _cache if k.startswith(prefix)]
        for k in keys:
            del _cache[k]


def set_json(path: str, data: Any, atomic: bool = True):
    """
    Записывает JSON-файл и инвалидирует кэш.
    Atomic write по умолчанию — защита от повреждения при краше.
    """
    dir_ = os.path.dirname(path) or "."
    os.makedirs(dir_, exist_ok=True)

    if atomic:
        with tempfile.NamedTemporaryFile(
            "w", dir=dir_, delete=False, encoding="utf-8", suffix=".tmp"
        ) as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
            tmp = f.name
        os.replace(tmp, path)
    else:
        with open(path, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)

    # Сразу кладём в кэш свежее значение
    mtime = os.path.getmtime(path)
    ttl   = _get_ttl(path)
    now   = time.monotonic()
    with _lock:
        _cache[path] = (data, now + ttl, mtime)


def stats() -> dict:
    """Статистика кэша для диагностики."""
    with _lock:
        now = time.monotonic()
        valid   = sum(1 for _, (_, exp, _) in _cache.items() if exp > now)
        expired = len(_cache) - valid
    return {"total": len(_cache), "valid": valid, "expired": expired}


# ── Патч существующих модулей ────────────────────────────────────────
# Вместо полного рефакторинга — подменяем json.load в критичных местах

def patch_memory_module():
    """
    Патчит memory/memory.py: load_long_term использует кэш.
    Вызывать один раз при старте из main().
    """
    try:
        import memory.memory as mm

        _orig_load = mm.load_long_term

        def _cached_load_long_term():
            return get_json(mm.MEMORY_FILE, {"master": {}, "last_updated": None, "last_analysis": None})

        def _cached_save_long_term(data):
            set_json(mm.MEMORY_FILE, data)

        mm.load_long_term  = _cached_load_long_term
        mm.save_long_term  = _cached_save_long_term
        log.info("[cache] memory.memory патчен: load_long_term кэшируется 30с")
    except Exception as e:
        log.warning(f"[cache] patch_memory_module: {e}")


def patch_small_modules():
    """
    Патчит мелкие модули: rules, tasks, timeline, mood, context.
    Каждый получает кэшированное чтение.
    """
    patches = [
        ("modules.rules",    "RULES_FILE",    "_load_rules",    "_save_rules"),
        ("modules.tasks",    "TASKS_FILE",    "_load_tasks",    None),
        ("modules.timeline", "TIMELINE_FILE", "_load_timeline", "_save_timeline"),
    ]

    for mod_name, file_attr, load_fn, save_fn in patches:
        try:
            import importlib
            mod  = importlib.import_module(mod_name)
            path = getattr(mod, file_attr, None)
            if not path:
                continue

            orig_load = getattr(mod, load_fn, None)
            if orig_load:
                def make_cached(p, fn):
                    def cached(*args, **kwargs):
                        return get_json(p, {})
                    return cached
                setattr(mod, load_fn, make_cached(path, orig_load))

            if save_fn:
                orig_save = getattr(mod, save_fn, None)
                if orig_save:
                    def make_save(p, fn):
                        def cached_save(data):
                            set_json(p, data)
                        return cached_save
                    setattr(mod, save_fn, make_save(path, orig_save))

            log.debug(f"[cache] {mod_name} патчен")
        except Exception as e:
            log.debug(f"[cache] {mod_name} skip: {e}")


def patch_context_module():
    """
    Патчит context.py: get_full_context кэшируется на 3 секунды.
    Это самый частый вызов — происходит при каждом сообщении.
    """
    try:
        import modules.context as ctx_mod
        import time as _time

        _ctx_cache = {}
        _ctx_lock  = __import__("threading").Lock()

        orig_get_full_context = ctx_mod.get_full_context

        def cached_get_full_context(active_window_override=None):
            key = str(active_window_override)
            now = _time.monotonic()
            with _ctx_lock:
                entry = _ctx_cache.get(key)
                if entry and now < entry[1]:
                    return entry[0]
            result = orig_get_full_context(active_window_override)
            with _ctx_lock:
                _ctx_cache[key] = (result, now + 3.0)
                # Чистим старые ключи
                if len(_ctx_cache) > 20:
                    expired = [k for k, (_, exp) in _ctx_cache.items() if exp < now]
                    for k in expired:
                        del _ctx_cache[k]
            return result

        ctx_mod.get_full_context = cached_get_full_context
        log.info("[cache] context.get_full_context кэшируется 3с")
    except Exception as e:
        log.warning(f"[cache] patch_context_module: {e}")


def apply_all_patches():
    """Вызывать из main() один раз при старте."""
    patch_memory_module()
    patch_small_modules()
    patch_context_module()
    log.info("[cache] Все патчи применены.")