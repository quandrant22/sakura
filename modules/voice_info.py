"""
modules/voice_info.py — информационные голосовые команды.

Связующий слой: роутер распознаёт намерение → отсюда берём ГОТОВЫЙ ФАКТ
из соответствующего модуля (steam_integration, vps_monitor, tasks, ...) →
ws_handlers озвучивает. Сами модули не переписываются.

Правило честности:
  handle() возвращает (текст, ok).
  ok=True  — данные получены (даже если их пусто: «новых ачивок нет»);
  ok=False — источник недоступен/модуль не смог: говорим это прямо,
             НЕ маскируя под «данных нет».
"""

import logging
from datetime import date, datetime, timedelta

log = logging.getLogger("sakura.voice_info")

# Корни действий, которые обрабатываются здесь (для ws_handlers)
INFO_ROOTS = ("steam", "vps", "reminder", "task", "weather",
              "music_stats", "capsule")


def is_info_action(action: str) -> bool:
    """True если действие — информационная команда из этого модуля."""
    root = (action or "").split(":", 1)[0]
    return root in INFO_ROOTS


# ── Периоды («вчера», «сегодня», «на этой неделе», «за месяц») ────────

def parse_period(text: str):
    """Разбирает словесный период. Возвращает (start_date, end_date_exclusive)
    или None. Одна общая функция для всех обработчиков."""
    import re as _re
    tl = (text or "").lower()
    today = date.today()

    def has(*phrases):
        for p in phrases:
            if _re.search(rf"(?<!\w){_re.escape(p)}(?!\w)", tl):
                return True
        return False

    if has("вчера"):
        d = today - timedelta(days=1)
        return d, today
    if has("сегодня"):
        return today, today + timedelta(days=1)
    if has("на этой неделе", "эту неделю", "эта неделя"):
        week_start = today - timedelta(days=today.weekday())
        return week_start, today + timedelta(days=1)
    if has("за неделю", "неделю", "недели", "неделя"):
        return today - timedelta(days=7), today + timedelta(days=1)
    if has("за месяц", "месяц", "месяца"):
        return today - timedelta(days=30), today + timedelta(days=1)
    return None


def _range_to_ts(period):
    """(start_date, end_date_exclusive) → (unix_start, unix_end)."""
    start_d, end_d = period
    start_ts = int(datetime(start_d.year, start_d.month, start_d.day).timestamp())
    end_ts = int(datetime(end_d.year, end_d.month, end_d.day).timestamp())
    return start_ts, end_ts


def _default_period_word(arg: str) -> str:
    """Нормализует слово периода из аргумента роутера."""
    a = (arg or "").lower().strip()
    if not a:
        return "неделя"
    if "вчер" in a:
        return "вчера"
    if "сегодн" in a:
        return "сегодня"
    if "месяц" in a:
        return "за месяц"
    return "неделя"


def _period_human(word: str) -> str:
    return {
        "вчера": "За вчера",
        "сегодня": "За сегодня",
        "за месяц": "За последний месяц",
    }.get(word, "На этой неделе")


# ── Steam ─────────────────────────────────────────────────────────────

def _seen_unlocked_between(start_ts: int, end_ts: int) -> list[dict]:
    """Ачивки из steam_achievements_seen за диапазон.
    unlocked_at хранится СТРОКОЙ — приводим к int; мусор пропускаем молча
    (не выдумываем дату)."""
    from memory.db import _conn
    rows = _conn().execute(
        "SELECT appid, apiname, unlocked_at FROM steam_achievements_seen"
    ).fetchall()
    out = []
    for r in rows:
        raw = (r["unlocked_at"] or "").strip()
        if not raw:
            continue
        try:
            ts = int(float(raw))
        except (ValueError, TypeError):
            continue
        if start_ts <= ts < end_ts:
            out.append({"appid": r["appid"], "apiname": r["apiname"], "ts": ts})
    out.sort(key=lambda x: x["ts"])
    return out


async def steam_achievements(arg: str):
    """Ачивки за период. → (текст, ok)."""
    from modules.steam_integration import get_library, get_achievements

    word = _default_period_word(arg)
    period = parse_period(word)
    if not period:
        period = parse_period("неделя")
    start_ts, end_ts = _range_to_ts(period)

    hits = _seen_unlocked_between(start_ts, end_ts)
    if not hits:
        return f"{_period_human(word)} новых ачивок нет.", True

    try:
        lib_names = {g.get("appid"): g.get("name", "")
                     for g in (get_library() or [])}
    except Exception as e:
        log.debug(f"[voice_info] библиотека steam недоступна: {e}")
        lib_names = {}

    by_app: dict[int, list[dict]] = {}
    for h in hits:
        by_app.setdefault(h["appid"], []).append(h)

    lines = []
    api_down = False
    total_shown = 0
    for appid, items in sorted(by_app.items(), key=lambda kv: -len(kv[1])):
        game = lib_names.get(appid) or f"appid {appid}"
        names = [it["apiname"] for it in items]
        try:
            achs = await get_achievements(appid)
            if achs:
                disp = {a.get("apiname"): (a.get("name") or a.get("displayName"))
                        for a in achs}
                names = [disp.get(n) or n for n in names]
            else:
                # API недоступен — остаются коды, честно пометим в хвосте
                api_down = True
        except Exception as e:
            log.debug(f"[voice_info] ачивки {appid}: {e}")
            api_down = True
        extra = ""
        if len(names) < len(items):
            extra = f" и ещё {len(items) - len(names)}"
            names = names[:12]
        lines.append(f"— {game}: {', '.join(names)}{extra}")
        total_shown += len(items)
        if total_shown >= 30:
            break

    head = f"{_period_human(word)} получены ачивки:"
    tail = "\n(Steam API ответил не полностью — часть названий могла остаться кодами)" \
        if api_down else ""
    return head + "\n" + "\n".join(lines) + tail, True


