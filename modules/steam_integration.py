"""
modules/steam_integration.py — полная интеграция со Steam.

Ключевые улучшения:
  - Вся библиотека хранится в SQLite (таблица steam_games) — не теряется при перезапуске
  - Умный поиск по имени с учётом опечаток и склонений
  - format_library_context показывает топ-20 + все неначатые одной строкой
  - search_game(query) — найти игру по частичному названию
  - 8AM и подобные «игры» из других лаунчеров не попадают в библиотеку
    (фильтруем по наличию нормального названия)
"""

import asyncio
import difflib
import json
import logging
import time
import urllib.request
import urllib.parse
from typing import Optional

log = logging.getLogger("sakura.steam")

# RAM-кэш поверх SQLite (для быстрого доступа без SQL в горячем пути)
_library:    list[dict]   = []
_library_at: float        = 0.0
_LIBRARY_TTL              = 3600 * 6   # обновляем раз в 6 часов

_current_game: Optional[dict] = None
_achievements_cache: dict     = {}


def _get_config():
    try:
        from config import STEAM_KEY, STEAM_ID
        return STEAM_KEY, STEAM_ID
    except Exception:
        return "", ""


def _fetch(url: str) -> Optional[dict]:
    try:
        with urllib.request.urlopen(url, timeout=8) as r:
            return json.loads(r.read().decode())
    except Exception as e:
        log.debug(f"[steam] fetch error: {e}")
        return None


# ── SQLite хранилище ──────────────────────────────────────────────────

