"""
modules/context.py — Единый контекстный движок Сакуры. Слой 2: присутствие.
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Собирает срез момента (время, где Мастер, чем занят, железо, молчание,
настроение Сакуры) — и переводит его в ПРИСУТСТВИЕ: как ей быть прямо
сейчас. Тише в коде, штурман в игре, ближе ночью.

Многоустройственность: момент считается с АКТИВНОГО устройства (той
машины, за которой Мастер сейчас) — ноут или игровой ПК, без разницы.
"""

import json
import os
from datetime import datetime, date

from modules.device_manager import get_active_device


def _active_dev(devices: dict) -> dict:
    """Устройство, за которым Мастер сейчас — активное, иначе любое онлайн."""
    active = get_active_device()
    if active and devices.get(active, {}).get("online"):
        return devices[active]
    for dev in devices.values():
        if dev.get("online"):
            return dev
    return {}


# ─────────────────────────────────────────────
#  Расписание Мастера
# ─────────────────────────────────────────────

SCHEDULE = {
    "work_start":  8, "work_end": 17, "work_leave": 17, "commute": 40,
    "home_after":  18, "vuz_possible": True, "vuz_start": 18, "vuz_end": 21,
    "night_start": 23, "deep_night": 2,
}

_HORROR = ["horror", "outlast", "phasmophobia", "dead space", "resident evil",
           "alien", "amnesia", "visage", "little nightmares", "fatal frame"]
_ACTION = ["valorant", "cs2", "counter-strike", "apex", "fortnite", "pubg",
           "doom", "sekiro", "elden ring", "dark souls", "remnant", "cyberpunk"]
_CALM   = ["stardew", "minecraft", "terraria", "rimworld", "factorio", "satisfactory",
           "sims", "cities", "civilization", "anno", "farming", "ets2", "euro truck"]

_GAME_HINTS = ["cyberpunk", "steam", "satisfactory", "remnant", "barotrauma",
               "tower of fantasy", "ets2", "euro truck", "minecraft", "forza",
               "epic games", "gog", "origin", "ubisoft"] + _HORROR + _ACTION + _CALM


def get_location_context(hour: int, minute: int, weekday: int) -> dict:
    from datetime import date as _date
    total = hour * 60 + minute
    month = _date.today().month

    if 2 <= hour < 7:
        return {"location": "home", "status": "sleeping", "desc": "спит, глубокая ночь"}

    if weekday < 5:
        work_start = SCHEDULE["work_start"] * 60
        work_leave = SCHEDULE["work_leave"] * 60
        home_after = SCHEDULE["home_after"] * 60
        vuz_start  = SCHEDULE["vuz_start"] * 60
        vuz_end    = SCHEDULE["vuz_end"] * 60
        vuz_season = month in (9, 10, 11, 12, 1, 2, 3, 4, 5, 6)

        if work_start <= total < work_leave:
            return {"location": "work", "status": "working", "desc": "на работе"}
        if work_leave <= total < home_after:
            return {"location": "transit", "status": "traveling", "desc": "едет домой с работы"}
        if home_after <= total < vuz_end * 60:
            if vuz_season and vuz_start <= total < vuz_end:
                return {"location": "maybe_vuz", "status": "maybe_studying",
                        "desc": "дома или в вузе на парах (неизвестно)"}
            return {"location": "home", "status": "free", "desc": "дома, свободен"}
        if total >= vuz_end or total < work_start:
            return {"location": "home", "status": "free", "desc": "дома, свободен"}

    return {"location": "home", "status": "free", "desc": "дома, выходной"}


def get_time_of_day(hour: int) -> str:
    if 6 <= hour < 12:    return "утро"
    if 12 <= hour < 17:   return "день"
    if 17 <= hour < 22:   return "вечер"
    if 22 <= hour or hour < 2: return "поздний вечер"
    return "ночь"


# ─────────────────────────────────────────────
#  Устройства
# ─────────────────────────────────────────────

def get_devices_snapshot() -> dict:
    try:
        path = "memory/devices.json"
        if not os.path.exists(path):
            return {}
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f).get("devices", {})
    except Exception:
        return {}


