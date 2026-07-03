"""
modules/disposition.py — Тонкий фасад для чтения текущей диспозиции.

Новое хранилище состояния НЕ создаётся. Модуль собирает из уже
существующих источников один словарь:
  - mood_vector  → valence, arousal
  - window_watcher → attention (тип окна)
  - стоячие намерения → пока заглушка (threads, capsules)

Потребители:
  1. _build_system() — перед генерацией (провод 1: предвербальное состояние)
  2. command_router  — обрамление подтверждения (провод 2)
  3. proactive_loop  — решение о добровольном действии
  4. episodes.add_episode() — запись действия (провод 3)

ЖЁСТКИЙ ИНВАРИАНТ: executor НИКОГДА не читает disposition.
Команда исполняется всегда. Диспозиция влияет только на обрамление.
"""

import logging

log = logging.getLogger("sakura.disposition")


def current() -> dict:
    """
    Возвращает текущую диспозицию — один маленький словарь.

    {
      "valence":   float,   # -1..+1 из mood_vector
      "arousal":   float,   #  0..1  из mood_vector
      "stance":    str,     # именованная точка (neutral/playful/annoyed/...)
      "willingness": float, # 0..1 — готовность к добровольным действиям
      "attention":  str,    # тип активного окна (call/game/code/browser/...)
      "quiet":     bool,    # тихий режим (созвон / полноэкранная игра)
    }
    """
    try:
        from modules.mood_vector import get_current as _mv_get
        m = _mv_get()
        v = m.get("valence", 0.0)
        a = m.get("arousal", 0.3)
    except Exception:
        v, a = 0.0, 0.3

    try:
        from modules.window_watcher import get_session_summary as _ws_summary
        ws = _ws_summary()
        attention = ws.get("current", "")
        quiet = ws.get("is_quiet", False)
    except Exception:
        attention = ""
        quiet = False

    return {
        "valence":    round(v, 2),
        "arousal":    round(a, 2),
        "stance":     _stance(v, a),
        "willingness": round(_willingness(v, a), 2),
        "attention":  attention,
        "quiet":      quiet,
    }


def _stance(valence: float, arousal: float) -> str:
    """
    Маппинг valence/arousal → именованная точка.
    Точки совпадают с _NAMED из mood_vector.py — никакого дублирования.
    """
    # Пороговые зоны — чем дальше от центра, тем ярче stance
    if valence > 0.55 and arousal > 0.70:
        return "excited"
    if valence > 0.55 and arousal < 0.35:
        return "tender"
    if valence > 0.50 and arousal > 0.45:
        return "playful"
    if valence > 0.50:
        return "happy"
    if valence < -0.45 and arousal > 0.55:
        return "annoyed"
    if valence < -0.30 and arousal < 0.25:
        return "lonely"
    if valence < -0.25 and arousal > 0.45:
        return "worried"
    if arousal < 0.18:
        return "calm"
    if arousal > 0.55:
        return "focused"
    return "neutral"


def _willingness(valence: float, arousal: float) -> float:
    """
    0..1 — готовность к добровольным действиям (инициатива, подколы, рекомендации).

    Не для команд — для proactive_loop и решения «добавить ли что-от себя».
    Низкая готовность: устала / расстроена / тихий режим / Мастер активен.
    Высокая: в хорошем расположении, много энергии, Мастер не в потоке.
    """
    # Базовая линия: комфорт = 0.5
    comfort = (valence + 1.0) / 2.0  # 0..1
    energy = arousal  # 0..1

    w = comfort * 0.6 + energy * 0.4

    # Штраф за тихий режим
    if _is_quiet():
        w *= 0.2

    # Штраф за высокую активность Мастера (он в потоке — не мешать)
    activity = _get_activity_hint()
    if activity > 0.7:
        w *= 0.4
    elif activity > 0.5:
        w *= 0.7

    return max(0.0, min(1.0, w))


def _is_quiet() -> bool:
    try:
        from modules.window_watcher import is_quiet_mode
        return is_quiet_mode()
    except Exception:
        return False


# ── Уровень активности агента ──────────────────────────────────────────

_activity_hint: float = 0.0

def _set_activity_hint(level: float):
    """Уровень активности мыши/клавиатуры от агента (0..1)."""
    global _activity_hint
    _activity_hint = max(0.0, min(1.0, level))

def _get_activity_hint() -> float:
    return _activity_hint


def stance_prompt() -> str:
    """
    Компактный блок для системного промпта.
    Если stance=neutral и willingness в норме — возвращаем пустую строку
    (не засоряем промпт очевидным).
    """
    d = current()
    stance = d["stance"]
    w = d["willingness"]

    if stance == "neutral" and 0.3 <= w <= 0.7:
        return ""

    parts = []

    _STANCE_MAP = {
        "playful":  "в игривом расположении",
        "tender":   "мягкая и заботливая",
        "happy":    "в хорошем настроении",
        "excited":  "в восторге, энергичная",
        "annoyed":  "слегка раздражена",
        "worried":  "немного насторожена",
        "lonely":   "немного грустная",
        "calm":     "спокойная и сосредоточенная",
        "focused":  "сосредоточена",
    }
    if stance in _STANCE_MAP:
        parts.append(_STANCE_MAP[stance])

    if w < 0.25:
        parts.append("мало энергии для инициатив")
    elif w > 0.8:
        parts.append("энергия на высоте — можно проявлять инициативу")

    if not parts:
        return ""

    return "ДИСПОЗИЦИЯ: " + ", ".join(parts)


def desire_hint() -> str:
    """
    Подсказка для промпта — когда у Сакуры есть энергия и интерес,
    она может проявить инициативу. Не заставляет — LLM сам решит.
    """
    d = current()
    w = d["willingness"]

    if w < 0.65:
        return ""

    # Есть энергия — подмешиваем интересы для инициативы
    try:
        from modules.relationship import get_sakura_interests
        interests = get_sakura_interests()
    except Exception:
        interests = []

    if not interests:
        return "У тебя сейчас энергия и хорошее расположение. Можешь проявить инициативу — предложить тему, поделиться мыслью, сделать что-то от себя."

    topic = interests[0]
    return (
        f"У тебя сейчас энергия и хорошее расположение. "
        f"Можешь проявить инициативу — например, обронить что-то про {topic} "
        f"или предложить что-нибудь от себя. Не обязательно — только если хочется."
    )