def _ensure_table():
    from memory.db import _conn
    conn = _conn()
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS steam_games (
            appid           INTEGER PRIMARY KEY,
            name            TEXT    NOT NULL,
            playtime_forever INTEGER NOT NULL DEFAULT 0,
            playtime_2weeks  INTEGER NOT NULL DEFAULT 0,
            img_icon_url    TEXT,
            updated_at      TEXT    NOT NULL DEFAULT (datetime('now'))
        );
        CREATE INDEX IF NOT EXISTS idx_steam_playtime ON steam_games(playtime_forever DESC);
        CREATE INDEX IF NOT EXISTS idx_steam_name     ON steam_games(name);
    """)
    conn.commit()


def _save_to_db(games: list[dict]):
    """Сохраняет/обновляет всю библиотеку в SQLite."""
    try:
        _ensure_table()
        from memory.db import _conn
        conn = _conn()
        for g in games:
            conn.execute("""
                INSERT INTO steam_games(appid, name, playtime_forever, playtime_2weeks, img_icon_url)
                VALUES(?, ?, ?, ?, ?)
                ON CONFLICT(appid) DO UPDATE SET
                    name=excluded.name,
                    playtime_forever=excluded.playtime_forever,
                    playtime_2weeks=excluded.playtime_2weeks,
                    img_icon_url=excluded.img_icon_url,
                    updated_at=datetime('now')
            """, (
                g.get("appid"),
                g.get("name", ""),
                g.get("playtime_forever", 0),
                g.get("playtime_2weeks", 0),
                g.get("img_icon_url", ""),
            ))
        conn.commit()
        log.info(f"[steam] Сохранено в БД: {len(games)} игр")
    except Exception as e:
        log.error(f"[steam] DB save error: {e}")


def _load_from_db() -> list[dict]:
    """Загружает библиотеку из SQLite."""
    try:
        _ensure_table()
        from memory.db import _conn
        rows = _conn().execute(
            "SELECT appid, name, playtime_forever, playtime_2weeks, img_icon_url "
            "FROM steam_games ORDER BY playtime_forever DESC"
        ).fetchall()
        return [dict(r) for r in rows]
    except Exception as e:
        log.error(f"[steam] DB load error: {e}")
        return []


# ── Библиотека ────────────────────────────────────────────────────────

def _is_real_game(game: dict) -> bool:
    """
    Фильтрует технические записи (инструменты, SDK, демки с кривыми именами).
    8AM, Steamworks, DirectX и подобное — не игры.
    """
    name = game.get("name", "").strip()
    if not name or len(name) < 2:
        return False
    bad = ("sdk", "steamworks", "directx", "redistributable",
           "appid", "tool", "8am", "proton", "steam linux")
    nl = name.lower()
    return not any(b in nl for b in bad)


async def load_library(force: bool = False) -> list[dict]:
    """Загружает библиотеку: сначала из БД, потом синхронизирует с API."""
    global _library, _library_at

    # Из RAM-кэша если свежий
    if _library and not force and time.monotonic() - _library_at < _LIBRARY_TTL:
        return _library

    # Из SQLite (мгновенно, без сети)
    db_games = _load_from_db()
    if db_games:
        _library = db_games
        _library_at = time.monotonic()
        log.info(f"[steam] Из БД: {len(_library)} игр")

    # Фоновая синхронизация с API
    asyncio.create_task(_sync_from_api())
    return _library


async def _sync_from_api():
    """Обновляет библиотеку из Steam API и сохраняет в БД."""
    global _library, _library_at
    key, sid = _get_config()
    if not key or not sid:
        return

    url = (
        f"http://api.steampowered.com/IPlayerService/GetOwnedGames/v0001/"
        f"?key={key}&steamid={sid}&include_appinfo=true"
        f"&include_played_free_games=true&format=json"
    )
    data = await asyncio.to_thread(_fetch, url)
    if not data:
        return

    games = data.get("response", {}).get("games", [])
    games = [g for g in games if _is_real_game(g)]
    games = sorted(games, key=lambda g: g.get("playtime_forever", 0), reverse=True)

    _save_to_db(games)
    _library = games
    _library_at = time.monotonic()
    log.info(f"[steam] API sync: {len(_library)} игр")


def get_library() -> list[dict]:
    return _library


# ── Поиск игры ────────────────────────────────────────────────────────

def search_game(query: str) -> Optional[dict]:
    """
    Ищет игру в библиотеке по частичному названию.
    Порядок: точное совпадение → вхождение → fuzzy.
    Используется когда Мастер спрашивает об игре по имени.
    """
    if not query or not _library:
        return None
    q = query.lower().strip()

    # 1. Точное совпадение
    for g in _library:
        if g.get("name", "").lower() == q:
            return g

    # 2. Вхождение (название содержит запрос или наоборот)
    for g in _library:
        name = g.get("name", "").lower()
        if q in name or name in q:
            return g

    # 3. Fuzzy — ближайшее по схожести
    names = [g.get("name", "") for g in _library]
    matches = difflib.get_close_matches(query, names, n=1, cutoff=0.55)
    if matches:
        return next((g for g in _library if g.get("name") == matches[0]), None)

    return None


def find_game_by_window(active_window: str) -> Optional[dict]:
    """Определяет текущую игру по заголовку активного окна."""
    if not active_window or not _library:
        return None
    wl = active_window.lower()

    for game in _library:
        name = game.get("name", "").lower()
        if name and (name in wl or wl in name):
            return game

    for game in _library:
        name = game.get("name", "").lower()
        words = [w for w in name.split()[:4] if len(w) > 3]
        if words and all(w in wl for w in words):
            return game

    return None


async def get_current_game(active_window: str) -> Optional[dict]:
    global _current_game
    game = find_game_by_window(active_window)
    if game != _current_game:
        _current_game = game
        if game:
            log.info(f"[steam] Текущая игра: {game['name']}")
    return game


# ── Достижения ────────────────────────────────────────────────────────

async def get_achievements(app_id: int) -> list[dict]:
    if app_id in _achievements_cache:
        return _achievements_cache[app_id]
    key, sid = _get_config()
    if not key or not sid:
        return []
    url = (
        f"http://api.steampowered.com/ISteamUserStats/GetPlayerAchievements/v0001/"
        f"?appid={app_id}&key={key}&steamid={sid}&format=json&l=russian"
    )
    data = await asyncio.to_thread(_fetch, url)
    if not data:
        return []
    achievements = data.get("playerstats", {}).get("achievements", [])
    _achievements_cache[app_id] = achievements
    return achievements


async def get_achievement_stats(app_id: int) -> dict:
    achievements = await get_achievements(app_id)
    if not achievements:
        return {}
    total    = len(achievements)
    unlocked = sum(1 for a in achievements if a.get("achieved") == 1)
    recent   = sorted(
        [a for a in achievements if a.get("achieved") == 1],
        key=lambda a: a.get("unlocktime", 0), reverse=True
    )[:3]
    return {
        "total": total, "unlocked": unlocked,
        "percent": round(unlocked / total * 100) if total else 0,
        "recent": recent,
    }


# ── Рекомендации ──────────────────────────────────────────────────────

async def recommend_games(mood: str = "neutral", limit: int = 5,
                           exclude_current: bool = True) -> list[dict]:
    if not _library:
        await load_library()

    games = list(_library)
    if exclude_current and _current_game:
        games = [g for g in games if g.get("appid") != _current_game.get("appid")]

    played   = [g for g in games if g.get("playtime_forever", 0) > 60]
    unplayed = [g for g in games if g.get("playtime_forever", 0) == 0]

    result = played[:limit-1] + unplayed[:1] if played else games[:limit]
    return result[:limit]


# ── Контекст для промпта ──────────────────────────────────────────────

def format_library_context() -> str:
    """
    Полный контекст библиотеки для системного промпта.
    Топ-20 по времени + все неначатые одной строкой.
    """
    if not _library:
        return ""

    played   = [g for g in _library if g.get("playtime_forever", 0) > 0]
    unplayed = [g for g in _library if g.get("playtime_forever", 0) == 0]

    lines = [f"STEAM БИБЛИОТЕКА ({len(_library)} игр):"]

    # Топ-20 с временем
    lines.append("Наиграно:")
    for g in played[:20]:
        h = g.get("playtime_forever", 0) // 60
        lines.append(f"  • {g['name']} ({h}ч)")

    # Неначатые — одной строкой чтобы не раздувать промпт
    if unplayed:
        names = ", ".join(g["name"] for g in unplayed[:15])
        suffix = f" и ещё {len(unplayed)-15}" if len(unplayed) > 15 else ""
        lines.append(f"Не запускались: {names}{suffix}")

    # Недавно играл (playtime_2weeks > 0)
    recent = [g for g in _library if g.get("playtime_2weeks", 0) > 0]
    if recent:
        r_names = ", ".join(g["name"] for g in recent[:3])
        lines.append(f"На этой неделе: {r_names}")

    return "\n".join(lines)


def format_current_game_context() -> str:
    if not _current_game:
        return ""
    name  = _current_game.get("name", "")
    hours = _current_game.get("playtime_forever", 0) // 60
    return (
        f"ТЕКУЩАЯ ИГРА: {name} (наиграно {hours}ч). "
        f"Мастер сейчас играет — можешь комментировать и обсуждать игру."
    )


# ── Гайды ─────────────────────────────────────────────────────────────

async def find_guide(game_name: str, question: str = "") -> dict:
    from config import get_active_key, mark_key_used
    from google import genai
    from google.genai import types

    key = get_active_key()
    if not key:
        return {"text": "", "images": []}

    prompt = (
        f"Игра: {game_name}\n"
        f"Вопрос: {question or 'общие советы и гайд для новичка'}\n\n"
        f"Дай краткий но полезный ответ — 3-5 предложений. "
        f"Конкретные советы, не общие слова. "
        f"Если знаешь важные механики — упомяни. "
        f"Отвечай как опытный игрок, а не как Сакура."
    )

    try:
        client = genai.Client(api_key=key)
        r = await asyncio.to_thread(
            client.models.generate_content,
            model="gemini-3.1-flash-lite",
            contents=[types.Content(role="user", parts=[types.Part(text=prompt)])]
        )
        mark_key_used(key)
        guide_text = (r.text or "").strip()
    except Exception as e:
        log.error(f"[steam guide] {e}")
        guide_text = ""

    images = await _find_game_images(game_name)
    return {"text": guide_text, "images": images, "game": game_name}


async def _find_game_images(game_name: str) -> list[str]:
    try:
        game = search_game(game_name) or next(
            (g for g in _library if g.get("name", "").lower() == game_name.lower()), None
        )
        if not game:
            enc  = urllib.parse.quote(game_name)
            url  = f"https://store.steampowered.com/api/storesearch/?term={enc}&l=russian&cc=RU"
            data = await asyncio.to_thread(_fetch, url)
            if data:
                items = data.get("items", [])
                if items:
                    game = items[0]

        if not game:
            return []

        app_id = game.get("appid") or game.get("id")
        if not app_id:
            return []

        url  = f"https://store.steampowered.com/api/appdetails?appids={app_id}&l=russian"
        data = await asyncio.to_thread(_fetch, url)
        if not data:
            return []

        app_data    = data.get(str(app_id), {}).get("data", {})
        screenshots = app_data.get("screenshots", [])
        return [s["path_thumbnail"] for s in screenshots[:3]]

    except Exception as e:
        log.debug(f"[steam images] {e}")
        return []