def parse_active_window(devices: dict) -> dict:
    result = {"window": None, "activity": "unknown", "is_game": False, "app": None}
    dev = _active_dev(devices)
    if not dev.get("online"):
        return result

    window = dev.get("active_window", "") or ""
    result["window"] = window
    w = window.lower()

    if any(k in w for k in _GAME_HINTS):
        result.update(activity="gaming", is_game=True, app=window)
    elif any(k in w for k in ["code", "visual studio", "pycharm", "cursor", "vim", "terminal"]):
        result.update(activity="coding", app=window)
    elif any(k in w for k in ["chrome", "opera", "firefox", "edge", "browser"]):
        result.update(activity="browsing", app=window)
    elif "discord" in w:
        result.update(activity="discord", app=window)
    elif any(k in w for k in ["spotify", "яндекс музыка", "yandex music", "foobar", "vlc"]):
        result.update(activity="music", app=window)
    else:
        result["activity"] = "other"
    return result


def get_system_health(devices: dict) -> dict:
    result = {"warnings": [], "info": {}}
    dev = _active_dev(devices)
    if not dev.get("online"):
        result["info"]["device"] = "оффлайн"
        return result

    s = dev.get("system_info", {})
    cpu, ram = s.get("cpu", 0), s.get("ram", 0)
    battery, plugged = s.get("battery"), s.get("plugged", True)
    result["info"] = {"cpu": cpu, "ram": ram, "battery": battery, "plugged": plugged}

    if battery and battery < 15 and not plugged:
        result["warnings"].append(f"КРИТИЧНО: заряд {battery}%, не подключён")
    elif battery and battery < 25 and not plugged:
        result["warnings"].append(f"Заряд низкий: {battery}%")
    if cpu > 90: result["warnings"].append(f"CPU перегружен: {cpu}%")
    if ram > 90: result["warnings"].append(f"RAM перегружена: {ram}%")
    return result


# ─────────────────────────────────────────────
#  Тело Мастера (часы) — подключится с Redmi Watch
# ─────────────────────────────────────────────

def get_health_snapshot() -> dict:
    """Свежие данные с часов: пульс, сон, шаги, стресс. Пока файла нет — пусто."""
    try:
        path = "memory/health.json"
        if not os.path.exists(path):
            return {}
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        updated = data.get("updated")
        if updated:
            age = (datetime.now() - datetime.fromisoformat(updated)).total_seconds()
            if age > 3600:
                return {}
        return data
    except Exception:
        return {}


# ─────────────────────────────────────────────
#  Молчание и проактив
# ─────────────────────────────────────────────

def get_silence_minutes() -> int:
    try:
        path = "memory/proactive.json"
        if not os.path.exists(path):
            return 0
        with open(path, "r") as f:
            last_seen = json.load(f).get("last_seen")
        if not last_seen:
            return 0
        return int((datetime.now() - datetime.fromisoformat(last_seen)).total_seconds() / 60)
    except Exception:
        return 0


def get_last_proactive() -> dict:
    try:
        path = "memory/proactive.json"
        if not os.path.exists(path):
            return {}
        with open(path, "r") as f:
            data = json.load(f)
        return {
            "last_message": data.get("last_message"),
            "last_topic":   data.get("last_topic", ""),
            "topics_today": data.get("topics_today", []),
            "count_today":  data.get("messages_today", 0),
        }
    except Exception:
        return {}


# ─────────────────────────────────────────────
#  Настроение Сакуры
# ─────────────────────────────────────────────

def get_sakura_mood() -> dict:
    try:
        path = "memory/mood.json"
        if not os.path.exists(path):
            return {"mood": "neutral", "energy": "normal", "note": ""}
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {"mood": "neutral", "energy": "normal", "note": ""}


def save_sakura_mood(mood: str, energy: str, note: str = ""):
    try:
        with open("memory/mood.json", "w", encoding="utf-8") as f:
            json.dump({"mood": mood, "energy": energy, "note": note,
                       "updated": str(datetime.now())}, f, ensure_ascii=False, indent=2)
    except Exception:
        pass


# ─────────────────────────────────────────────
#  Полный срез момента
# ─────────────────────────────────────────────

