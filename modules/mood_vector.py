"""
modules/mood_vector.py — Настроение как непрерывный вектор (бэклог №8).

Заменяет плоские ярлыки ("tender", "annoyed") парой координат:
  valence  [-1.0 … +1.0]  — отрицательно / положительно
  arousal  [ 0.0 …  1.0]  — спокойно / возбуждённо

Инерция: настроение не прыгает мгновенно, а «плывёт» к цели
с коэффициентом затухания. Это убирает главный шов личности.

Маппинг → орб и TTS:
  get_orb_params()  → {"color": hex, "pulse_amp": float, "petal_speed": float,
                        "petal_count": int, "inner_weather": str}
  get_tts_params()  → {"speed": float, "pitch_shift": float}
  get_mood_context()→ строка для системного промпта

Совместимость: публичный интерфейс старого mood.py сохранён через
обёртки mark_interaction() / get_mood_context() / auto_detect_mood_from_reply().

Хранение: memory/mood_vector.json (Сакура), memory/master_mood.json (Мастер).

НОВОЕ — Модель настроения Мастера (бэклог №4):
  update_master_mood(text, source)   — обновляет по тексту или просодии
  get_master_mood_hint() -> str      — блок для системного промпта
  get_master_mood() -> dict          — raw-вектор для внешнего использования
"""

import json
import logging
import math
import os
import re
import tempfile
from datetime import datetime
from typing import Optional

log = logging.getLogger("sakura.mood")

MOOD_FILE        = "memory/mood_vector.json"
MASTER_MOOD_FILE = "memory/master_mood.json"

# ── Инерция ──────────────────────────────────────────────────────────
ALPHA          = 0.15
DECAY_PER_HOUR = 0.08

# ── Словарь именованных точек ────────────────────────────────────────
_NAMED = {
    "neutral":  ( 0.00,  0.30),
    "happy":    ( 0.70,  0.55),
    "playful":  ( 0.60,  0.80),
    "tender":   ( 0.55,  0.25),
    "proud":    ( 0.65,  0.50),
    "worried":  (-0.40,  0.60),
    "annoyed":  (-0.55,  0.70),
    "lonely":   (-0.30,  0.15),
    "focused":  ( 0.10,  0.40),
    "excited":  ( 0.75,  0.90),
    "calm":     ( 0.20,  0.10),
}


# ── I/O Сакуры ───────────────────────────────────────────────────────

def _default() -> dict:
    return {
        "valence":          0.0,
        "arousal":          0.3,
        "target_valence":   0.0,
        "target_arousal":   0.3,
        "last_interaction": str(datetime.now()),
        "updated":          str(datetime.now()),
    }


