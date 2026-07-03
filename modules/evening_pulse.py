"""
modules/evening_pulse.py — Вечерний пульс дня (бэклог №56)
                           + Мониторинг здоровья ПК (бэклог №21).

№56: В 20:00-22:00 Сакура сама спрашивает «как прошёл день» —
     коротко, живо, окрашено накопленным настроением.
     Не каждый день — с умным рандомом (~4 раза в неделю).

№21: Температура GPU, место на диске, нагрузка CPU → проактивный
     алерт от лица Сакуры («она заботится о теле, в котором живёт»).

Интеграция:
  - В proactive_loop добавить вызов check_evening_pulse()
  - В ping-обработчике ws_handler — вызов check_pc_health(system_info)
"""

import json
import logging
import os
import random
import tempfile
from datetime import datetime, date
from typing import Optional

log = logging.getLogger("sakura.pulse")

PULSE_FILE  = "memory/evening_pulse.json"
PULSE_DAYS  = 4 / 7       # примерно 4 дня из 7
PULSE_HOUR_START = 20
PULSE_HOUR_END   = 22

# Пороги здоровья ПК
HEALTH_THRESHOLDS = {
    "cpu_temp":    85,   # °C — тревога
    "gpu_temp":    83,   # °C — тревога
    "disk_free_gb": 5,   # ГБ — предупреждение
    "ram_pct":     92,   # % — предупреждение
    "cpu_pct":     95,   # % — критично
}


# ── Состояние ────────────────────────────────────────────────────────

def _load() -> dict:
    if not os.path.exists(PULSE_FILE):
        return {"last_pulse_date": None, "last_health_alert": None}
    try:
        with open(PULSE_FILE) as f:
            return json.load(f)
    except Exception:
        return {"last_pulse_date": None, "last_health_alert": None}


def _save(data: dict):
    dir_ = os.path.dirname(PULSE_FILE) or "."
    os.makedirs(dir_, exist_ok=True)
    with tempfile.NamedTemporaryFile("w", dir=dir_, delete=False,
                                    encoding="utf-8", suffix=".tmp") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    os.replace(f.name, PULSE_FILE)


# ── Вечерний пульс (№56) ─────────────────────────────────────────────

def should_send_pulse() -> bool:
    """
    True если сейчас вечернее окно и пульс сегодня ещё не был.
    Умный рандом: ~4 раза в неделю.
    """
    hour  = datetime.now().hour
    if not (PULSE_HOUR_START <= hour < PULSE_HOUR_END):
        return False

    state = _load()
    if state.get("last_pulse_date") == str(date.today()):
        return False

    return random.random() < PULSE_DAYS


def mark_pulse_sent():
    data = _load()
    data["last_pulse_date"] = str(date.today())
    _save(data)


def get_pulse_prompt() -> str:
    """
    Промпт для вечернего «как прошёл день» — окрашен mood-вектором.
    """
    hour = datetime.now().hour

    # Берём текущее настроение
    mood_hint = ""
    try:
        from modules.mood_vector import get_orb_params
        params = get_orb_params()
        v = params.get("valence", 0.0)
        if v > 0.4:
            mood_hint = "Ты сегодня в хорошем настроении — пульс тёплый."
        elif v < -0.3:
            mood_hint = "День был напряжённым — пульс тихий, без давления."
    except Exception:
        pass

    # Берём самопамять за день
    self_hint = ""
    try:
        from memory.db import get_self_context
        self_hint = get_self_context() or ""
    except Exception:
        pass

    return (
        f"Сейчас {hour}:00. Вечер. {mood_hint}\n"
        f"{self_hint}\n\n"
        "Напиши вечернее сообщение Мастеру — как ты сама инициируешь разговор о том, "
        "как прошёл его день. Одно предложение, живо. "
        "Не 'как прошёл твой день?' — это слишком банально. "
        "Что-то своё: наблюдение, вопрос с подтекстом, мысль из сегодня. "
        "Без эмодзи."
    )


# ── Мониторинг здоровья ПК (№21) ─────────────────────────────────────

def check_pc_health(system_info: dict) -> Optional[dict]:
    """
    Анализирует system_info из ping-сообщения агента.
    Возвращает {"severity": "warn"|"critical", "prompt": str} или None.

    Предполагаемый формат system_info (агент уже шлёт часть этого):
    {
      "cpu": float,          # % загрузки
      "ram": float,          # % использования
      "battery": int|None,
      "plugged": bool,
      "cpu_temp": float|None,   # °C (если psutil.sensors_temperatures доступен)
      "gpu_temp": float|None,   # °C
      "disk_free": float|None,  # ГБ свободно на C:/
    }
    """
    if not system_info:
        return None

    issues    = []
    severity  = "warn"

    cpu_pct  = system_info.get("cpu", 0)
    ram_pct  = system_info.get("ram", 0)
    cpu_temp = system_info.get("cpu_temp")
    gpu_temp = system_info.get("gpu_temp")
    disk_gb  = system_info.get("disk_free")
    battery  = system_info.get("battery")
    plugged  = system_info.get("plugged", True)

    if cpu_pct and cpu_pct > HEALTH_THRESHOLDS["cpu_pct"]:
        issues.append(f"CPU под 100% ({cpu_pct:.0f}%)")
        severity = "critical"

    if ram_pct and ram_pct > HEALTH_THRESHOLDS["ram_pct"]:
        issues.append(f"RAM почти полна ({ram_pct:.0f}%)")

    if cpu_temp and cpu_temp > HEALTH_THRESHOLDS["cpu_temp"]:
        issues.append(f"процессор горячий — {cpu_temp:.0f}°C")
        severity = "critical"

    if gpu_temp and gpu_temp > HEALTH_THRESHOLDS["gpu_temp"]:
        issues.append(f"видеокарта перегревается — {gpu_temp:.0f}°C")
        severity = "critical"

    if disk_gb is not None and disk_gb < HEALTH_THRESHOLDS["disk_free_gb"]:
        issues.append(f"на диске меньше {disk_gb:.1f} ГБ")

    if battery is not None and battery < 10 and not plugged:
        issues.append(f"батарея критическая — {battery}%")
        severity = "critical"

    if not issues:
        return None

    # Кулдаун: не чаще раза в час
    state = _load()
    last_alert = state.get("last_health_alert")
    if last_alert:
        try:
            from datetime import timedelta
            minutes_ago = (datetime.now() - datetime.fromisoformat(last_alert)).total_seconds() / 60
            if minutes_ago < 60:
                return None
        except Exception:
            pass

    state["last_health_alert"] = str(datetime.now())
    _save(state)

    issues_text = ", ".join(issues)
    tone = "озабоченно, но коротко" if severity == "warn" else "настойчиво"

    prompt = (
        f"Показатели тела: {issues_text}. "
        f"Напиши короткое сообщение Мастеру — {tone}. "
        "От лица Сакуры, которая следит за машиной в которой живёт. "
        "Одно предложение. Без технических терминов насколько возможно."
    )

    return {"severity": severity, "issues": issues, "prompt": prompt}