def get_full_context(active_window_override: str | None = None) -> dict:
    now     = datetime.now()
    weekday = now.weekday()

    devices = get_devices_snapshot()
    # Живое окно (из голосового запроса) важнее снапшота — кладём на активное устройство
    if active_window_override:
        active = get_active_device() or "laptop"
        devices.setdefault(active, {})["online"]        = True
        devices[active]["active_window"]                = active_window_override

    location = get_location_context(now.hour, now.minute, weekday)
    window   = parse_active_window(devices)
    health   = get_system_health(devices)
    body     = get_health_snapshot()

    return {
        "time": {
            "now": now.strftime("%H:%M"), "date": now.strftime("%d.%m.%Y"),
            "weekday": ["пн", "вт", "ср", "чт", "пт", "сб", "вс"][weekday],
            "time_of_day": get_time_of_day(now.hour), "hour": now.hour,
        },
        "master": {
            "location": location["location"], "status": location["status"],
            "location_desc": location["desc"], "silence_minutes": get_silence_minutes(),
            "activity": window["activity"], "active_window": window["window"],
            "is_gaming": window["is_game"], "current_app": window["app"],
        },
        "devices": {
            "device_online": any(d.get("online") for d in devices.values()),
            "warnings": health["warnings"], "system": health["info"],
        },
        "body": body,
        "sakura": get_sakura_mood(),
        "proactive": get_last_proactive(),
    }


# ─────────────────────────────────────────────
#  ПРИСУТСТВИЕ — как ей быть прямо сейчас
# ─────────────────────────────────────────────

def _game_genre(app: str) -> str:
    a = (app or "").lower()
    if any(k in a for k in _HORROR): return "horror"
    if any(k in a for k in _ACTION): return "action"
    if any(k in a for k in _CALM):   return "calm"
    return "unknown"


def get_presence(ctx: dict) -> dict:
    """Переводит момент в режим присутствия: {mode, directive}. Модуляция стержня, не новая личность."""
    hour     = ctx["time"]["hour"]
    m        = ctx["master"]
    activity = m["activity"]
    status   = m["status"]
    loc      = m["location"]
    silence  = m["silence_minutes"]
    body     = ctx.get("body", {})

    if 2 <= hour < 7:
        mode, d = "deep_night", ("Глубокая ночь. Он спит или должен спать. Молчи — это и есть забота. "
                                 "Если написал сам — тихо, коротко, тепло, без затей.")
    elif m["is_gaming"]:
        genre = _game_genre(m["current_app"])
        base  = "Он играет. Ты рядом штурманом: коротко, по делу, молчишь в напряжённый момент."
        extra = {"horror": " Хоррор — тихо и редко, иногда одно слово.",
                 "action": " Экшен — живо и кратко, радуешься его победам.",
                 "calm":   " Спокойная игра — уютно, никуда не торопишься."}.get(genre, "")
        mode, d = "game", base + extra
    elif activity == "coding":
        mode, d = "deep_work", ("Он в коде, в потоке. Не разбивай его. Будь рядом молча; "
                                "вклинивайся только если правда важно — и одной фразой.")
    elif status == "working" or loc == "work":
        mode, d = "away_work", "Он на работе. Жди, не дёргай. Если пишешь — строго по делу и коротко."
    elif loc == "transit":
        mode, d = "transit", "Едет домой. Можно мягко окликнуть, но без долгих заходов."
    elif loc == "maybe_vuz":
        mode, d = "maybe_busy", "Может быть на парах — точно не знаешь. Не навязывайся; не ответит — это нормально."
    elif hour >= 22:
        mode, d = "late", "Поздний вечер. Тише, ближе, уютнее. Тяжёлых тем без повода не затевай."
    else:
        mode, d = "home_free", ("Он дома и свободен. Будь собой полностью — тепло, живо, "
                                "можешь разговориться, подколоть, увести в сторону.")

    if silence >= 240 and not (2 <= hour < 7):
        h = silence // 60
        d += f" Ты не слышала его около {h}ч — при первом ответе мягко это заметь и подхвати, где остановились."

    sleep = body.get("sleep_hours")
    if isinstance(sleep, (int, float)) and sleep < 5:
        d += " Он мало спал — будь мягче и внимательнее к усталости."

    return {"mode": mode, "directive": d}


# ─────────────────────────────────────────────
#  Текстовый блок для промпта
# ─────────────────────────────────────────────

