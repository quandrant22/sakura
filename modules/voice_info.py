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
import time as _time
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
    if has("за несколько дней", "несколько дней"):
        return today - timedelta(days=7), today + timedelta(days=1)
    if has("неделю", "недели", "неделя", "7 дней", "за неделю"):
        return today - timedelta(days=7), today + timedelta(days=1)
    if has("месяц", "месяца", "30 дней", "за месяц"):
        return today - timedelta(days=30), today + timedelta(days=1)
    return None


def _range_to_ts(period):
    """(start_date, end_date_exclusive) → (unix_start, unix_end)."""
    start_d, end_d = period
    start_ts = int(datetime(start_d.year, start_d.month, start_d.day).timestamp())
    end_ts = int(datetime(end_d.year, end_d.month, end_d.day).timestamp())
    return start_ts, end_ts


def _default_period_word(arg: str) -> str:
    """Нормализует слово периода из аргумента роутера.
    Пять вариантов: сегодня / вчера / неделя / месяц / всё время.
    Без периода → по умолчанию неделя."""
    a = (arg or "").lower().strip()
    if "вчер" in a:
        return "вчера"
    if "сегодн" in a or a in ("за день", "за сегодня"):
        return "сегодня"
    if any(k in a for k in ("месяц", "30 дней")):
        return "месяц"
    if any(k in a for k in ("всё время", "все время", "вообще", "всего",
                            "за всегда", "всё", "за все время", "за всё время")):
        return "всё"
    if "за день" in a:
        return "сегодня"
    return "неделя"


def _period_human(word: str) -> str:
    return {
        "вчера": "За вчера",
        "сегодня": "За сегодня",
        "месяц": "За последний месяц",
        "всё": "За всё время",
    }.get(word, "За эту неделю")


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


# Кэш повторных вопросов по ачивкам (TTL ~15 минут)
_ACH_QUERY_TTL = 15 * 60
_ach_query_cache: dict[str, tuple[float, str, bool]] = {}


def _fmt_unlock_ts(ts: int) -> str:
    """«вчера в 22:14», «сегодня в 09:03», «12.05 в 18:40»."""
    from datetime import datetime as _dt
    dt = _dt.fromtimestamp(ts)
    today = date.today()
    d = dt.date()
    if d == today - timedelta(days=1):
        day = "вчера"
    elif d == today:
        day = "сегодня"
    else:
        day = dt.strftime("%d.%m")
    return f"{day} в {dt.strftime('%H:%M')}"


def _plural_ach(n: int) -> str:
    if n % 10 == 1 and n % 100 != 11:
        return "достижение"
    if n % 10 in (2, 3, 4) and n % 100 not in (12, 13, 14):
        return "достижения"
    return "достижений"


def _format_period_hits(word: str, found: list, total_count: int) -> str:
    """Дворецкий регистр: «За эту неделю: N достижений.» +
    по играм: Game — «Ачивка» (вчера в 22:14). Больше 10 → последние 5."""
    head = f"{_period_human(word)}: {total_count} {_plural_ach(total_count)}."
    LIMIT = 10
    lines = []
    shown = 0
    for game, items in found:
        for ts, name in items:
            if shown >= LIMIT:
                break
            lines.append(f"{game} — «{name}» ({_fmt_unlock_ts(ts)}).")
            shown += 1
        if shown >= LIMIT:
            break
    tail = f"\nИ ещё {total_count - LIMIT} более ранних." \
        if total_count > LIMIT else ""
    return head + "\n" + "\n".join(lines) + tail


async def steam_achievements(arg: str):
    """Ачивки за период. Основной источник — Steam API
    (GetPlayerAchievements); таблица seen — только кэш-фолбэк.
    → (текст, ok)."""
    word = _default_period_word(arg)

    cached = _ach_query_cache.get(word)
    if cached and _time.monotonic() - cached[0] < _ACH_QUERY_TTL:
        return cached[1], cached[2]

    text, ok = await _steam_achievements_uncached(word)
    _ach_query_cache[word] = (_time.monotonic(), text, ok)
    return text, ok


