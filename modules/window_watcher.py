"""
modules/window_watcher.py — Наблюдатель активного окна (бэклоги №16, №22).

№16: «Третий час в одном баге» — Сакура замечает долгий сеанс в одном
     приложении и предлагает перерыв или комментирует происходящее.

№22: Авто «не мешать» — детект созвона (Teams/Zoom/Discord call) и
     полноэкранного режима → Сакура переходит в тишину автоматически.

Интеграция: ws_handler получает ping с active_window → вызвать
  window_watcher.update(device_id, active_window, system_info)

Результат: watcher.get_insight() → строка для проактивного сообщения
           watcher.is_quiet_mode() → bool для подавления сообщений
"""

import json
import logging
import os
import tempfile
import time
from datetime import datetime, timedelta
from typing import Optional

log = logging.getLogger("sakura.window_watcher")

WATCHER_FILE = "memory/window_watcher.json"

# Приложения созвонов — авто-тишина
_CALL_APPS = {
    "teams", "zoom", "skype",
    "meet.google", "webex", "whereby",
    "google meet", "microsoft teams",
    "slack",  # только если fullscreen
}
# Discord — звонок только если окно содержит "voice" или "call" в заголовке
_CALL_DISCORD_HINTS = ("voice", "call", "звон", "voice channel")

# Сколько минут в одном окне → инсайт
FOCUS_THRESHOLD_MIN = 90

# Сколько минут в игре → не беспокоить
GAME_QUIET_MIN = 15

# Минимальный интервал между инсайтами
INSIGHT_COOLDOWN_MIN = 45


# ── I/O ──────────────────────────────────────────────────────────────

def _default() -> dict:
    return {
        "current_window":     "",
        "window_since":       None,   # ISO datetime
        "device_id":          None,
        "is_fullscreen":      False,
        "is_call":            False,
        "quiet_until":        None,   # ISO datetime
        "last_insight_at":    None,
        "last_insight_topic": None,
        "sessions": {},               # window_name → total_minutes
    }


