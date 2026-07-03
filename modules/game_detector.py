"""
modules/game_detector.py — идентификация игры + реакция на события (бэклог №1).

Уровень 1 (был): скриншот → название/жанр/атмосфера → кэш 5 мин.
Уровень 2 (новый): периодический vision-тик для одиночных игр →
  детект событий (смерть, победа, босс, кат-сцена) → реактивный комментарий.

Принципы под ограничения:
  • Тик только если is_game=True и жанр не в SKIP_GENRES (мультиплеер/соревновательные)
  • Интервал: EVENT_INTERVAL секунд (по умолчанию 90с — ~2 Vision-запроса в 3 минуты)
  • Не комментируем каждый тик — только если детектировано событие
  • Один активный тик на устройство (нет накопления задач)

Квота: при EVENT_INTERVAL=90 и 6 часах игры = 240 Vision-запросов/день.
  Gemini Flash Vision — отдельный лимит от текстового LLM.
  Уменьши EVENT_INTERVAL если квота давит.
"""

import asyncio
import base64
import json
import logging
import time
from typing import Optional

log = logging.getLogger("sakura.game_detector")

# Кэш: device_id → {game, genre, mood, detected_at}
_cache: dict = {}
_CACHE_TTL   = 300  # 5 минут

# Состояние периодического тика: device_id → {last_event_check, last_event_type}
_event_state: dict = {}

# Жанры, для которых НЕ запускаем event-тик (мультиплеер / соревновательные)
# — риск анти-чит детекции, плюс там события слишком частые и бессмысленные
SKIP_GENRES = {"racing", "unknown"}

# Интервал между event-тиками (секунды)
EVENT_INTERVAL = 90

# Жанры и их цветовые темы для overlay
GENRE_THEMES = {
    "horror":    {"color": "#4a0a0a", "orb": "#8b0000", "pulse": 0.12},
    "action":    {"color": "#0a1a2a", "orb": "#ff4500", "pulse": 0.10},
    "rpg":       {"color": "#0a0a1a", "orb": "#6a0dad", "pulse": 0.06},
    "strategy":  {"color": "#0a1a0a", "orb": "#006400", "pulse": 0.04},
    "racing":    {"color": "#1a1a00", "orb": "#ffd700", "pulse": 0.11},
    "simulator": {"color": "#0a0a0a", "orb": "#4169e1", "pulse": 0.05},
    "indie":     {"color": "#1a0a1a", "orb": "#ff69b4", "pulse": 0.07},
    "unknown":   {"color": "#0a0a0a", "orb": "#9a7fb5", "pulse": 0.05},
}

# Настроение Сакуры по жанру
GENRE_MOOD = {
    "horror":    {"valence": -0.2, "arousal": 0.7},
    "action":    {"valence":  0.4, "arousal": 0.8},
    "rpg":       {"valence":  0.3, "arousal": 0.4},
    "strategy":  {"valence":  0.1, "arousal": 0.3},
    "racing":    {"valence":  0.5, "arousal": 0.9},
    "simulator": {"valence":  0.2, "arousal": 0.3},
    "indie":     {"valence":  0.4, "arousal": 0.5},
    "unknown":   {"valence":  0.0, "arousal": 0.3},
}

# Типы событий и их эмоциональный вес для настроения Сакуры
_EVENT_MOOD = {
    "death":    {"valence": -0.3, "arousal": 0.6},
    "victory":  {"valence":  0.6, "arousal": 0.8},
    "boss":     {"valence":  0.1, "arousal": 0.9},
    "cutscene": {"valence":  0.2, "arousal": 0.4},
    "loading":  None,   # не комментируем
    "none":     None,
}


def get_cached_game(device_id: str) -> Optional[dict]:
    entry = _cache.get(device_id)
    if entry and time.monotonic() - entry["detected_at"] < _CACHE_TTL:
        return entry
    return None