async def _candidate_games(word: str, start_date):
    """Игры-кандидаты по периоду — НЕ вся библиотека.
    сегодня/вчера/неделя → GetRecentlyPlayedGames; месяц → + игры из
    steam_games с playtime_2weeks>0 или свежим rtime_last_played."""
    from modules.steam_integration import (
        get_recently_played, load_library, get_library)

    ids: list = []
    names: dict = {}

    try:
        for g in (await get_recently_played(10) or []):
            appid = g.get("appid")
            if appid and appid not in ids:
                ids.append(appid)
                names[appid] = g.get("name", "")
    except Exception as e:
        log.debug(f"[voice_info] recently played: {e}")

    if word == "месяц":
        start_ts = int(datetime(start_date.year, start_date.month,
                                start_date.day).timestamp())
        try:
            from memory.db import _conn
            rows = _conn().execute(
                "SELECT appid, name FROM steam_games "
                "WHERE playtime_2weeks > 0 OR rtime_last_played >= ?",
                (start_ts,)).fetchall()
            for r in rows:
                if r["appid"] not in ids:
                    ids.append(r["appid"])
                    names[r["appid"]] = r["name"]
        except Exception as e:
            log.debug(f"[voice_info] steam_games месяц: {e}")

    # Имена из библиотеки (лениво грузим при пустом кэше)
    try:
        lib = get_library() or []
        if not lib:
            await load_library()
            lib = get_library() or []
        for g in lib:
            names.setdefault(g.get("appid"), g.get("name", ""))
    except Exception as e:
        log.debug(f"[voice_info] библиотека: {e}")

    return [(i, names.get(i, "")) for i in ids], names


def _plural_game(n: int) -> str:
    if n % 10 == 1 and n % 100 != 11:
        return "игре"
    if n % 10 in (2, 3, 4) and n % 100 not in (12, 13, 14):
        return "играх"
    return "играх"


def _achievements_all_time():
    """«За всё время» → сводка из локального журнала, БЕЗ десятков вызовов API."""
    from modules.steam_integration import load_library, get_library
    from memory.db import _conn

    rows = _conn().execute(
        "SELECT appid, COUNT(*) AS n FROM steam_achievements_seen "
        "GROUP BY appid ORDER BY n DESC").fetchall()

    lib = get_library() or []
    played_total = sum(1 for g in lib if (g.get("playtime_forever", 0) or 0) > 0)

    if not rows:
        return ("Локальный журнал достижений пока пуст — он наполняется "
                "по мере игры."), True

    total = sum(r["n"] for r in rows)
    games_n = len(rows)
    word_games = "игре" if games_n == 1 else "играх"
    head = f"Всего выбито {total} {_plural_ach(total)} в {games_n} {word_games}."
    lines = []
    for r in rows[:5]:
        appid = r["appid"]
        name = next((g.get("name", "") for g in lib if g.get("appid") == appid),
                    f"appid {appid}")
        lines.append(f"— {name}: {r['n']}")
    tail = ""
    if played_total > games_n:
        tail = (f"\nПолная статистика есть по {games_n} {_plural_game(games_n)} "
                f"из {played_total} — остальное собирается по мере игры.")
    return head + "\n" + "\n".join(lines) + tail, True


