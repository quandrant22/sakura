"""
modules/integrations.py — Внешние интеграции (бэклоги №28, №30).

№28: Steam ачивки — через Steam API получаем новые ачивки и реагируем живо.
     Требует STEAM_ID и STEAM_KEY в .env.

№30: Совместное слушание музыки — Сакура знает что играет (через
     Yandex Music или Last.fm) и комментирует не по запросу.
"""

import asyncio
import json
import logging
import time
import urllib.request
import urllib.parse
from typing import Optional

log = logging.getLogger("sakura.integrations")

# ── №28: Steam ───────────────────────────────────────────────────────

_steam_cache: dict = {}
_STEAM_COOLDOWN = 300   # 5 минут между проверками


def _get_steam_config():
    try:
        from config import STEAM_ID, STEAM_KEY
        return STEAM_ID, STEAM_KEY
    except ImportError:
        return None, None


async def check_new_achievements() -> Optional[dict]:
    """
    Проверяет новые ачивки в Steam.
    Возвращает {game, achievement, description} или None.
    """
    steam_id, steam_key = _get_steam_config()
    if not steam_id or not steam_key:
        return None

    now = time.monotonic()
    if now - _steam_cache.get("last_check", 0) < _STEAM_COOLDOWN:
        return None
    _steam_cache["last_check"] = now

    try:
        # Получаем недавно сыгранные игры
        url = (
            f"http://api.steampowered.com/IPlayerService/GetRecentlyPlayedGames/v0001/"
            f"?key={steam_key}&steamid={steam_id}&count=1&format=json"
        )
        data = await asyncio.to_thread(_fetch_json, url)
        games = data.get("response", {}).get("games", [])
        if not games:
            return None

        game = games[0]
        app_id   = game["appid"]
        app_name = game.get("name", "игра")

        # Получаем ачивки
        url2 = (
            f"http://api.steampowered.com/ISteamUserStats/GetPlayerAchievements/v0001/"
            f"?appid={app_id}&key={steam_key}&steamid={steam_id}&format=json&l=russian"
        )
        data2 = await asyncio.to_thread(_fetch_json, url2)
        achievements = data2.get("playerstats", {}).get("achievements", [])

        # Ищем только что полученные (unlocktime в последние 5 минут)
        recent_cutoff = time.time() - 300
        new_ach = [
            a for a in achievements
            if a.get("achieved") == 1 and a.get("unlocktime", 0) > recent_cutoff
        ]

        if not new_ach:
            return None

        ach = new_ach[0]
        result = {
            "game":        app_name,
            "achievement": ach.get("name", "достижение"),
            "description": ach.get("description", ""),
        }
        log.info(f"[steam] Новая ачивка: {result}")
        return result

    except Exception as e:
        log.debug(f"[steam] {e}")
        return None


def make_achievement_prompt(ach: dict) -> str:
    """Промпт для реакции Сакуры на ачивку."""
    desc = f" ({ach['description']})" if ach['description'] else ""
    return (
        f"Мастер только что получил ачивку «{ach['achievement']}»{desc} "
        f"в игре «{ach['game']}». "
        "Отреагируй живо — одна фраза, как подруга которая следила за игрой. "
        "Не «поздравляю», а что-то своё."
    )


# ── №30: Музыка ───────────────────────────────────────────────────────

_music_cache: dict = {}
_MUSIC_COOLDOWN  = 120   # 2 минуты
_COMMENT_COOLDOWN = 3600  # не комментируем чаще раза в час
_last_music_comment = 0.0


def get_current_music_from_window(active_window: str) -> Optional[str]:
    """
    Пытается определить что играет по названию активного окна.
    Работает для Spotify, VLC, YouTube Music, Яндекс Музыки.
    """
    wl = active_window.lower()

    # Spotify: "Artist - Song - Spotify"
    if "spotify" in wl:
        parts = active_window.split(" - ")
        if len(parts) >= 2:
            track = " - ".join(parts[:-1]).strip()
            if track and len(track) > 3:
                return track

    # YouTube Music / YouTube: ищем паттерн в заголовке
    if "youtube" in wl:
        # Убираем "- YouTube"
        track = active_window.replace("- YouTube", "").strip()
        if track and len(track) > 5:
            return track

    # Яндекс Музыка: "Исполнитель — Название — Яндекс Музыка"
    if "яндекс" in wl and "музык" in wl:
        parts = active_window.split("—")
        if len(parts) >= 3:
            artist = parts[0].strip()
            title = parts[1].strip()
            return f"{artist} — {title}"
        if len(parts) == 2:
            return parts[0].strip()
        # Альтернативный формат: "Название - Исполнитель"
        parts = active_window.split(" - ")
        if len(parts) >= 2:
            last = parts[-1].strip()
            if "яндекс" in last.lower() or "музык" in last.lower():
                return " - ".join(parts[:-1]).strip()
            return parts[0].strip()

    # VLC: "filename.mp3 - VLC"
    if "vlc" in wl:
        track = active_window.replace("- VLC media player", "").strip()
        if track and len(track) > 3:
            return track

    # MPC-HC / MPC-BE: "filename.mp3 - MPC-HC"
    if "mpc" in wl:
        parts = active_window.split(" - ")
        if len(parts) >= 2:
            return parts[0].strip()

    # foobar2000: "Artist - Title - foobar2000"
    if "foobar" in wl:
        parts = active_window.split(" - ")
        if len(parts) >= 2:
            return " - ".join(parts[:-1]).strip()

    return None


def should_comment_music() -> bool:
    """True если пора прокомментировать музыку."""
    import random
    global _last_music_comment
    now = time.monotonic()
    if now - _last_music_comment < _COMMENT_COOLDOWN:
        return False
    return random.random() < 0.12   # 12% шанс


def make_music_comment_prompt(track: str, memory_context: str = "",
                               genre: str = "", album: str = "",
                               year: int | None = None) -> str:
    """Промпт для комментария о музыке с обогащённым контекстом."""
    extra = ""
    if genre:
        extra += f"Жанр: {genre}. "
    if album:
        extra += f"Альбом: {album}"
        if year:
            extra += f" ({year})"
        extra += ". "

    return (
        f"Сейчас играет: «{track}».\n"
        f"{extra}"
        f"{memory_context}\n\n"
        "Сакура заметила что Мастер слушает эту музыку и хочет прокомментировать "
        "БЕЗ ЗАПРОСА — одна фраза. Не 'о, хороший трек', а что-то своё: "
        "связь с его настроением, воспоминание, наблюдение, знание жанра или исполнителя. "
        "Может спросить почему именно это сейчас."
    )


def mark_music_commented():
    global _last_music_comment
    _last_music_comment = time.monotonic()


def _fetch_json(url: str) -> dict:
    with urllib.request.urlopen(url, timeout=5) as r:
        return json.loads(r.read().decode())