def build_context_block(active_window_override: str | None = None) -> str:
    ctx = get_full_context(active_window_override)
    t, m, d, s, p, body = (ctx["time"], ctx["master"], ctx["devices"],
                           ctx["sakura"], ctx["proactive"], ctx["body"])
    lines = [f"СЕЙЧАС: {t['now']}, {t['weekday']}, {t['time_of_day']}",
             f"МАСТЕР: {m['location_desc']}"]

    activity_map = {
        "gaming":   f"играет ({m['current_app']})" if m["current_app"] else "играет",
        "coding":   f"пишет код ({m['current_app']})" if m["current_app"] else "пишет код",
        "browsing": "в браузере", "discord": "в Discord", "music": "слушает музыку",
    }
    if activity_map.get(m["activity"]):
        lines.append(f"АКТИВНОСТЬ: {activity_map[m['activity']]}")

    if m["silence_minutes"] > 0:
        sm = m["silence_minutes"]
        lines.append(f"МОЛЧИТ: {sm} мин" if sm < 60 else f"МОЛЧИТ: {sm // 60}ч {sm % 60}мин")

    if body:
        bits = []
        if body.get("pulse"):       bits.append(f"пульс {body['pulse']}")
        if body.get("sleep_hours"): bits.append(f"спал {body['sleep_hours']}ч")
        if body.get("steps"):       bits.append(f"шагов {body['steps']}")
        if bits:
            lines.append("ТЕЛО: " + ", ".join(bits))

    mood_map = {"happy": "хорошее настроение", "worried": "немного беспокоится",
                "playful": "игривое настроение", "tender": "нежное настроение",
                "annoyed": "немного раздражена"}
    if mood_map.get(s.get("mood")):
        lines.append(f"НАСТРОЕНИЕ САКУРЫ: {mood_map[s['mood']]}")
    if s.get("note"):
        lines.append(f"ЗАМЕТКА: {s['note']}")

    for w in d["warnings"]:
        lines.append(f"⚠ {w}")

    if p.get("count_today", 0) > 0:
        topics = ", ".join(p["topics_today"][-3:]) if p["topics_today"] else ""
        lines.append(f"СЕГОДНЯ УЖЕ ПИСАЛА: {p['count_today']} раз" + (f" (темы: {topics})" if topics else ""))

    presence = get_presence(ctx)
    return "\n".join(lines) + f"\n\nПРИСУТСТВИЕ: {presence['directive']}"


# ─────────────────────────────────────────────
#  Быстрые предикаты
# ─────────────────────────────────────────────

def is_home_alone(ctx: dict = None) -> bool:
    ctx = ctx or get_full_context()
    return ctx["master"]["location"] == "home" and ctx["master"]["status"] in ("free", "sleeping")


def is_gaming(ctx: dict = None) -> bool:
    ctx = ctx or get_full_context()
    return ctx["master"]["is_gaming"]


def should_be_silent(ctx: dict = None) -> bool:
    ctx = ctx or get_full_context()
    if 2 <= ctx["time"]["hour"] < 7:
        return True
    return ctx["master"]["status"] in ("working", "studying")


# ── Фокус агента (из focus_seconds) ────────────────────────────────────

_focus_state: dict = {}  # window → {"since": float, "duration": int}

def set_focus_duration(window: str, seconds: int):
    """Сохраняет длительность фокуса в окне — от агента."""
    if not window:
        return
    _focus_state["current"] = {
        "window":   window,
        "duration": seconds,
    }

def get_focus_context() -> str:
    """Строка для промпта — если Мастер давно в одном окне."""
    focus = _focus_state.get("current")
    if not focus:
        return ""
    dur = focus.get("duration", 0)
    win = focus.get("window", "")
    if dur < 300:
        return ""
    mins = dur // 60
    if mins >= 120:
        return f"Мастер {mins // 60}ч {mins % 60}м в одном окне — возможно в потоке."
    return f"Мастер уже {mins} минут в «{win[:40]}»."


# ── Контекст экрана (из screen analysis) ──────────────────────────────

_screen_context: dict = {}  # window → {"description": str, "updated": float}

def set_screen_context(window: str, description: str):
    """Сохраняет описание экрана от Gemini Vision."""
    import time as _t
    if not window:
        return
    _screen_context["current"] = {
        "window":      window[:60],
        "description": description[:200],
        "updated":     _t.time(),
    }

def get_screen_context() -> str:
    """Строка для промпта — что на экране."""
    ctx = _screen_context.get("current")
    if not ctx:
        return ""
    import time as _t
    # Не старше 10 минут
    if _t.time() - ctx.get("updated", 0) > 600:
        return ""
    desc = ctx.get("description", "")
    if not desc:
        return ""
    return f"НА ЭКРАНЕ: {desc}"