async def _steam_achievements_uncached(word: str):
    from modules.steam_integration import _fetch_achievements

    # Особый период: всё время → сводка из локального журнала
    if word == "всё":
        return _achievements_all_time()

    period = parse_period(word)
    if not period:
        period = parse_period("неделя")
    start_d, end_d = period
    start_ts, end_ts = _range_to_ts(period)

    candidates, names = await _candidate_games(word, start_d)

    # Нет кандидатов вовсе (никто не играл за период) — не ставим ok=False
    if not candidates:
        hits_seen = _seen_unlocked_between(start_ts, end_ts)
        if hits_seen:
            return _fallback_seen(word, hits_seen, names), True
        return f"{_period_human(word)} достижений нет.", True

    found: list = []
    api_ok = False
    api_error = False

    for appid, cname in candidates[:12]:
        try:
            achs, reason = await _fetch_achievements(appid)
        except Exception as e:
            log.debug(f"[voice_info] ачивки {appid}: {e}")
            api_error = True
            continue
        if achs is None:
            api_error = True
            continue
        api_ok = True   # ответили данными для этой игры
        game = names.get(appid) or cname or f"appid {appid}"
        hits = []
        for a in achs:
            if a.get("achieved") != 1:
                continue
            ts = int(a.get("unlocktime", 0) or 0)
            if start_ts <= ts < end_ts:
                nm = a.get("name") or a.get("displayName") or a.get("apiname", "?")
                hits.append((ts, nm))
        if hits:
            hits.sort(key=lambda x: -x[0])
            found.append((game, hits))

    total = sum(len(items) for _, items in found)

    if total:
        return _format_period_hits(word, found, total), True

    # Ачивок не найдено: если хоть по одной игре API честно ответил (achieved=1
    # не было) — считаем, что достижений за период нет. Иначе — недоступен.
    if api_ok:
        return f"{_period_human(word)} достижений нет.", True

    # Steam недоступен → локальная таблица как кэш-фолбэк
    hits_seen = _seen_unlocked_between(start_ts, end_ts)
    if hits_seen:
        return _fallback_seen(word, hits_seen, names), True
    return "Не смогла проверить, Steam недоступен.", False


def _fallback_seen(word: str, hits_seen, names: dict) -> str:
    """Оформление ответа из локального журнала при недоступном API."""
    by_app: dict = {}
    for h in hits_seen:
        by_app.setdefault(h["appid"], []).append((h["ts"], (h.get("name")
                        or h.get("displayName") or h.get("apiname", "?"))))
    found = [(names.get(a, f"appid {a}"), v) for a, v in by_app.items()]
    total = sum(len(v) for _, v in found)
    text = _format_period_hits(word, found, total)
    text += ("\n(по локальному журналу — данные могут быть неполными: "
             "Steam был недоступен)")
    return text


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


# ── Напоминания ───────────────────────────────────────────────────────

async def reminders_add(text: str):
    """«Напомни через N минут X» / «таймер на N минут». → (текст, ok)."""
    from modules.reminders import parse_reminder, add_reminder
    parsed = parse_reminder(text or "")
    if not parsed:
        return ("Не разобрала время. Скажи, например: "
                "напомни через 20 минут проверить чайник."), False
    entry = add_reminder(parsed["text"], parsed["delay"],
                         parsed.get("type", "reminder"))
    mins = max(1, round((entry["trigger_at"] - _now()) / 60))
    what = entry["text"] if entry["type"] != "timer" else "таймер"
    return f"Хорошо. Через {mins} мин напомню: {what}.", True


async def reminders_list():
    """Какие напоминания. → (текст, ok)."""
    from modules.reminders import format_reminders_list
    text = format_reminders_list()
    if not text:
        return "Список напоминаний пуст.", True
    return text, True


# ── Задачи ────────────────────────────────────────────────────────────

def _tasks_list_text() -> str:
    """Активные задачи с id — чтобы «выполнил задачу N» работал."""
    from modules.tasks import get_due_tasks, get_upcoming_tasks
    due = get_due_tasks() or []
    upcoming_ids = {t.get("id") for t in due}
    upcoming = [t for t in (get_upcoming_tasks(24) or [])
                if t.get("id") not in upcoming_ids]
    if not due and not upcoming:
        return ""
    lines = []
    if due:
        lines.append("На сегодня/просроченные:")
        for t in due[:8]:
            when = t.get("due_time") or t.get("due_date") or ""
            lines.append(f"— [{t['id']}] {t['text']}" + (f" ({when})" if when else ""))
    if upcoming:
        lines.append("Скоро:")
        for t in upcoming[:5]:
            lines.append(f"— [{t['id']}] {t['text']}")
    return "\n".join(lines)


async def tasks_list():
    """Какие задачи / что на сегодня. → (текст, ok)."""
    text = _tasks_list_text()
    if not text:
        return "Активных задач нет.", True
    return text, True


async def tasks_add(arg: str):
    """Добавить задачу. → (текст, ok)."""
    from modules.tasks import add_task
    name = (arg or "").strip()
    if not name:
        return "Не расслышала текст задачи.", False
    task = add_task(name)
    return f"Задача добавлена: {task['text']}.", True


