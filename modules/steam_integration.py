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
from config import MAIN_MODEL

log = logging.getLogger("sakura.steam")

# RAM-кэш поверх SQLite (для быстрого доступа без SQL в горячем пути)
_library:    list[dict]   = []
_library_at: float        = 0.0
_LIBRARY_TTL              = 3600 * 6   # обновляем раз в 6 часов

_current_game: Optional[dict] = None
_achievements_cache: dict     = {}
_ACHIEVEMENTS_TTL             = 30 * 60   # 30 минут — новые ачивки подхватываются без перезапуска

# Текущая игровая сессия (в памяти процесса — сиюминутное состояние, не в БД)
_session: Optional[dict] = None   # {"game": dict, "started_at": float}
_SESSION_MIN_MINUTES = 15         # короче 15 минут — не событие
_SESSION_DEDUP_HOURS = 1          # не плодим записи об одной игре чаще раза в час
_last_session_log: dict = {}      # {appid: timestamp} — защита от мусора

# Последняя причина ошибки — логируем ОДИН раз при смене состояния, не спамим в цикле
_last_reason: str = ""


def _get_config():
    try:
        from config import STEAM_KEY, STEAM_ID
        return STEAM_KEY, STEAM_ID
    except Exception:
        return "", ""


def _log_reason(reason: str):
    """Логирует причину только при смене состояния."""
    global _last_reason
    if reason != _last_reason:
        _last_reason = reason
        if reason == "ok":
            log.info("[steam] API: ok")
        else:
            log.warning(f"[steam] API: {reason}")


