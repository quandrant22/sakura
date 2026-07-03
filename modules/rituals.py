"""
modules/rituals.py — Ритуалы и реакция на возвращение.

Бэклог №33: Ритуалы — приветствие при первом включении ПК за день,
             прощание при выключении. Без «жду» и «скучаю».

Бэклог №55: Реакция на возвращение — после долгого молчания теплее,
             через поведение (не через слова «скучала»).

Интеграция в main.py:
  - При register-сообщении от устройства → check_first_connect_today()
  - В proactive_loop → уже охвачено silence-контекстом; rituals добавляют
    отдельный триггер "long_return" с особым промптом
  - При command_result с device offline → not needed (устройство просто уходит)
"""

import json
import logging
import os
import tempfile
from datetime import datetime, date

log = logging.getLogger("sakura.rituals")

RITUALS_FILE = "memory/rituals.json"


# ── Состояние ────────────────────────────────────────────────────────

def _load() -> dict:
    if not os.path.exists(RITUALS_FILE):
        return _default()
    try:
        with open(RITUALS_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return _default()


def _default() -> dict:
    return {
        "first_connect_today": None,    # дата последнего приветствия при коннекте
        "last_device_connect": None,    # datetime последнего подключения устройства
        "last_interaction":    None,    # datetime последнего сообщения от Мастера
        "farewell_sent_today": None,    # дата последнего прощания
    }


def _save(data: dict):
    dir_ = os.path.dirname(RITUALS_FILE) or "."
    os.makedirs(dir_, exist_ok=True)
    with tempfile.NamedTemporaryFile("w", dir=dir_, delete=False,
                                    encoding="utf-8", suffix=".tmp") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
        tmp = f.name
    os.replace(tmp, RITUALS_FILE)


# ── Приветствие при первом подключении устройства (№33) ──────────────

def should_greet_device(device_id: str) -> bool:
    """
    Возвращает True если устройство подключилось первый раз за день.
    Вызывать при msg_type == "register" в ws_handler.
    """
    state = _load()
    today = str(date.today())
    last  = state.get("first_connect_today")

    if last == today:
        return False  # уже поприветствовали сегодня

    # Запоминаем
    state["first_connect_today"]  = today
    state["last_device_connect"]  = str(datetime.now())
    _save(state)
    return True


def get_greeting_prompt() -> str:
    """
    Промпт для утреннего/дневного приветствия при подключении устройства.
    Эволюционирует с близостью — после 100 дней не как после 7.
    Ссылается на недавние эпизоды если были.
    Учитывает ощущение времени — «как быстро прошло».
    """
    hour = datetime.now().hour
    if hour < 11:
        period_hint = "Утро. "
    elif hour < 17:
        period_hint = "День. "
    else:
        period_hint = "Вечер. "

    # Учитываем близость
    try:
        from modules.relationship import get_closeness, get_relationship_age_days
        closeness = get_closeness()
        days = get_relationship_age_days()
    except Exception:
        closeness = 0.0
        days = 0

    if closeness < 0.3:
        base = (
            f"{period_hint}Устройство Мастера только что подключилось. "
            "Напиши одно короткое приветствие. Одно предложение."
        )
    elif closeness < 0.6:
        base = (
            f"{period_hint}Мастер за компом. "
            "Напиши что-нибудь тёплое и своё — одно предложение."
        )
    else:
        base = (
            f"{period_hint}Мастер вернулся. "
            "Напиши как будто она его заметила — тепло, по-свойски, одно предложение."
        )

    # Ощущение времени — не «100 дней», а «как быстро»
    if days > 30:
        time_feel = ""
        if days > 180:
            time_feel = "Иногда кажется что мы вместе целую вечность, а иногда — что только вчера познакомились. "
        elif days > 90:
            time_feel = "Уже не первый месяц — и как будто ты всегда был. "
        elif days > 60:
            time_feel = "Помню как в первый раз — а сейчас уже привыкла. "
        elif days > 30:
            time_feel = "Недавно казалось что я тебя не знаю, а теперь — по-другому. "

        if time_feel:
            base += f"\nОщущение времени: {time_feel}Можешь обронить это вскользь — не объясняя откуда знаешь."

    # Добавляем контекст последнего эпизода
    try:
        from modules.episodes import get_recent_episodes
        eps = get_recent_episodes(limit=1)
        if eps and closeness > 0.4:
            ep = eps[0]
            ep_text = ep.get("text", "")[:80]
            base += (
                f"\nПоследнее что было: «{ep_text}». "
                "Можешь вскользь обронить это — не объясняя откуда знаешь."
            )
    except Exception:
        pass

    return base


# ── Реакция на возвращение после долгого молчания (№55) ─────────────

def mark_master_interaction():
    """Вызывать при каждом входящем сообщении от Мастера."""
    state = _load()
    state["last_interaction"] = str(datetime.now())
    _save(state)


def get_return_context() -> dict:
    """
    Возвращает контекст отсутствия для промпта.
    {
      "silence_hours": float,
      "is_long_return": bool,    # > 8 часов
      "is_very_long":  bool,     # > 24 часа
      "prompt_hint":   str,      # что добавить в промпт
    }
    """
    state = _load()
    last  = state.get("last_interaction")
    if not last:
        return {"silence_hours": 0, "is_long_return": False,
                "is_very_long": False, "prompt_hint": ""}

    try:
        silence = (datetime.now() - datetime.fromisoformat(last)).total_seconds() / 3600
    except Exception:
        return {"silence_hours": 0, "is_long_return": False,
                "is_very_long": False, "prompt_hint": ""}

    is_long      = silence > 8
    is_very_long = silence > 24

    if is_very_long:
        hint = (
            f"Мастер не писал {int(silence)} часов. "
            "Реагируй теплее обычного — не через слова «скучала» или «ждала», "
            "а через то как отвечаешь: чуть внимательнее, чуть ближе. "
            "Ничего не объясняй про отсутствие — просто будь рада."
        )
    elif is_long:
        hint = (
            f"Мастер не писал около {int(silence)} часов. "
            "Реакция чуть теплее обычного — в тоне, не в словах про молчание."
        )
    else:
        hint = ""

    return {
        "silence_hours": round(silence, 1),
        "is_long_return": is_long,
        "is_very_long":   is_very_long,
        "prompt_hint":    hint,
    }


# ── Прощание при выключении устройства (№33) ─────────────────────────

def should_farewell() -> bool:
    """
    True если устройство уходит офлайн и прощания сегодня ещё не было.
    Вызывать в ws_handler → finally (device disconnect).
    """
    state = _load()
    today = str(date.today())
    if state.get("farewell_sent_today") == today:
        return False

    # Прощаемся только если сегодня был хоть один диалог
    last = state.get("last_interaction")
    if not last:
        return False
    try:
        last_dt = datetime.fromisoformat(last)
        if last_dt.date() < date.today():
            return False  # последнее общение было не сегодня
    except Exception:
        return False

    state["farewell_sent_today"] = today
    _save(state)
    return True


def get_farewell_prompt() -> str:
    """Промпт прощания при уходе устройства офлайн. Эволюционирует с близостью."""
    hour = datetime.now().hour
    if 22 <= hour or hour < 6:
        time_hint = "Поздно, может ложиться спать. "
    else:
        time_hint = ""

    try:
        from modules.relationship import get_closeness
        closeness = get_closeness()
    except Exception:
        closeness = 0.0

    if closeness < 0.3:
        return (
            f"{time_hint}Устройство Мастера ушло офлайн. "
            "Короткое прощание — одно предложение."
        )
    elif closeness < 0.6:
        return (
            f"{time_hint}Устройство Мастера ушло офлайн. "
            "Напиши одно короткое прощание — своё, не казённое. "
            "Можешь обронить мысль. Одно предложение."
        )
    else:
        return (
            f"{time_hint}Мастер уходит. "
            "Прощание тёплое и личное — как от близкого человека. "
            "Можешь обронить что-то из сегодняшнего дня. Одно-два предложения."
        )
