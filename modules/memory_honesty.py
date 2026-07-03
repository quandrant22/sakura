"""
modules/memory_honesty.py — Честность памяти (бэклоги №6, №54).

№6: Ощутимое забывание — когда факт давно не запрашивался и
    имеет низкий hits, Сакура честно признаёт что «подзабыла».
    Это живость, а не баг.

№54: «Я не уверена» — когда в памяти есть противоречащие друг
     другу факты по одной теме, Сакура это замечает и не
     выбирает уверенно, а признаёт противоречие.

Интеграция:
  В personality.py / _build_system():
    from modules.memory_honesty import get_honesty_context
    honesty = get_honesty_context(query)
    if honesty:
        parts.append(honesty)

  В ask_gemini() при формировании memory_ctx:
    context = get_memory_context(query)
    honesty = get_honesty_context(query, context)
"""

import logging
import math
from datetime import date, datetime
from typing import Optional

log = logging.getLogger("sakura.memory_honesty")

# Факт считается «подзабытым» если:
FORGOTTEN_DAYS  = 60   # не запрашивался N дней
FORGOTTEN_HITS  = 3    # и у него мало обращений

# Порог противоречия: два факта по одной теме с косинусом > CONFLICT_COS
# считаются потенциально противоречивыми
CONFLICT_COS    = 0.85
CONFLICT_DELTA  = 30   # дней — факты созданы с разницей > N дней (обновление)


def _get_low_confidence_facts(query: str, limit: int = 3) -> list[dict]:
    """
    Находит факты которые Сакура могла «подзабыть»:
    давно не запрашивались и имеют мало hits.
    Только если они семантически близки к текущему запросу.
    """
    try:
        from memory.db import _conn, _embed, _vec_to_bytes
        conn = _conn()

        # Ищем семантически близкие факты с низким confidence
        vec = _embed(query, "RETRIEVAL_QUERY")
        if vec:
            try:
                rows = conn.execute("""
                    SELECT mm.id, mm.text, mm.category,
                           mm.hits, mm.last_access, mm.created_at,
                           distance
                    FROM vec_master
                    JOIN master_memory mm ON mm.vec_rowid = vec_master.rowid
                    WHERE vec_master.embedding MATCH ?
                      AND k = 10
                    ORDER BY distance
                """, (_vec_to_bytes(vec),)).fetchall()
            except Exception:
                rows = []
        else:
            rows = []

        forgotten = []
        today = date.today()
        for row in rows:
            try:
                last = date.fromisoformat(row["last_access"][:10])
                days_ago = (today - last).days
            except Exception:
                days_ago = 0

            if days_ago >= FORGOTTEN_DAYS and row["hits"] <= FORGOTTEN_HITS:
                forgotten.append({
                    "text":     row["text"],
                    "category": row["category"],
                    "days_ago": days_ago,
                    "hits":     row["hits"],
                })

        return forgotten[:limit]

    except Exception as e:
        log.debug(f"[honesty] low_confidence: {e}")
        return []


def _detect_contradictions(query: str) -> list[dict]:
    """
    Ищет пары фактов по одной теме, созданные в разное время
    (обновление информации = потенциальное противоречие).
    """
    try:
        from memory.db import _conn, _embed, _vec_to_bytes
        conn = _conn()

        vec = _embed(query, "RETRIEVAL_QUERY")
        if not vec:
            return []

        try:
            rows = conn.execute("""
                SELECT mm.id, mm.text, mm.category,
                       mm.created_at, mm.hits, distance
                FROM vec_master
                JOIN master_memory mm ON mm.vec_rowid = vec_master.rowid
                WHERE vec_master.embedding MATCH ?
                  AND k = 8
                ORDER BY distance
            """, (_vec_to_bytes(vec),)).fetchall()
        except Exception:
            return []

        if len(rows) < 2:
            return []

        conflicts = []
        for i in range(len(rows)):
            for j in range(i + 1, len(rows)):
                a, b = rows[i], rows[j]
                # Семантически близкие (low distance = high cosine)
                cos_a = 1.0 - a["distance"]
                cos_b = 1.0 - b["distance"]
                if cos_a < CONFLICT_COS or cos_b < CONFLICT_COS:
                    continue

                # Созданы в разное время (обновление)
                try:
                    date_a = datetime.fromisoformat(a["created_at"][:10]).date()
                    date_b = datetime.fromisoformat(b["created_at"][:10]).date()
                    delta  = abs((date_a - date_b).days)
                except Exception:
                    continue

                if delta >= CONFLICT_DELTA:
                    conflicts.append({
                        "older": {"text": a["text"], "date": str(date_a)},
                        "newer": {"text": b["text"], "date": str(date_b)},
                        "delta_days": delta,
                    })

        return conflicts[:2]   # максимум 2 пары

    except Exception as e:
        log.debug(f"[honesty] contradictions: {e}")
        return []


def get_honesty_context(query: str = "") -> str:
    """
    Возвращает блок для системного промпта — инструкции честности.
    Пустая строка если всё в порядке.

    Два случая:
      1. Подзабытые факты → Сакура должна признать неуверенность
      2. Противоречия → Сакура должна назвать оба варианта

    Не вызываем каждый раз — только если query непустой.
    """
    if not query or len(query) < 5:
        return ""

    lines = []

    # №6: Подзабытые факты
    forgotten = _get_low_confidence_facts(query)
    if forgotten:
        texts = [f["text"][:60] for f in forgotten]
        lines.append(
            "ОСТОРОЖНО — СЛАБЫЕ ВОСПОМИНАНИЯ: следующие факты давно не всплывали "
            "и могут быть неточными. Если они нужны для ответа — признай что помнишь смутно, "
            "не выдавай за достоверное: " + "; ".join(texts)
        )

    # №54: Противоречия
    conflicts = _detect_contradictions(query)
    if conflicts:
        for c in conflicts:
            lines.append(
                f"ВОЗМОЖНОЕ ПРОТИВОРЕЧИЕ: раньше было «{c['older']['text'][:50]}» "
                f"({c['older']['date']}), потом — «{c['newer']['text'][:50]}» "
                f"({c['newer']['date']}). "
                "Если тема всплывёт — признай что у тебя два разных воспоминания, "
                "не угадывай какое правильное."
            )

    return "\n".join(lines) if lines else ""


def get_memory_confidence(fact_text: str) -> float:
    """
    Возвращает уверенность [0.0 .. 1.0] для конкретного факта.
    Используется для маркировки в get_memory_context().
    """
    try:
        from memory.db import _conn
        conn = _conn()
        row  = conn.execute("""
            SELECT hits, last_access FROM master_memory
            WHERE text = ?
            LIMIT 1
        """, (fact_text,)).fetchone()

        if not row:
            return 0.5

        today    = date.today()
        last     = date.fromisoformat(row["last_access"][:10])
        days_ago = (today - last).days
        hits     = row["hits"]

        # Уверенность: много hits + недавно = высокая
        recency_score = math.exp(-days_ago / 30)
        hits_score    = min(1.0, hits / 20)
        return round((recency_score * 0.5 + hits_score * 0.5), 2)

    except Exception:
        return 0.5


# ── Патч get_memory_context для маркировки низкой уверенности ────────

def enrich_memory_context(raw_context: str, query: str = "") -> str:
    """
    Принимает обычный memory_context и добавляет маркер [?] к фактам
    с низкой уверенностью. Вызывать вместо get_memory_context() в промпте.

    Лёгкая версия: просто добавляет honesty_context в конец.
    """
    honesty = get_honesty_context(query)
    if not honesty:
        return raw_context
    return raw_context + "\n\n" + honesty if raw_context else honesty