def _load() -> dict:
    if not os.path.exists(MOOD_FILE):
        return _default()
    try:
        with open(MOOD_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return _default()


def _save(data: dict):
    data["updated"] = str(datetime.now())
    dir_ = os.path.dirname(MOOD_FILE) or "."
    os.makedirs(dir_, exist_ok=True)
    with tempfile.NamedTemporaryFile("w", dir=dir_, delete=False,
                                    encoding="utf-8", suffix=".tmp") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
        tmp = f.name
    os.replace(tmp, MOOD_FILE)


# ── Инерционное обновление ───────────────────────────────────────────

def _apply_decay(data: dict) -> dict:
    try:
        last  = datetime.fromisoformat(data["last_interaction"])
        hours = (datetime.now() - last).total_seconds() / 3600
        hour_now = datetime.now().hour
        if 2 <= hour_now < 8:
            return data
        decay = min(1.0, hours * DECAY_PER_HOUR)
        data["valence"] *= (1 - decay)
        data["arousal"]  = data["arousal"] * (1 - decay) + 0.3 * decay
        data["target_valence"] *= (1 - decay * 0.5)
        data["target_arousal"]  = (data["target_arousal"] * (1 - decay * 0.5)
                                    + 0.3 * decay * 0.5)
    except Exception:
        pass
    return data


def _step_toward_target(data: dict) -> dict:
    v, a   = data["valence"], data["arousal"]
    tv, ta = data["target_valence"], data["target_arousal"]
    data["valence"] = v + ALPHA * (tv - v)
    data["arousal"] = a + ALPHA * (ta - a)
    return data


def get_current() -> dict:
    data = _load()
    data = _apply_decay(data)
    data = _step_toward_target(data)
    return data


# ── Публичный API изменения настроения Сакуры ────────────────────────

def set_target(valence: float, arousal: float, blend: float = 1.0):
    valence = max(-1.0, min(1.0, valence))
    arousal = max( 0.0, min(1.0, arousal))
    data = _load()
    data["target_valence"] = (data["target_valence"] * (1 - blend) + valence * blend)
    data["target_arousal"] = (data["target_arousal"] * (1 - blend) + arousal * blend)
    data = _step_toward_target(data)
    _save(data)


def set_named(name: str, blend: float = 1.0):
    if name in _NAMED:
        v, a = _NAMED[name]
        set_target(v, a, blend)


def mark_interaction():
    data = _load()
    data["last_interaction"] = str(datetime.now())
    try:
        last  = datetime.fromisoformat(data.get("last_interaction", str(datetime.now())))
        hours = (datetime.now() - last).total_seconds() / 3600
        if hours > 8:
            data["target_valence"] = min(1.0, data["target_valence"] + 0.2)
    except Exception:
        pass
    _save(data)


def auto_detect_from_llm(reply: str, user_message: str):
    match = re.search(r"EMOTION:(\w+)", reply)
    if not match:
        combined = (reply + user_message).lower()
        if any(w in combined for w in ["смешно", "весело", "хаха", "лол"]):
            set_named("playful", blend=0.4)
        elif any(w in combined for w in ["спасибо", "молодец", "получилось"]):
            set_named("happy", blend=0.3)
        elif any(w in combined for w in ["бесит", "надоело", "ненавижу"]):
            set_named("worried", blend=0.4)
        return
    label_map = {
        "good": "happy", "evil": "annoyed", "neutral": "neutral",
        "playful": "playful", "tender": "tender", "proud": "proud",
        "worried": "worried", "excited": "excited",
    }
    set_named(label_map.get(match.group(1).lower(), "neutral"), blend=0.35)


# ── Модель настроения Мастера (бэклог №4) ────────────────────────────
#
# Хранит историю эмоционального дрейфа Мастера:
#   valence  — насколько он доволен/расстроен прямо сейчас
#   arousal  — насколько он взволнован/спокоен
#   trend    — "rising" | "falling" | "stable" — вектор последних N точек
#   history  — последние 24 точки (по одной в разговор), для тренда
#
# Сакура использует это подтекстом — не комментирует вслух, но меняет тон.

_MASTER_DECAY_PER_HOUR = 0.05   # медленнее чем у Сакуры — Мастер не «остывает» быстро

# Маркеры в тексте → смещение вектора Мастера
_MASTER_SIGNALS_POS = [
    "получилось", "сделал", "готово", "победил", "отлично", "круто",
    "спасибо", "хорошо", "нравится", "люблю", "рад", "доволен",
    "смешно", "хаха", "лол", "кайф", "топ", "огонь",
]
_MASTER_SIGNALS_NEG = [
    "бесит", "надоело", "устал", "не работает", "сломалось", "ошибка",
    "не могу", "проблема", "баг", "падает", "грустно", "плохо",
    "раздражает", "достало", "не получается", "не понимаю",
]
_MASTER_SIGNALS_HIGH_A = [
    "срочно", "быстро", "горит", "дедлайн", "паника", "помогите",
    "не успеваю", "жёстко", "вот это да", "серьёзно",
]
_MASTER_SIGNALS_LOW_A = [
    "окей", "ладно", "понял", "ок", "угу", "ага", "пойдёт",
]


def _master_default() -> dict:
    return {
        "valence":  0.0,
        "arousal":  0.3,
        "history":  [],          # list of [valence, arousal, iso_timestamp]
        "updated":  str(datetime.now()),
    }


def _master_load() -> dict:
    if not os.path.exists(MASTER_MOOD_FILE):
        return _master_default()
    try:
        with open(MASTER_MOOD_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return _master_default()


def _master_save(data: dict):
    data["updated"] = str(datetime.now())
    dir_ = os.path.dirname(MASTER_MOOD_FILE) or "."
    os.makedirs(dir_, exist_ok=True)
    with tempfile.NamedTemporaryFile("w", dir=dir_, delete=False,
                                    encoding="utf-8", suffix=".tmp") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
        tmp = f.name
    os.replace(tmp, MASTER_MOOD_FILE)


def _master_apply_decay(data: dict) -> dict:
    try:
        last  = datetime.fromisoformat(data["updated"])
        hours = (datetime.now() - last).total_seconds() / 3600
        decay = min(1.0, hours * _MASTER_DECAY_PER_HOUR)
        data["valence"] *= (1 - decay)
        data["arousal"]  = data["arousal"] * (1 - decay) + 0.3 * decay
    except Exception:
        pass
    return data


def _master_trend(history: list) -> str:
    """Тренд по последним точкам valence."""
    if len(history) < 3:
        return "stable"
    vals = [h[0] for h in history[-6:]]
    delta = vals[-1] - vals[0]
    if delta > 0.15:
        return "rising"
    if delta < -0.15:
        return "falling"
    return "stable"


def update_master_mood(text: str, source: str = "text",
                       prosody_valence: Optional[float] = None,
                       prosody_arousal: Optional[float] = None):
    """
    Обновляет вектор настроения Мастера.

    source="text"    — по ключевым словам в тексте сообщения
    source="prosody" — по данным STT-просодии (передать prosody_valence/arousal)
    source="both"    — оба источника, усредняются

    Вызывать из ask_gemini / voice_command handler при каждом сообщении Мастера.
    """
    data = _master_load()
    data = _master_apply_decay(data)

    dv, da = 0.0, 0.0  # смещения

    if source in ("text", "both"):
        tl = text.lower()
        pos = sum(1 for w in _MASTER_SIGNALS_POS  if w in tl)
        neg = sum(1 for w in _MASTER_SIGNALS_NEG  if w in tl)
        hi  = sum(1 for w in _MASTER_SIGNALS_HIGH_A if w in tl)
        lo  = sum(1 for w in _MASTER_SIGNALS_LOW_A  if w in tl)
        # Нормируем: каждый маркер даёт 0.12
        dv += (pos - neg) * 0.12
        da += (hi  - lo)  * 0.10
        # Длина сообщения: очень короткие → вялость (низкий a)
        if len(text) < 10:
            da -= 0.05

    if source in ("prosody", "both") and prosody_valence is not None:
        # Просодия имеет меньший вес чем текст
        dv += (prosody_valence - data["valence"]) * 0.20
        if prosody_arousal is not None:
            da += (prosody_arousal - data["arousal"]) * 0.15

    # Применяем со сжатием к границам
    data["valence"] = max(-1.0, min(1.0, data["valence"] + dv))
    data["arousal"] = max( 0.0, min(1.0, data["arousal"] + da))

    # Добавляем точку в историю (храним последние 24)
    history = data.get("history", [])
    history.append([round(data["valence"], 2), round(data["arousal"], 2),
                    str(datetime.now())])
    data["history"] = history[-24:]

    _master_save(data)


def get_master_mood() -> dict:
    """Возвращает текущий вектор настроения Мастера с трендом."""
    data = _master_load()
    data = _master_apply_decay(data)
    return {
        "valence": round(data["valence"], 2),
        "arousal": round(data["arousal"], 2),
        "trend":   _master_trend(data.get("history", [])),
        "history": data.get("history", []),
    }


def get_master_mood_hint() -> str:
    """
    Компактный блок для системного промпта.
    Сакура не называет это вслух — просто учитывает в тоне.
    Молчим если Мастер близко к нейтрали.
    """
    m = get_master_mood()
    v, a, trend = m["valence"], m["arousal"], m["trend"]

    # Нейтральная зона — не добавляем ничего
    if abs(v) < 0.20 and abs(a - 0.3) < 0.15:
        return ""

    parts = []

    if v > 0.45:
        parts.append("в хорошем расположении духа")
    elif v > 0.20:
        parts.append("настроен спокойно-позитивно")
    elif v < -0.45:
        parts.append("расстроен или раздражён")
    elif v < -0.20:
        parts.append("немного напряжён")

    if a > 0.70:
        parts.append("взволнован")
    elif a < 0.18:
        parts.append("вялый, пишет коротко")

    if trend == "rising":
        parts.append("настроение улучшается")
    elif trend == "falling":
        parts.append("настроение падает — будь мягче")

    if not parts:
        return ""

    return "СОСТОЯНИЕ МАСТЕРА (подтекст, не говори вслух): " + ", ".join(parts)


# ── Маппинг на орб ───────────────────────────────────────────────────

def get_orb_params() -> dict:
    data = get_current()
    v = data["valence"]
    a = data["arousal"]
    raw = _load()
    tv = raw.get("target_valence", v)
    ta = raw.get("target_arousal", a)

    if v >= 0:
        r = int(154 + v * 80)
        g = int(127 + v * 30)
        b = int(181 - v * 60)
    else:
        fac = -v
        r = int(154 - fac * 90)
        g = int(127 + fac * 50)
        b = int(181 + fac * 60)

    r = max(0, min(255, r))
    g = max(0, min(255, g))
    b = max(0, min(255, b))
    color = f"#{r:02x}{g:02x}{b:02x}"

    pulse_amp   = 0.03 + a * 0.11
    petal_speed = 0.5 + a * 1.0 + max(0, v) * 0.3
    petal_count = max(3, min(14, int(5 + max(0, v) * 6 + a * 3)))
    ring_speed  = 0.12 + a * 1.0

    if ta > 0.75 and tv < -0.3:
        inner_weather = "storm"
    elif ta < 0.25 and tv > 0.1:
        inner_weather = "shimmer"
    elif tv < -0.5:
        inner_weather = "fog"
    else:
        inner_weather = "clear"

    uncertainty = (1 - abs(v)) * (1 - abs(a - 0.5) * 2)
    glitch_prob = uncertainty * 0.006

    return {
        "color":         color,
        "pulse_amp":     round(pulse_amp, 3),
        "petal_speed":   round(petal_speed, 2),
        "petal_count":   petal_count,
        "ring_speed":    round(ring_speed, 2),
        "inner_weather": inner_weather,
        "glitch_prob":   round(glitch_prob, 4),
        "valence":       round(v, 2),
        "arousal":       round(a, 2),
    }


# ── Маппинг на TTS просодию ───────────────────────────────────────────

def get_tts_params() -> dict:
    data = get_current()
    v = data["valence"]
    a = data["arousal"]

    hour = datetime.now().hour
    night_factor = 0.85 if (22 <= hour or hour < 7) else 1.0

    speed_factor  = max(0.80, min(1.25, (0.90 + a * 0.30) * night_factor))
    volume_factor = max(0.78, min(1.05, 0.92 + v * 0.10))
    pause_factor  = max(0.65, min(1.45, 1.0 - a * 0.25 - v * 0.05))

    if a > 0.7 and v > 0.4:
        description = "оживлённо, быстро"
    elif a < 0.3 and v > 0.2:
        description = "спокойно, мягко"
    elif v < -0.4:
        description = "тихо, с паузами"
    elif a > 0.6 and v < -0.2:
        description = "напряжённо"
    else:
        description = ""

    return {
        "speed_factor":  round(speed_factor, 3),
        "volume_factor": round(volume_factor, 3),
        "pause_factor":  round(pause_factor, 3),
        "description":   description,
    }


# ── Промпт-блок Сакуры ────────────────────────────────────────────────

def get_mood_context() -> str:
    raw = _load()
    v = raw.get("target_valence", 0.0)
    a = raw.get("target_arousal", 0.3)

    if abs(v) < 0.25 and abs(a - 0.3) < 0.15:
        return ""

    parts = []
    if v > 0.6:
        parts.append("в хорошем настроении")
    elif v > 0.3:
        parts.append("настроение приподнятое")
    elif v < -0.6:
        parts.append("на душе неспокойно")
    elif v < -0.3:
        parts.append("чуть тревожно")

    if a > 0.75:
        parts.append("энергично")
    elif a < 0.20:
        parts.append("устала, говори тише")

    tts = get_tts_params()
    if tts["description"]:
        parts.append(f"темп: {tts['description']}")

    if not parts:
        return ""

    return "СОСТОЯНИЕ САКУРЫ: " + ", ".join(parts)


# ── Совместимость со старым mood.py ──────────────────────────────────

def update_mood(mood: str, energy: str = None, note: str = ""):
    if mood in _NAMED:
        blend = 0.6 if mood in ("lonely", "annoyed", "worried") else 0.4
        set_named(mood, blend=blend)


def auto_detect_mood_from_reply(reply: str, user_message: str):
    auto_detect_from_llm(reply, user_message)