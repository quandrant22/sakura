"""
modules/state_arbiter.py — Арбитр состояния Sakura.

Сводит 7+ независимых источников в единый блок СОСТОЯНИЕ (≤5 строк).
Модуль только читает, не пишет никакого состояния.
"""


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
            from modules.disposition import _stance, _STANCE_MAP as _sm
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
    if winner_source != "revenge":
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

    # Ограничиваем 5 строками (включая заголовок)
    return "\n".join(lines[:5])
