"""
modules/patterns.py — Привычки и паттерны Мастера.

Анализирует историю (episodes, window_watcher, music_memory) по дням недели
и времени суток. Извлекает повторяющиеся паттерны:
  - «по понедельникам ты обычно уставший»
  - «по вечерам ты всегда включаешь музыку»
  - «в субботу утром ты обычно в Terraria»

Инжектится в промпт как «ПРИВЫЧКИ: ...» — не как факты, а как понимание.
"""

import json
import logging
import os
from datetime import datetime, date
from typing import Optional

log = logging.getLogger("sakura.patterns")

PATTERNS_FILE = "memory/patterns.json"
_UPDATE_INTERVAL = 86400  # обновлять раз в день


def _load() -> dict:
    if not os.path.exists(PATTERNS_FILE):
        return {"patterns": [], "last_update": None}
    try:
        with open(PATTERNS_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {"patterns": [], "last_update": None}


def _save(data: dict):
    import tempfile
    dir_ = os.path.dirname(PATTERNS_FILE) or "."
    os.makedirs(dir_, exist_ok=True)
    with tempfile.NamedTemporaryFile("w", dir=dir_, delete=False,
                                    encoding="utf-8", suffix=".tmp") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
        tmp = f.name
    os.replace(tmp, PATTERNS_FILE)


def _should_update() -> bool:
    data = _load()
    last = data.get("last_update")
    if not last:
        return True
    try:
        last_dt = datetime.fromisoformat(last)
        return (datetime.now() - last_dt).total_seconds() > _UPDATE_INTERVAL
    except Exception:
        return True


def update_patterns():
    """
    Анализирует историю и извлекает паттерны.
    Вызывать из reflection_loop или при старте.
    """
    if not _should_update():
        return

    patterns = []

    # Паттерны из episodes
    try:
        from modules.episodes import get_recent_episodes
        eps = get_recent_episodes(limit=50)
        patterns += _extract_episode_patterns(eps)
    except Exception:
        pass

    # Паттерны из window_watcher
    try:
        from modules.window_watcher import get_session_summary
        ws = get_session_summary()
        patterns += _extract_window_patterns(ws)
    except Exception:
        pass

    # Паттерны из music_memory
    try:
        from modules.music_memory import get_top_tracks
        tracks = get_top_tracks(limit=20)
        patterns += _extract_music_patterns(tracks)
    except Exception:
        pass

    data = _load()
    data["patterns"] = patterns[:10]  # максимум 10 паттернов
    data["last_update"] = str(datetime.now())
    _save(data)

    if patterns:
        log.info(f"[patterns] Обновлено: {len(patterns)} паттернов")


def _extract_episode_patterns(eps: list) -> list:
    """Извлекает паттерны из эпизодов."""
    if not eps:
        return []

    patterns = []
    # Группируем по контексту (окно/тема)
    by_context = {}
    for ep in eps:
        ctx = ep.get("context", "")
        if ctx:
            by_context.setdefault(ctx, []).append(ep)

    for ctx, group in by_context.items():
        if len(group) >= 3:
            # Частый контекст = привычка
            emotion_counts = {}
            for ep in group:
                em = ep.get("emotion", "neutral")
                emotion_counts[em] = emotion_counts.get(em, 0) + 1
            dominant = max(emotion_counts, key=emotion_counts.get)
            patterns.append({
                "type": "context_habit",
                "context": ctx[:40],
                "emotion": dominant,
                "count": len(group),
                "hint": f"Часто бывает в «{ctx[:30]}» — обычно {dominant}",
            })

    return patterns


def _extract_window_patterns(ws: dict) -> list:
    """Извлекает паттерны из статистики окон."""
    patterns = []
    top_apps = ws.get("top_apps", [])

    for app in top_apps[:5]:
        window = app.get("window", "")
        minutes = app.get("minutes", 0)
        if minutes > 120:  # больше 2 часов = привычка
            patterns.append({
                "type": "app_habit",
                "window": window[:40],
                "minutes": minutes,
                "hint": f"Много времени в «{window[:30]}»",
            })

    return patterns


def _extract_music_patterns(tracks: list) -> list:
    """Извлекает паттерны из музыкального вкуса."""
    if not tracks:
        return []

    patterns = []
    # Группируем по исполнителю
    by_artist = {}
    for t in tracks:
        artist = t.get("artist", "")
        if artist:
            by_artist.setdefault(artist, []).append(t)

    for artist, group in by_artist.items():
        if len(group) >= 3:
            patterns.append({
                "type": "music_habit",
                "artist": artist[:40],
                "count": len(group),
                "hint": f"Любит音乐 от {artist}",
            })

    return patterns


def get_patterns_hint() -> str:
    """
    Строка для промпта — привычки Мастера.
    Обновляется раз в день.
    """
    if _should_update():
        try:
            update_patterns()
        except Exception:
            pass

    data = _load()
    patterns = data.get("patterns", [])

    if not patterns:
        return ""

    hints = [p.get("hint", "") for p in patterns[:5] if p.get("hint")]
    if not hints:
        return ""

    return "ПРИВЫЧКИ МАСТЕРА: " + "; ".join(hints)