def _load() -> dict:
    if not os.path.exists(WATCHER_FILE):
        return _default()
    try:
        with open(WATCHER_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return _default()


def _save(data: dict):
    dir_ = os.path.dirname(WATCHER_FILE) or "."
    os.makedirs(dir_, exist_ok=True)
    with tempfile.NamedTemporaryFile("w", dir=dir_, delete=False,
                                    encoding="utf-8", suffix=".tmp") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
        tmp = f.name
    os.replace(tmp, WATCHER_FILE)


# ── Детект типа окна ─────────────────────────────────────────────────

def _is_call_window(window: str) -> bool:
    wl = window.lower()
    # Обычные приложения звонков
    if any(app in wl for app in _CALL_APPS):
        return True
    # Discord — звонок только если в заголовке есть признак голосового канала
    if "discord" in wl:
        return any(hint in wl for hint in _CALL_DISCORD_HINTS)
    return False


def _is_game_window(window: str) -> bool:
    from personality import _GAME_KEYWORDS
    wl = window.lower()
    return any(k in wl for k in _GAME_KEYWORDS)


def _is_code_window(window: str) -> bool:
    wl = window.lower()
    code_hints = ("code", "visual studio", "pycharm", "intellij", "vim", "nvim",
                  ".py", ".js", ".ts", ".cpp", ".go", ".rs", "terminal", "powershell",
                  "cmd", "bash", "git")
    return any(h in wl for h in code_hints)


def _classify_window(window: str, is_fullscreen: bool) -> str:
    """Возвращает тип окна: call / game / code / browser / media / other."""
    if _is_call_window(window) and is_fullscreen:
        return "call"
    if _is_call_window(window):
        return "call"
    if _is_game_window(window):
        return "game"
    if _is_code_window(window):
        return "code"
    wl = window.lower()
    if any(b in wl for b in ("chrome", "firefox", "edge", "opera", "browser", "safari")):
        return "browser"
    if any(m in wl for m in ("vlc", "mpv", "netflix", "youtube", "spotify", "kodi")):
        return "media"
    return "other"


# ── Обновление состояния ─────────────────────────────────────────────

def update(device_id: str, active_window: str, system_info: dict = None):
    """
    Вызывать при каждом ping/register от устройства.
    Обновляет текущее окно и детектирует тихий режим.
    """
    data      = _load()
    now       = datetime.now()
    window    = (active_window or "").strip()
    fullscreen = bool(system_info and system_info.get("fullscreen"))

    # Трекинг смены окна
    if window != data.get("current_window") or device_id != data.get("device_id"):
        # Записываем время в предыдущем окне
        if data.get("window_since") and data.get("current_window"):
            try:
                since   = datetime.fromisoformat(data["window_since"])
                minutes = (now - since).total_seconds() / 60
                prev    = data["current_window"]
                sessions = data.get("sessions", {})
                sessions[prev] = sessions.get(prev, 0) + minutes
                # Чистим старые сессии (> 50 записей)
                if len(sessions) > 50:
                    worst = sorted(sessions, key=lambda k: sessions[k])[:10]
                    for k in worst:
                        del sessions[k]
                data["sessions"] = sessions
            except Exception:
                pass

        data["current_window"] = window
        data["window_since"]   = str(now)
        data["device_id"]      = device_id

    data["is_fullscreen"] = fullscreen

    # Определяем тихий режим (авто №22)
    wtype = _classify_window(window, fullscreen)
    data["is_call"] = (wtype == "call")

    if wtype == "call":
        # Тишина на 2 часа пока на созвоне
        quiet_until = now + timedelta(hours=2)
        data["quiet_until"] = str(quiet_until)
        log.info(f"[watcher] Созвон: тишина до {quiet_until.strftime('%H:%M')}")
    elif wtype == "game" and fullscreen:
        # В полноэкранной игре — не мешать
        quiet_until = now + timedelta(minutes=30)
        data["quiet_until"] = str(quiet_until)

    _save(data)


# ── Тихий режим ──────────────────────────────────────────────────────

def is_quiet_mode() -> bool:
    """True если Сакура должна молчать (созвон / полноэкранная игра)."""
    data = _load()
    if data.get("is_call"):
        return True
    quiet_until = data.get("quiet_until")
    if quiet_until:
        try:
            if datetime.now() < datetime.fromisoformat(quiet_until):
                return True
        except Exception:
            pass
    return False


def get_quiet_reason() -> Optional[str]:
    """Почему тишина — для логов."""
    data = _load()
    if data.get("is_call"):
        return "созвон"
    if data.get("is_fullscreen") and _is_game_window(data.get("current_window", "")):
        return "полноэкранная игра"
    return None


# ── Инсайты (№16) ────────────────────────────────────────────────────

def get_insight() -> Optional[dict]:
    """
    Возвращает инсайт если Мастер долго в одном окне и пора его заметить.
    Возвращает None если ещё рано или тихий режим.

    Формат ответа:
    {
      "prompt": str,     # промпт для Gemini
      "window": str,
      "minutes": int,
      "type": str,
    }
    """
    if is_quiet_mode():
        return None

    data   = _load()
    now    = datetime.now()
    window = data.get("current_window", "")
    since  = data.get("window_since")

    if not window or not since:
        return None

    # Считаем сколько времени в текущем окне
    try:
        minutes = (now - datetime.fromisoformat(since)).total_seconds() / 60
    except Exception:
        return None

    wtype = _classify_window(window, data.get("is_fullscreen", False))

    # Порог зависит от типа
    threshold = {
        "code":    FOCUS_THRESHOLD_MIN,
        "browser": FOCUS_THRESHOLD_MIN + 30,
        "other":   FOCUS_THRESHOLD_MIN,
    }.get(wtype, FOCUS_THRESHOLD_MIN)

    if minutes < threshold:
        return None

    # Кулдаун
    last = data.get("last_insight_at")
    if last:
        try:
            if (now - datetime.fromisoformat(last)).total_seconds() / 60 < INSIGHT_COOLDOWN_MIN:
                return None
        except Exception:
            pass

    # Разные промпты под тип
    app_name = window.split("—")[-1].strip() if "—" in window else window[:40]
    mins_h   = f"{int(minutes // 60)}ч {int(minutes % 60)}м" if minutes >= 60 else f"{int(minutes)}м"

    if wtype == "code":
        prompt = (
            f"Мастер пишет код в {app_name} уже {mins_h} без перерыва. "
            "Напиши одно короткое сообщение — заметь это. "
            "Можешь предложить перерыв, но ненавязчиво. "
            "Или просто оброни наблюдение. Без советов про здоровье."
        )
    elif wtype == "browser":
        prompt = (
            f"Мастер в браузере ({app_name}) уже {mins_h}. "
            "Один короткий комментарий — что-то своё, живое. "
            "Не спрашивай 'что смотришь'."
        )
    else:
        prompt = (
            f"Мастер в приложении '{app_name}' уже {mins_h}. "
            "Оброни что-нибудь — замечание, вопрос, мысль. "
            "Одно предложение."
        )

    # Отмечаем что инсайт был
    data["last_insight_at"]    = str(now)
    data["last_insight_topic"] = wtype
    _save(data)

    return {
        "prompt":  prompt,
        "window":  window,
        "minutes": int(minutes),
        "type":    wtype,
    }


def get_session_summary() -> dict:
    """Статистика текущих сессий для рефлексии."""
    data     = _load()
    sessions = data.get("sessions", {})
    # Топ-5 по времени
    top = sorted(sessions.items(), key=lambda x: x[1], reverse=True)[:5]
    return {
        "top_apps":      [{"window": w, "minutes": int(m)} for w, m in top],
        "current":       data.get("current_window", ""),
        "is_quiet":      is_quiet_mode(),
        "quiet_reason":  get_quiet_reason(),
    }
