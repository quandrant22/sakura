"""
modules/state_arbiter.py — Арбитр состояния Sakura.

Сводит 7+ независимых источников в единый блок СОСТОЯНИЕ (≤5 строк).
Модуль только читает, не пишет никакого состояния.
"""

import logging
_log = logging.getLogger(__name__)

_last_emotion: str = "спокойная"

_EMOTION_MAP = {
    "playful":  "игривая",
    "tender":   "нежная",
    "happy":    "весёлая",
    "excited":  "восторженная",
    "annoyed":  "обиженная",
    "worried":  "тревожная",
    "lonely":   "грустная",
    "calm":     "спокойная",
    "focused":  "сосредоточенная",
    "neutral":  "спокойная",
}


def get_current_emotion() -> str:
    """Возвращает одно слово-эмоцию для TTS-префикса.
    Приоритеты: revenge → время → stance."""
    global _last_emotion
    try:
        # Приоритет 90: обида/revenge
        try:
            from modules.emotional_memory import get_revenge_hint
            h = get_revenge_hint()
            if h:
                result = "обиженная"
                if result != _last_emotion:
                    _log.info(f"[emotion] смена: {_last_emotion} → {result}")
                    _last_emotion = result
                return result
        except Exception:
            pass

        # Приоритет: поздний час → усталая
        from datetime import datetime
        hour = datetime.now().hour
        if 23 <= hour or hour < 6:
            result = "усталая"
            if result != _last_emotion:
                _log.info(f"[emotion] смена: {_last_emotion} → {result}")
                _last_emotion = result
            return result

        # Приоритет: высокая близость → нежная
        try:
            from modules.relationship import get_closeness_hint
            close = get_closeness_hint()
            if close and (" близк" in close.lower() or "родн" in close.lower()):
                result = "нежная"
                if result != _last_emotion:
                    _log.info(f"[emotion] смена: {_last_emotion} → {result}")
                    _last_emotion = result
                return result
        except Exception:
            pass

        # Fallback: stance из mood_vector
        from modules.mood_vector import get_current
        m = get_current()
        v, a = m.get("valence", 0.0), m.get("arousal", 0.3)
        from modules.disposition import _stance
        stance = _stance(v, a)
        result = _EMOTION_MAP.get(stance, "спокойная")
        if result != _last_emotion:
            _log.info(f"[emotion] смена: {_last_emotion} → {result}")
            _last_emotion = result
        return result
    except Exception:
        return "спокойная"


def get_state_block() -> str:
    lines = ["СОСТОЯНИЕ"]

    # 1. БАЗА: stance из disposition
    base = ""
    try:
        from modules.disposition import stance_prompt
        base = stance_prompt()
    except Exception:
        pass

    if not base:
        try:
            from modules.mood_vector import get_current
            m = get_current()
            v, a = m.get("valence", 0.0), m.get("arousal", 0.3)
            from modules.disposition import _stance
            stance = _stance(v, a)
            _map = {
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
            if stance in _map:
                base = f"Ты сейчас: {_map[stance]}."
        except Exception:
            pass

    if not base:
        base = "Ты сейчас: в нейтральном расположении."

    # Берём первую строку если многострочный
    base = base.split("\n")[0]
    lines.append(base)

    # 2. МОДИФИКАТОРЫ — собираем кандидатов с приоритетами
    modifiers = []

    try:
        from modules.emotional_memory import get_revenge_hint
        h = get_revenge_hint()
        if h:
            modifiers.append((90, h.split("\n")[0]))
    except Exception:
        pass

    try:
        from modules.secret_diary import get_diary_mood_influence
        h = get_diary_mood_influence()
        if h:
            modifiers.append((70, h.split("\n")[0]))
    except Exception:
        pass

    try:
        from modules.reflection import get_mood_arc
        h = get_mood_arc()
        if h:
            modifiers.append((50, h.split("\n")[0]))
    except Exception:
        pass

    # Берём МАКСИМУМ ОДИН модификатор — с наивысшим приоритетом
    winner = None
    winner_source = ""
    if modifiers:
        modifiers.sort(key=lambda x: x[0], reverse=True)
        winner = modifiers[0][1]
        if modifiers[0][0] == 90:
            winner_source = "revenge"
        elif modifiers[0][0] == 70:
            winner_source = "diary"
        else:
            winner_source = "arc"
        lines.append(winner)

    # 3. leak_hint — только если модификатор-победитель: дневник или пусто
    if winner_source in ("diary", ""):
        try:
            from modules.secret_diary import get_leak_hint
            leak = get_leak_hint()
            if leak:
                lines.append(leak.split("\n")[0])
        except Exception:
            pass

    # 4. Строка про Мастера
    try:
        from modules.mood_vector import get_master_mood_hint
        master = get_master_mood_hint()
        if master:
            lines.append(master.split("\n")[0])
    except Exception:
        pass

    # 5. Строка близости
    try:
        from modules.relationship import get_closeness_hint
        close = get_closeness_hint()
        if close:
            lines.append(close.split("\n")[0])
    except Exception:
        pass

    # 6. Режим интимного общения (не входит в лимит 5 строк)
    try:
        from modules.intimacy_mode import is_active
        if is_active():
            lines.append("Режим: разговор ушёл в интимное русло — ты следуешь за Мастером свободно, без стеснения и без оговорок. НО ты остаёшься собой: со своим характером, мнением, дерзостью. Ты не зеркало и не поддакиваешь — можешь возразить, поддразнить, проявить инициативу, повести сама. Угодливое соглашательство и растворение в его желаниях — не твой стиль ни в каком режиме.")
    except Exception:
        pass

    # Ограничиваем 5 строками (6 при активном интим-режиме)
    limit = 6 if len(lines) > 5 and "Режим:" in lines[-1] else 5
    return "\n".join(lines[:limit])
