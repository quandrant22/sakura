"""
modules/music_memory.py — память прослушиваний + вкус Сакуры.
Записывает треки, позволяет запрашивать статистику.
Сакура формирует собственные предпочтения.
"""

import json
import logging
import os
import random
import time
from collections import Counter
from datetime import datetime, timedelta

log = logging.getLogger(__name__)

HISTORY_FILE = "memory/music_history.json"
TASTE_FILE = "memory/sakura_taste.json"
MAX_ENTRIES = 5000


def _load() -> list[dict]:
    if os.path.exists(HISTORY_FILE):
        with open(HISTORY_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    return []


def _save(history: list[dict]):
    os.makedirs(os.path.dirname(HISTORY_FILE), exist_ok=True)
    # Обрезаем до MAX_ENTRIES
    if len(history) > MAX_ENTRIES:
        history = history[-MAX_ENTRIES:]
    with open(HISTORY_FILE, "w", encoding="utf-8") as f:
        json.dump(history, f, ensure_ascii=False)


def track_play(artist: str, title: str, album: str = ""):
    """Записывает прослушивание трека."""
    history = _load()
    entry = {
        "artist": artist,
        "title": title,
        "album": album,
        "timestamp": datetime.now().isoformat(),
    }
    history.append(entry)
    _save(history)
    log.debug(f"[music_memory] tracked: {artist} — {title}")


def get_recent(hours: int = 24, limit: int = 10) -> list[dict]:
    """Возвращает недавние треки за N часов."""
    cutoff = datetime.now() - timedelta(hours=hours)
    history = _load()
    recent = [
        h for h in history
        if datetime.fromisoformat(h["timestamp"]) > cutoff
    ]
    return recent[-limit:]


def get_top_artists(days: int = 7, limit: int = 5) -> list[tuple[str, int]]:
    """Топ исполнителей за N дней."""
    cutoff = datetime.now() - timedelta(days=days)
    history = _load()
    artists = Counter()
    for h in history:
        if datetime.fromisoformat(h["timestamp"]) > cutoff:
            artists[h["artist"]] += 1
    return artists.most_common(limit)


def get_top_tracks(days: int = 7, limit: int = 5) -> list[tuple[str, int]]:
    """Топ треков за N дней."""
    cutoff = datetime.now() - timedelta(days=days)
    history = _load()
    tracks = Counter()
    for h in history:
        if datetime.fromisoformat(h["timestamp"]) > cutoff:
            key = f"{h['artist']} — {h['title']}"
            tracks[key] += 1
    return tracks.most_common(limit)


def get_stats(days: int = 7) -> dict:
    """Общая статистика за N дней."""
    cutoff = datetime.now() - timedelta(days=days)
    history = _load()
    recent = [h for h in history if datetime.fromisoformat(h["timestamp"]) > cutoff]
    if not recent:
        return {"total": 0, "artists": 0, "tracks": 0}

    artists = set()
    tracks = set()
    for h in recent:
        artists.add(h["artist"])
        tracks.add(f"{h['artist']} — {h['title']}")

    return {
        "total": len(recent),
        "artists": len(artists),
        "tracks": len(tracks),
    }


def format_recent(hours: int = 24) -> str:
    """Форматирует список недавних треков."""
    recent = get_recent(hours=hours, limit=15)
    if not recent:
        return "Нет данных о прослушиваниях."
    lines = []
    for h in reversed(recent):
        ts = datetime.fromisoformat(h["timestamp"]).strftime("%H:%M")
        lines.append(f"• {ts} — {h['artist']} — {h['title']}")
    return "\n".join(lines)


def format_top(days: int = 7) -> str:
    """Форматирует топ треков/исполнителей."""
    stats = get_stats(days)
    if stats["total"] == 0:
        return "Нет данных за этот период."

    top_artists = get_top_artists(days, 5)
    top_tracks = get_top_tracks(days, 5)

    lines = [f"За {days} дн.: {stats['total']} прослушиваний, {stats['artists']} исполнителей"]
    if top_artists:
        lines.append("\nТоп исполнителей:")
        for artist, count in top_artists:
            lines.append(f"  • {artist} — {count} раз")
    if top_tracks:
        lines.append("\nТоп треков:")
        for track, count in top_tracks:
            lines.append(f"  • {track} — {count} раз")
    return "\n".join(lines)


# ── Вкус Сакуры ───────────────────────────────────────────────────

def _load_taste() -> dict:
    if os.path.exists(TASTE_FILE):
        with open(TASTE_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    return {
        "favorites": {},      # artist → {"count": N, "first": date, "note": str}
        "dislikes": {},       # artist → {"count": N, "first": date, "note": str}
        "genres_loved": {},   # genre → count
        "genres_hated": {},   # genre → count
    }


def _save_taste(taste: dict):
    os.makedirs(os.path.dirname(TASTE_FILE), exist_ok=True)
    with open(TASTE_FILE, "w", encoding="utf-8") as f:
        json.dump(taste, f, ensure_ascii=False, indent=2)


def like_artist(artist: str, note: str = ""):
    """Сакура полюбила исполнителя (по реакции Мастера)."""
    taste = _load_taste()
    if artist not in taste["favorites"]:
        taste["favorites"][artist] = {
            "count": 0,
            "first": datetime.now().isoformat(),
            "note": note,
        }
    taste["favorites"][artist]["count"] += 1
    if note:
        taste["favorites"][artist]["note"] = note
    # Убираем из dislikes если был
    taste["dislikes"].pop(artist, None)
    _save_taste(taste)
    log.info(f"[music_taste] liked: {artist}")


def dislike_artist(artist: str, note: str = ""):
    """Сакура разлюбила исполнителя."""
    taste = _load_taste()
    if artist not in taste["dislikes"]:
        taste["dislikes"][artist] = {
            "count": 0,
            "first": datetime.now().isoformat(),
            "note": note,
        }
    taste["dislikes"][artist]["count"] += 1
    if note:
        taste["dislikes"][artist]["note"] = note
    # Убираем из favorites если был
    taste["favorites"].pop(artist, None)
    _save_taste(taste)
    log.info(f"[music_taste] disliked: {artist}")


def get_favorites(limit: int = 5) -> list[dict]:
    """Топ любимых исполнителей Сакуры."""
    taste = _load_taste()
    favs = taste.get("favorites", {})
    sorted_favs = sorted(favs.items(), key=lambda x: x[1]["count"], reverse=True)
    return [{"artist": a, **info} for a, info in sorted_favs[:limit]]


def get_dislikes(limit: int = 5) -> list[dict]:
    """Топ нелюбимых исполнителей."""
    taste = _load_taste()
    dislikes = taste.get("dislikes", {})
    sorted_d = sorted(dislikes.items(), key=lambda x: x[1]["count"], reverse=True)
    return [{"artist": a, **info} for a, info in sorted_d[:limit]]


def has_opinion(artist: str) -> str | None:
    """Проверяет, есть ли у Сакуры мнение об исполнителе."""
    taste = _load_taste()
    if artist in taste.get("favorites", {}):
        return "favorite"
    if artist in taste.get("dislikes", {}):
        return "dislike"
    return None


def get_taste_context() -> str:
    """Контекст вкуса Сакуры для промпта."""
    taste = _load_taste()
    favs = taste.get("favorites", {})
    dislikes = taste.get("dislikes", {})

    parts = []
    if favs:
        top3 = sorted(favs.items(), key=lambda x: x[1]["count"], reverse=True)[:3]
        names = [a for a, _ in top3]
        parts.append(f"Любимые исполнители: {', '.join(names)}")
    if dislikes:
        top3 = sorted(dislikes.items(), key=lambda x: x[1]["count"], reverse=True)[:3]
        names = [a for a, _ in top3]
        parts.append(f"Не люблю: {', '.join(names)}")

    if not parts:
        return ""
    return "МУЗЫКАЛЬНЫЙ ВКУС САКУРЫ:\n" + "\n".join(parts)


def generate_taste_comment(artist: str) -> str | None:
    """Генерирует комментарий Сакуры об исполнителе на основе её вкуса."""
    opinion = has_opinion(artist)
    taste = _load_taste()

    if opinion == "favorite":
        fav = taste["favorites"][artist]
        count = fav["count"]
        if count >= 10:
            templates = [
                f"О, {artist}! Один из моих любимых. Слушаю постоянно.",
                f"{artist} — это да. Мне этот звук очень заходит.",
                f"Обожаю {artist}. Каждый трек — огонь.",
            ]
        else:
            templates = [
                f"{artist} мне нравится. Приятный.",
                f"О, {artist} — хороший выбор.",
                f"{artist} — мне заходит, да.",
            ]
        return random.choice(templates)

    if opinion == "dislike":
        dislike = taste["dislikes"][artist]
        count = dislike["count"]
        if count >= 5:
            templates = [
                f"Опять {artist}... Мне не нравится, честно.",
                f"{artist} — не моя тема. Вообще.",
                f"Уважаю твой вкус, но {artist} — нет.",
            ]
        else:
            templates = [
                f"{artist} — ну, не мой вкус.",
                f"Хм, {artist}. Не заходит мне.",
                f"{artist} — не то чтобы плохо, просто не моё.",
            ]
        return random.choice(templates)

    return None