async def detect_game_from_screenshot(
    screenshot_b64: str,
    active_window: str,
    device_id: str,
) -> dict:
    """
    Анализирует скриншот через Gemini Vision.
    Возвращает: {game, genre, mood_hint, theme, is_game}
    """
    cached = get_cached_game(device_id)
    if cached and cached.get("window") == active_window:
        return cached

    from config import get_active_key, mark_key_used
    from google import genai
    from google.genai import types

    key = get_active_key()
    if not key:
        return _unknown(active_window, device_id)

    try:
        img_bytes = base64.b64decode(screenshot_b64)
        client    = genai.Client(api_key=key)
        prompt    = (
            "Посмотри на скриншот и определи:\n"
            "1. Это игра или нет?\n"
            "2. Если игра — точное название\n"
            "3. Жанр (horror/action/rpg/strategy/racing/simulator/indie/unknown)\n"
            "4. Одним словом: атмосфера (мрачная/динамичная/спокойная/напряжённая/весёлая)\n\n"
            f"Активное окно: {active_window}\n\n"
            "Ответь ТОЛЬКО в JSON без markdown:\n"
            '{"is_game": true/false, "name": "название или null", '
            '"genre": "жанр", "atmosphere": "атмосфера"}'
        )
        response = await asyncio.to_thread(
            client.models.generate_content,
            model="gemini-3.1-flash-lite",
            contents=[types.Content(parts=[
                types.Part(inline_data=types.Blob(mime_type="image/jpeg", data=img_bytes)),
                types.Part(text=prompt),
            ])]
        )
        mark_key_used(key)

        raw  = (response.text or "").strip().replace("```json", "").replace("```", "").strip()
        data = json.loads(raw)

        result = {
            "is_game":    data.get("is_game", False),
            "game":       data.get("name"),
            "genre":      data.get("genre", "unknown"),
            "atmosphere": data.get("atmosphere", ""),
            "window":     active_window,
            "theme":      GENRE_THEMES.get(data.get("genre", "unknown"), GENRE_THEMES["unknown"]),
            "mood_hint":  GENRE_MOOD.get(data.get("genre", "unknown"),   GENRE_MOOD["unknown"]),
            "detected_at": time.monotonic(),
        }
        _cache[device_id] = result
        log.info(f"[game] {result['game']} ({result['genre']}) — {result['atmosphere']}")
        return result

    except Exception as e:
        log.error(f"[game] Vision ошибка: {e}")
        return _unknown(active_window, device_id)


def _unknown(window: str, device_id: str) -> dict:
    return {
        "is_game": False, "game": None, "genre": "unknown",
        "atmosphere": "", "window": window,
        "theme":     GENRE_THEMES["unknown"],
        "mood_hint": GENRE_MOOD["unknown"],
        "detected_at": time.monotonic(),
    }


def get_game_context(device_id: str) -> str:
    entry = get_cached_game(device_id)
    if not entry or not entry.get("is_game"):
        return ""
    game  = entry.get("game", "")
    genre = entry.get("genre", "")
    atm   = entry.get("atmosphere", "")
    if not game:
        return ""
    return (
        f"ИГРОВОЙ КОНТЕКСТ: Мастер играет в «{game}» (жанр: {genre}, атмосфера: {atm}). "
        f"Учитывай это в тоне ответов."
    )


# ── Реакция на события игры (уровень 2) ──────────────────────────────

def should_check_event(device_id: str) -> bool:
    """True если пора делать event-тик для этого устройства."""
    cached = get_cached_game(device_id)
    if not cached or not cached.get("is_game"):
        return False
    genre = cached.get("genre", "unknown")
    if genre in SKIP_GENRES:
        return False
    state    = _event_state.get(device_id, {})
    last_t   = state.get("last_event_check", 0)
    return time.monotonic() - last_t >= EVENT_INTERVAL