async def steam_current():
    """Что сейчас играю. → (текст, ok)."""
    from modules.steam_integration import get_session_context, _current_game
    parts = []
    try:
        ctx = get_session_context() or ""
        if ctx:
            parts.append(ctx)
    except Exception as e:
        log.debug(f"[voice_info] session ctx: {e}")
    if not parts:
        g = _current_game
        if g and g.get("name"):
            parts.append(f"Сейчас в библиотеке активна игра «{g['name']}»")
    if parts:
        return ". ".join(parts), True
    return "Сейчас не вижу запущенной игры.", True


async def steam_playtime(name: str):
    """Сколько наиграно: всего и за 2 недели — раздельно, не путать."""
    from modules.steam_integration import search_game
    game = search_game((name or "").strip())
    if not game:
        return f"Игру «{(name or '').strip()}» в библиотеке не нашла.", True
    forever_min = game.get("playtime_forever", 0) or 0
    recent_min  = game.get("playtime_2weeks", 0) or 0
    parts = [f"{game.get('name', 'игра')}: всего {forever_min // 60} ч"]
    if recent_min:
        parts.append(f"за две недели — {recent_min // 60} ч")
    else:
        parts.append("за две недели — не играл(а)")
    return ", ".join(parts) + ".", True


async def steam_progress(name: str):
    """Прогресс ачивок в игре: сколько из скольких. → (текст, ok)."""
    from modules.steam_integration import search_game, get_achievement_stats
    game = search_game((name or "").strip())
    if not game:
        return f"Игру «{(name or '').strip()}» в библиотеке не нашла.", True
    stats = await get_achievement_stats(game.get("appid"))
    if not stats:
        return (f"По «{game.get('name')}» Steam не ответил по ачивкам. "
                f"Это не значит, что прогресса нет — попробуй позже."), False
    return (f"{game.get('name')}: выбито {stats['unlocked']} из {stats['total']} "
            f"({stats['percent']}%)."), True


async def steam_recent():
    """Во что играл недавно. → (текст, ok)."""
    from modules.steam_integration import get_recently_played
    games = await get_recently_played()
    if not games:
        return "Steam не вернул недавних игр.", True
    lines = []
    for g in games[:5]:
        h2w = (g.get("playtime_2weeks", 0) or 0) // 60
        suffix = f" — {h2w} ч за две недели" if h2w else ""
        lines.append(f"— {g.get('name', 'игра')}{suffix}")
    return "Недавно играл(а):\n" + "\n".join(lines), True


# ── Единая точка входа ────────────────────────────────────────────────

def _vps_status_text() -> str:
    """Факты о сервере из vps_monitor (метрики текущего момента)."""
    from modules.vps_monitor import get_metrics
    m = get_metrics()
    if not m:
        return ""
    cpu, ram, disk = m.get("cpu", 0), m.get("ram", 0), m.get("disk", 0)
    free = m.get("disk_free")
    parts = [f"CPU {cpu:.0f}%", f"RAM {ram:.0f}%", f"диск {disk:.0f}%"]
    if free:
        parts.append(f"свободно {free} ГБ")
    uptime = m.get("uptime")
    if uptime:
        parts.append(f"аптайм {uptime}")
    return ", ".join(parts)


async def vps_status():
    """Как сервер / нагрузка. → (текст, ok)."""
    try:
        text = _vps_status_text()
    except Exception as e:
        log.debug(f"[voice_info] vps метрики: {e}")
        return "Метрики сервера сейчас не получаются.", False
    if not text:
        return ("Мониторинг ещё не собрал ни одной метрики — "
                "сервер запущен недавно."), False
    return f"Сервер: {text}.", True


async def vps_feeling():
    """«Как самочувствие» — сервер как тело Сакуры. → (текст, ok)."""
    from modules.vps_monitor import get_body_feeling
    feeling = get_body_feeling() or ""
    if feeling:
        return feeling, True
    # пусто = всё в норме — это тоже честный ответ
    return ("Чувствую себя спокойно: нагрузка в норме, "
            "ничего не давит."), True


# ── Единая точка входа ────────────────────────────────────────────────

async def handle(action: str, arg: str = "", text: str = ""):
    """Диспетчер информационных команд. Возвращает (текст, ok)."""
    action = action or ""
    arg = arg or ""
    try:
        if action == "steam:achievements":
            return await steam_achievements(arg)
        if action == "steam:current":
            return await steam_current()
        if action == "steam:playtime":
            if not arg.strip():
                return "Не расслышала название игры.", False
            return await steam_playtime(arg)
        if action == "steam:progress":
            if not arg.strip():
                return "Не расслышала название игры.", False
            return await steam_progress(arg)
        if action == "steam:recent":
            return await steam_recent()
        if action == "vps:status":
            return await vps_status()
        if action == "vps:feeling":
            return await vps_feeling()
    except Exception as e:
        log.error(f"[voice_info] {action}: {type(e).__name__}: {e}")
        return "Не смогла получить данные у источника — он недоступен.", False
    log.warning(f"[voice_info] неизвестное действие: {action!r}")
    return "Такой команды у меня пока нет.", False