def _fetch(url: str) -> dict:
    """→ {"ok": bool, "data": dict|None, "reason": str}
    reason: ok | private | invalid_key | steam_down | no_stats | no_data | error"""
    try:
        with urllib.request.urlopen(url, timeout=8) as r:
            status = r.status
            body   = r.read().decode()
    except urllib.error.HTTPError as e:
        status = e.code
        try:
            body = e.read().decode()
        except Exception:
            body = ""
    except Exception as e:
        log.debug(f"[steam] fetch error: {e}")
        _log_reason("steam_down")
        return {"ok": False, "data": None, "reason": "steam_down"}

    try:
        data = json.loads(body) if body else {}
    except Exception:
        data = {}

    # HTTP-коды
    if status in (401, 403):
        _log_reason("invalid_key")
        return {"ok": False, "data": data, "reason": "invalid_key"}
    if status >= 500:
        _log_reason("steam_down")
        return {"ok": False, "data": data, "reason": "steam_down"}

    # Семантика тела
    ps = data.get("playerstats")
    if isinstance(ps, dict):
        err = ps.get("error")
        if err == "Profile is not public":
            _log_reason("private")
            return {"ok": False, "data": data, "reason": "private"}
        if err == "Requested app has no stats":
            _log_reason("no_stats")
            return {"ok": False, "data": data, "reason": "no_stats"}

    if data.get("response") == {}:
        _log_reason("private")
        return {"ok": False, "data": data, "reason": "private"}

    if not data:
        _log_reason("no_data")
        return {"ok": False, "data": None, "reason": "no_data"}

    _log_reason("ok")
    return {"ok": True, "data": data, "reason": "ok"}


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
            rtime_last_played INTEGER NOT NULL DEFAULT 0,
            img_icon_url    TEXT,
            updated_at      TEXT    NOT NULL DEFAULT (datetime('now'))
        );
        CREATE INDEX IF NOT EXISTS idx_steam_playtime ON steam_games(playtime_forever DESC);
        CREATE INDEX IF NOT EXISTS idx_steam_name     ON steam_games(name);

        CREATE TABLE IF NOT EXISTS steam_achievements_seen (
            appid       INTEGER NOT NULL,
            apiname     TEXT    NOT NULL,
            unlocked_at TEXT,
            seen_at     TEXT    NOT NULL DEFAULT (datetime('now')),
            PRIMARY KEY (appid, apiname)
        );
    """)
    # Миграция старых БД: колонка rtime_last_played могла не существовать
    try:
        conn.execute("ALTER TABLE steam_games ADD COLUMN rtime_last_played INTEGER NOT NULL DEFAULT 0")
        conn.commit()
    except Exception:
        pass  # колонка уже есть
    conn.commit()


def _save_to_db(games: list[dict]):
    """Сохраняет/обновляет всю библиотеку в SQLite."""
    try:
        _ensure_table()
        from memory.db import _conn
        conn = _conn()
        for g in games:
            conn.execute("""
                INSERT INTO steam_games(appid, name, playtime_forever, playtime_2weeks, rtime_last_played, img_icon_url)
                VALUES(?, ?, ?, ?, ?, ?)
                ON CONFLICT(appid) DO UPDATE SET
                    name=excluded.name,
                    playtime_forever=excluded.playtime_forever,
                    playtime_2weeks=excluded.playtime_2weeks,
                    rtime_last_played=excluded.rtime_last_played,
                    img_icon_url=excluded.img_icon_url,
                    updated_at=datetime('now')
            """, (
                g.get("appid"),
                g.get("name", ""),
                g.get("playtime_forever", 0),
                g.get("playtime_2weeks", 0),
                g.get("rtime_last_played", 0) or 0,
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
            "SELECT appid, name, playtime_forever, playtime_2weeks, rtime_last_played, img_icon_url "
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
    res = await asyncio.to_thread(_fetch, url)
    if not res.get("ok"):
        return

    games = res["data"].get("response", {}).get("games", [])
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


def _record_session_end():
    """Завершает сессию: считает длительность, при >15 мин пишет эпизод в память.
    Защита от мусора: не чаще одной записи об игре в час."""
    global _session
    if not _session:
        return
    game = _session["game"]
    started = _session["started_at"]
    _session = None

    minutes = int((time.monotonic() - started) / 60)
    if minutes < _SESSION_MIN_MINUTES:
        return

    appid = game.get("appid")
    now = time.monotonic()
    last = _last_session_log.get(appid)
    if last and now - last < _SESSION_DEDUP_HOURS * 3600:
        return  # уже писали об этой игре недавно — не плодим записи

    _last_session_log[appid] = now
    name = game.get("name", "игра")
    hours = minutes // 60
    mins = minutes % 60
    if hours:
        dur = f"{hours} ч {mins} мин" if mins else f"{hours} ч"
    else:
        dur = f"{mins} мин"
    try:
        from memory.db import add_to_category as db_add
        db_add("events", f"играл в {name} {dur}", layer="working")
        log.info(f"[steam] Сессия записана: {name} {dur}")
    except Exception as e:
        log.debug(f"[steam] session record error: {e}")


async def get_current_game(active_window: str) -> Optional[dict]:
    global _current_game
    game = find_game_by_window(active_window)
    if game != _current_game:
        # Игра пропала → конец сессии
        if _current_game and not game:
            _record_session_end()
        _current_game = game
        if game:
            # Игра появилась → начало сессии
            global _session
            _session = {"game": game, "started_at": time.monotonic()}
            log.info(f"[steam] Текущая игра: {game['name']}")
    return game


def get_session_context() -> str:
    """→ 'СЕЙЧАС: Мастер играет в Palworld, 40 минут' или '' если не играет."""
    if not _session:
        return ""
    game = _session["game"]
    minutes = int((time.monotonic() - _session["started_at"]) / 60)
    name = game.get("name", "игра")
    return f"СЕЙЧАС: Мастер играет в {name}, {minutes} минут"


def get_current_session() -> Optional[dict]:
    """Текущая игровая сессия структурированно: {name, minutes} или None."""
    if not _session:
        return None
    return {
        "name":    (_session.get("game") or {}).get("name", "игра"),
        "minutes": int((time.monotonic() - _session["started_at"]) / 60),
    }


# ── Достижения ────────────────────────────────────────────────────────

async def get_achievements(app_id: int) -> list[dict]:
    """TTL-кэш поверх _fetch_achievements (для совместимости)."""
    cached = _achievements_cache.get(app_id)
    if cached and time.monotonic() - cached[1] < _ACHIEVEMENTS_TTL:
        return cached[0]
    ach, _reason = await _fetch_achievements(app_id)
    if ach is not None:
        _achievements_cache[app_id] = (ach, time.monotonic())
    return ach if ach is not None else []


async def _fetch_achievements(app_id: int) -> tuple[Optional[list], str]:
    """GetPlayerAchievements БЕЗ кэша. → (achievements|None, reason).
    reason: 'ok' | 'steam_down' | 'private' | 'invalid_key' | 'no_stats' | 'no_data'."""
    key, sid = _get_config()
    if not key or not sid:
        return None, "invalid_key"
    url = (
        f"http://api.steampowered.com/ISteamUserStats/GetPlayerAchievements/v0001/"
        f"?appid={app_id}&key={key}&steamid={sid}&format=json&l=russian"
    )
    res = await asyncio.to_thread(_fetch, url)
    if not res.get("ok"):
        return None, res.get("reason", "steam_down")
    achievements = res["data"].get("playerstats", {}).get("achievements", [])
    return achievements, "ok"


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


# ── Ачивки как события ────────────────────────────────────────────────

def _seen_achievements(appid: int) -> set:
    """Возвращает set apiname уже виденных ачивок для игры."""
    try:
        _ensure_table()
        from memory.db import _conn
        rows = _conn().execute(
            "SELECT apiname FROM steam_achievements_seen WHERE appid=?", (appid,)
        ).fetchall()
        return {r["apiname"] for r in rows}
    except Exception as e:
        log.debug(f"[steam] seen achievements error: {e}")
        return set()


def _mark_achievements_seen(appid: int, achievements: list[dict]):
    """Записывает ачивки в таблицу seen."""
    try:
        _ensure_table()
        from memory.db import _conn
        conn = _conn()
        for a in achievements:
            conn.execute("""
                INSERT OR IGNORE INTO steam_achievements_seen(appid, apiname, unlocked_at)
                VALUES(?, ?, ?)
            """, (appid, a.get("apiname", ""), str(a.get("unlocktime", ""))))
        conn.commit()
    except Exception as e:
        log.debug(f"[steam] mark seen error: {e}")


async def check_new_achievements(appid: int) -> list[dict]:
    """Сравнивает текущие разблокированные ачивки с таблицей seen.
    Новые → записывает и возвращает список. При первом запуске для игры
    (таблица пуста по appid) — записывает ВСЁ молча, возвращает []."""
    achievements = await get_achievements(appid)
    if not achievements:
        return []

    unlocked = [a for a in achievements if a.get("achieved") == 1]
    if not unlocked:
        return []

    seen = _seen_achievements(appid)
    if not seen:
        # Первый запуск для игры — записываем всё молча, ничего не возвращаем
        _mark_achievements_seen(appid, unlocked)
        return []

    new = [a for a in unlocked if a.get("apiname") not in seen]
    if not new:
        return []

    _mark_achievements_seen(appid, new)
    return new


async def get_recently_played(limit: int = 5) -> list[dict]:
    """GetRecentlyPlayedGames → [{name, appid, playtime_2weeks, playtime_forever}]
    (минуты). Пусто если API недоступен или игр нет."""
    key, sid = _get_config()
    if not key or not sid:
        return []
    url = (
        f"http://api.steampowered.com/IPlayerService/GetRecentlyPlayedGames/v0001/"
        f"?key={key}&steamid={sid}&format=json&count={limit}"
    )
    res = await asyncio.to_thread(_fetch, url)
    if not res.get("ok"):
        return []
    games = (res.get("data") or {}).get("response", {}).get("games") or []
    return games


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
    lines.append("Наиграно (всего за всё время):")
    for g in played[:20]:
        h = g.get("playtime_forever", 0) // 60
        lines.append(f"  • {g['name']} ({h}ч)")

    # Неначатые — одной строкой чтобы не раздувать промпт
    if unplayed:
        names = ", ".join(g["name"] for g in unplayed[:15])
        suffix = f" и ещё {len(unplayed)-15}" if len(unplayed) > 15 else ""
        lines.append(f"Не запускались: {names}{suffix}")

    # Недавно играл (playtime_2weeks > 0) — это время за последние 2 недели, не всего
    recent = [g for g in _library if g.get("playtime_2weeks", 0) > 0]
    if recent:
        r_names = ", ".join(g["name"] for g in recent[:3])
        lines.append(f"За последние 2 недели: {r_names}")

    # Правило честности: не выдумывать числа
    lines.append(
        "ПРАВИЛО: если данных о времени в игре или ачивках нет — НЕ выдумывай числа. "
        "Скажи, что статистика недоступна, или не упоминай её вовсе. "
        "playtime_forever — всего часов за всё время, playtime_2weeks — за последние две недели. "
        "Это разные утверждения, подписывай явно."
    )

    return "\n".join(lines)


def format_current_game_context() -> str:
    if not _current_game:
        return ""
    name  = _current_game.get("name", "")
    hours = _current_game.get("playtime_forever", 0) // 60
    return (
        f"ТЕКУЩАЯ ИГРА: {name} (наиграно всего {hours}ч). "
        f"Мастер сейчас играет — можешь комментировать и обсуждать игру. "
        f"ПРАВИЛО: если данных о времени или ачивках нет — НЕ выдумывай числа, "
        f"скажи что статистика недоступна или не упоминай её."
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
            model=MAIN_MODEL,
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
            res  = await asyncio.to_thread(_fetch, url)
            if res.get("ok"):
                items = res["data"].get("items", [])
                if items:
                    game = items[0]

        if not game:
            return []

        app_id = game.get("appid") or game.get("id")
        if not app_id:
            return []

        url  = f"https://store.steampowered.com/api/appdetails?appids={app_id}&l=russian"
        res  = await asyncio.to_thread(_fetch, url)
        if not res.get("ok"):
            return []

        app_data    = res["data"].get(str(app_id), {}).get("data", {})
        screenshots = app_data.get("screenshots", [])
        return [s["path_thumbnail"] for s in screenshots[:3]]

    except Exception as e:
        log.debug(f"[steam images] {e}")
        return []


# ── Фоновое обновление библиотеки ─────────────────────────────────────

async def steam_library_loop():
    """Фоновый цикл: раз в 6 часов синхронизирует библиотеку с API,
    чтобы новые игры (например Palworld) появлялись без перезапуска."""
    while True:
        await asyncio.sleep(_LIBRARY_TTL)
        try:
            await load_library(force=True)
        except Exception as e:
            log.debug(f"[steam] library loop error: {e}")


# ── Фоновый цикл ачивок ───────────────────────────────────────────────

_ACHIEVEMENTS_CHECK_INTERVAL = 10 * 60   # раз в 10 минут
_ACHIEVEMENTS_REACTION_COOLDOWN = 3600   # не чаще одного упоминания в час
_ACHIEVEMENTS_REACTION_PROB = 0.5        # ~50% вероятность реакции
_last_achievement_reaction: float = 0.0


async def steam_achievements_loop():
    """Фоновый цикл: раз в 10 минут проверяет новые ачивки, ТОЛЬКО если
    Мастер сейчас в игре. Реакция редкая — не чаще раза в час, ~50%.

    Фолбэк: если текущая игра НЕ определилась по окну (полноэкранный режим,
    заголовок не отдан агентом) — берём игры из GetRecentlyPlayedGames со
    свежим rtime_last_played (последние 14 часов) и проверяем их ачивки."""
    global _last_achievement_reaction
    while True:
        await asyncio.sleep(_ACHIEVEMENTS_CHECK_INTERVAL)
        try:
            check_ids = []
            if _current_game and _current_game.get("appid"):
                check_ids.append(_current_game["appid"])
            else:
                # Фолбэк: недавние игры по API/БД
                check_ids = await _recent_played_appids(hours=14)

            for appid in check_ids:
                if not appid:
                    continue
                new = await check_new_achievements(appid)
                if not new:
                    continue
                # Реакция редкая: не чаще раза в час + ~50% вероятность
                now = time.monotonic()
                if now - _last_achievement_reaction < _ACHIEVEMENTS_REACTION_COOLDOWN:
                    continue
                import random
                if random.random() > _ACHIEVEMENTS_REACTION_PROB:
                    continue
                _last_achievement_reaction = now
                chosen = _pick_rarest_achievement(new)
                game_name = (_current_game or {}).get("name", "игра")
                log.info(f"[steam] Новая ачивка: {chosen.get('name', chosen.get('apiname', '?'))} в {game_name}")
                cb = _achievement_callback
                if cb:
                    await cb(game_name, chosen)
        except Exception as e:
            log.debug(f"[steam] achievements loop error: {e}")


async def _recent_played_appids(hours: int = 14) -> list[int]:
    """Игры со свежим rtime_last_played — из БД, с фолбэком на API."""
    now = time.time()
    limit_ts = int(now - hours * 3600)
    try:
        _ensure_table()
        from memory.db import _conn
        rows = _conn().execute(
            "SELECT appid FROM steam_games "
            "WHERE rtime_last_played >= ? ORDER BY rtime_last_played DESC LIMIT 5",
            (limit_ts,)).fetchall()
        if rows:
            return [r["appid"] for r in rows]
    except Exception as e:
        log.debug(f"[steam] recent played db error: {e}")
    # Фолбэк на API
    try:
        games = await get_recently_played(5)
        return [g.get("appid") for g in (games or []) if g.get("appid")]
    except Exception as e:
        log.debug(f"[steam] recent played api error: {e}")
        return []


_achievement_callback = None


def set_achievement_callback(cb):
    """Устанавливает callback для реакции на ачивку: cb(game_name, achievement_dict)."""
    global _achievement_callback
    _achievement_callback = cb


def _pick_rarest_achievement(achievements: list[dict]) -> dict:
    """Выбирает самую редкую ачивку (по глобальному проценту получения),
    если доступен, иначе — последнюю по unlocktime."""
    with_pct = [a for a in achievements if a.get("global_percent") is not None]
    if with_pct:
        return min(with_pct, key=lambda a: a.get("global_percent", 100))
    return max(achievements, key=lambda a: a.get("unlocktime", 0))