async def tasks_done(arg: str):
    """Выполнил задачу N. → (текст, ok)."""
    import re as _re
    from modules import tasks as _tasks
    m = _re.search(r"\d+", arg or "")
    if not m:
        return "Назови номер задачи — номера есть в списке задач.", False
    task_id = int(m.group(0))
    exists = any(t.get("id") == task_id for t in (_tasks.load_tasks() or []))
    if not exists:
        return (f"Задачи номер {task_id} в списке нет. "
                f"Скажи «какие задачи» — покажу номера."), True
    _tasks.complete_task(task_id)
    return f"Отметила задачу {task_id} выполненной.", True


# ── Погода ────────────────────────────────────────────────────────────

async def weather_now():
    """Какая погода сейчас. → (текст, ok).
    Факты собираем из словаря get_weather() (temp/desc/wind/daily);
    get_weather_context() — промптовый подтекст и на «ясно» пустой,
    для ответа Мастеру не годится."""
    from modules.weather import get_weather
    w = await get_weather()
    if not w:
        return ("Сервис погоды не ответил. Это не «данных нет» — "
                "он просто недоступен, попробуй позже."), False
    parts = [f"Сейчас {w.get('temp', '?')}°C, {w.get('desc') or w.get('category', '')}"]
    wind = w.get("wind")
    if wind is not None:
        parts.append(f"ветер {wind} м/с")
    daily = w.get("daily") or []
    if len(daily) >= 1:
        d0 = daily[0]
        try:
            parts.append(f"сегодня от {d0['t_min']} до {d0['t_max']}°C")
        except (KeyError, TypeError):
            pass
    return ". ".join(parts) + ".", True


# ── Музыкальная статистика ────────────────────────────────────────────

async def music_recent(arg: str):
    """Что я слушал за период. → (текст, ok)."""
    from modules.music_memory import format_recent
    word = _default_period_word(arg or "сегодня")
    hours = 48 if word == "вчера" else (24 if word == "сегодня" else 168)
    label = _period_human(word)
    text = format_recent(hours=hours)
    if text.startswith("Нет данных"):
        return f"{label} прослушиваний нет.", True
    return f"{label} слушал(а):\n{text}", True


async def music_top(arg: str):
    """Кого слушаю чаще всего. → (текст, ok)."""
    from modules.music_memory import format_top
    word = _default_period_word(arg or "неделя")
    days = 30 if word == "за месяц" else 7
    text = format_top(days=days)
    if text.startswith("Нет данных"):
        return "За этот период статистики прослушиваний нет.", True
    return text, True


# ── Капсулы ───────────────────────────────────────────────────────────

async def capsules_list():
    """Какие капсулы ждут. → (текст, ok)."""
    from modules.capsules import get_all_capsules
    caps = get_all_capsules(include_opened=False) or []
    if not caps:
        return "Запечатанных капсул нет.", True
    n = len(caps)
    head = f"Ждут вскрытия {n}:" if n > 1 else "Одна капсула ждёт вскрытия:"
    lines = [f"— открыть {c.get('open_date', '?')}: "
             f"{str(c.get('text', ''))[:60]}" for c in caps[:8]]
    return head + "\n" + "\n".join(lines), True


def _now():
    import time as _t
    return _t.time()


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
        if action == "reminder:add":
            return await reminders_add(text)
        if action == "reminder:list":
            return await reminders_list()
        if action == "task:add":
            return await tasks_add(arg)
        if action == "task:list":
            return await tasks_list()
        if action == "task:done":
            return await tasks_done(arg)
        if action == "weather:now":
            return await weather_now()
        if action == "music_stats:recent":
            return await music_recent(arg)
        if action == "music_stats:top":
            return await music_top(arg)
        if action == "capsule:list":
            return await capsules_list()
    except Exception as e:
        log.error(f"[voice_info] {action}: {type(e).__name__}: {e}")
        return "Не смогла получить данные у источника — он недоступен.", False
    log.warning(f"[voice_info] неизвестное действие: {action!r}")
    return "Такой команды у меня пока нет.", False