async def detect_game_event(
    screenshot_b64: str,
    device_id: str,
) -> Optional[dict]:
    """
    Анализирует скриншот на предмет игрового события.
    Возвращает {"event": str, "description": str} или None если событий нет.

    event: "death" | "victory" | "boss" | "cutscene" | "loading" | "none"
    """
    _event_state.setdefault(device_id, {})
    _event_state[device_id]["last_event_check"] = time.monotonic()

    from config import get_active_key, mark_key_used
    from google import genai
    from google.genai import types

    key = get_active_key()
    if not key:
        return None

    cached     = get_cached_game(device_id)
    game_name  = cached.get("game", "игра") if cached else "игра"

    try:
        img_bytes = base64.b64decode(screenshot_b64)
        client    = genai.Client(api_key=key)
        prompt    = (
            f"Игра: {game_name}\n\n"
            "Посмотри на скриншот и определи, произошло ли ПРЯМО СЕЙЧАС значимое событие:\n"
            "• death — экран смерти/поражения/game over\n"
            "• victory — победа/уровень пройден/босс убит/квест выполнен\n"
            "• boss — начало боя с боссом (характерный UI/экран)\n"
            "• cutscene — катсцена/диалог\n"
            "• loading — экран загрузки\n"
            "• none — обычный геймплей, ничего особенного\n\n"
            "Ответь ТОЛЬКО в JSON без markdown:\n"
            '{"event": "тип", "description": "одно предложение что происходит"}\n'
            'Если none — description пустая строка.'
        )
        response = await asyncio.to_thread(
            client.models.generate_content,
            model="gemini-3.1-flash-lite",
            contents=[types.Content(parts=[
                types.Part(inline_data=types.Blob(mime_type="image/jpeg", data=img_bytes)),
                types.Part(text=prompt),
            ])]
        )
        mark_key_used(key)

        raw  = (response.text or "").strip().replace("```json", "").replace("```", "").strip()
        data = json.loads(raw)
        event_type = data.get("event", "none")

        # Не репортим loading и none
        if event_type in ("none", "loading"):
            return None

        # Не репортим одно и то же событие подряд (дебаунс)
        last_event = _event_state[device_id].get("last_event_type")
        if last_event == event_type:
            return None

        _event_state[device_id]["last_event_type"] = event_type

        # Обновляем настроение Сакуры под событие
        mood_shift = _EVENT_MOOD.get(event_type)
        if mood_shift:
            try:
                from modules.mood_vector import set_target
                set_target(mood_shift["valence"], mood_shift["arousal"], blend=0.3)
            except Exception:
                pass

        log.info(f"[game_event] {device_id}: {event_type} — {data.get('description','')}")
        return {
            "event":       event_type,
            "description": data.get("description", ""),
            "game":        game_name,
        }

    except Exception as e:
        log.debug(f"[game_event] Vision: {e}")
        return None


def make_event_prompt(event: dict) -> str:
    """Промпт для Gemini — реактивный комментарий на игровое событие."""
    game  = event.get("game", "игра")
    etype = event.get("event", "")
    desc  = event.get("description", "")

    templates = {
        "death":   (
            f"Мастер только что погиб в «{game}». {desc} "
            "Один короткий комментарий — сочувственный или подбадривающий, без банальщины. "
            "Максимум одно предложение."
        ),
        "victory": (
            f"Мастер победил в «{game}»! {desc} "
            "Один короткий комментарий — живая радость, можно с подколом. "
            "Максимум одно предложение."
        ),
        "boss":    (
            f"В «{game}» начался бой с боссом. {desc} "
            "Один короткий комментарий — напряжённый, подбадривающий. "
            "Максимум одно предложение."
        ),
        "cutscene": (
            f"В «{game}» идёт катсцена. {desc} "
            "Один тихий комментарий — наблюдение, можно интригующее. "
            "Максимум одно предложение."
        ),
    }
    return templates.get(etype, f"Событие в «{game}»: {desc}. Прокомментируй коротко.")