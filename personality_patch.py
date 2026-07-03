"""
personality_patch.py — патч для personality.py.

Добавляет в get_system_prompt():
  1. Блок самопамяти Сакуры из memory.db (бэклог №1)
  2. Контекст возвращения из modules/rituals.py (бэклог №55)

Применение: заменить get_adaptation_context() и get_system_prompt()
в оригинальном personality.py на версии ниже.

Или вставить импорты в начало personality.py:
    from personality_patch import get_self_block, get_return_hint
И добавить вызовы в get_system_prompt() перед return.
"""

# ──────────────────────────────────────────────────────────────────
# Эти две функции вставить В personality.py (или импортировать)
# ──────────────────────────────────────────────────────────────────


def get_self_block() -> str:
    """
    Возвращает блок самопамяти Сакуры для системного промпта.
    Не падает если memory.db недоступна.
    """
    try:
        from memory.db import get_self_context
        ctx = get_self_context()
        return ctx if ctx else ""
    except Exception:
        return ""


def get_return_hint(query: str = "") -> str:
    """
    Возвращает подсказку для промпта если Мастер долго отсутствовал.
    Не падает если rituals.py недоступен.
    """
    try:
        from modules.rituals import get_return_context
        ctx = get_return_context()
        return ctx.get("prompt_hint", "")
    except Exception:
        return ""


# ──────────────────────────────────────────────────────────────────
# Обновлённая get_adaptation_context — читает из SQLite, не из JSON
# ──────────────────────────────────────────────────────────────────

def get_adaptation_context() -> str:
    """
    Строит блок «ЧТО СТОИТ ПОМНИТЬ» из SQLite-памяти.
    Обратно совместима с оригиналом — тот же формат вывода.
    """
    try:
        from memory.db import _conn
        conn = _conn()

        patterns = conn.execute("""
            SELECT text FROM master_memory
            WHERE category='patterns'
            ORDER BY hits DESC, last_access DESC
            LIMIT 6
        """).fetchall()
        prefs = conn.execute("""
            SELECT text FROM master_memory
            WHERE category='preferences'
            ORDER BY hits DESC, last_access DESC
            LIMIT 6
        """).fetchall()

        all_text = " ".join(
            [r["text"] for r in patterns] + [r["text"] for r in prefs]
        ).lower()

        lines = []
        if any(w in all_text for w in ["ночь", "не высыпается", "устаёт"]):
            lines.append("— Часто не высыпается. Замечай сама.")
        if any(w in all_text for w in ["лаконичен", "коротко", "по делу"]):
            lines.append("— Ценит краткость.")
        if any(w in all_text for w in ["юмор", "подколы", "сарказм"]):
            lines.append("— Любит юмор и подколы.")
        if any(w in all_text for w in ["перфекционизм", "шлифует"]):
            lines.append("— Перфекционист. Иногда стоит мягко вернуть к общей картине.")
        if not lines:
            return ""

        return "ЧТО СТОИТ ПОМНИТЬ:\n" + "\n".join(lines)

    except Exception:
        # Fallback на JSON если SQLite недоступна
        try:
            import json, os
            path = "memory/long_term.json"
            if not os.path.exists(path):
                return ""
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
            master = data.get("master", {})
            pattern_texts = [p["text"] if isinstance(p, dict) else p
                             for p in master.get("patterns", [])[-6:]]
            pref_texts    = [p["text"] if isinstance(p, dict) else p
                             for p in master.get("preferences", [])[-6:]]
            all_text = " ".join(pattern_texts + pref_texts).lower()
            lines = []
            if any(w in all_text for w in ["ночь", "не высыпается", "устаёт"]):
                lines.append("— Часто не высыпается. Замечай сама.")
            if any(w in all_text for w in ["лаконичен", "коротко", "по делу"]):
                lines.append("— Ценит краткость.")
            if not lines:
                return ""
            return "ЧТО СТОИТ ПОМНИТЬ:\n" + "\n".join(lines)
        except Exception:
            return ""


# ──────────────────────────────────────────────────────────────────
# Пример — как вставить в get_system_prompt() в personality.py:
# ──────────────────────────────────────────────────────────────────
#
#   from personality_patch import get_self_block, get_return_hint, get_adaptation_context
#
#   def get_system_prompt(...):
#       ...
#       adaptation = get_adaptation_context()   # заменяет оригинальный вызов
#       self_block = get_self_block()           # новое
#       return_hint = get_return_hint()         # новое
#       ...
#       return f"""...
#   {adaptation}{game_context}
#   {self_block}
#   {return_hint}
#
#   НИКОГДА
#   ...
#   """
#
# В _build_system() в main.py больше ничего менять не нужно —
# самопамять встраивается в сам системный промпт.
