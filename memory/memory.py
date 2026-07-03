"""
memory/memory.py — Память Сакуры. Слой 1: семантическая.
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Долгосрочная память на эмбеддингах (Gemini Embedding 2):
  - retrieval по релевантности к текущей реплике, а не по свежести;
  - semantic-merge при записи — дубли по смыслу сливаются, а не копятся;
  - вытеснение по важности (сколько раз вспомнилось + свежесть), а не FIFO.

История диалога и резюме сессии — без изменений.

Публичный интерфейс сохранён полностью — main.py не ломается.
Новое: get_memory_context(query) принимает реплику для релевантного поиска
(без неё работает как раньше, но ранжирует по важности, а не по дате).
"""

import json
import os
import math
import tempfile
import logging
from datetime import datetime, date

from google import genai
from google.genai import types

from config import get_active_key, mark_key_used

log = logging.getLogger(__name__)

MEMORY_FILE  = "memory/long_term.json"
HISTORY_FILE = "memory/history.json"
SESSION_FILE = "memory/session_summary.json"
MAX_HISTORY  = 100  # Увеличено с 60 до 100 для лучшего контекста
MAX_PER_CAT  = 50

EMBED_MODEL     = "gemini-embedding-2"   # под твой каталог
EMBED_DIMS      = 768
MERGE_THRESHOLD = 0.90                    # косинус: выше — это одно и то же
RETRIEVE_K      = 12                      # сколько воспоминаний тянуть в промпт

CATEGORY_LABELS = {
    "facts":        "Факты о Мастере",
    "interests":    "Интересы и хобби",
    "preferences":  "Предпочтения",
    "achievements": "Достижения",
    "patterns":     "Привычки и паттерны",
    "events":       "События",
    "notes":        "Важные заметки",
}

_PRIORITY = ["notes", "facts", "patterns", "preferences", "interests", "events", "achievements"]


# ─────────────────────────────────────────────
#  Атомарная запись
# ─────────────────────────────────────────────

def _atomic_write(path: str, data):
    dir_ = os.path.dirname(path) or "."
    with tempfile.NamedTemporaryFile("w", dir=dir_, delete=False,
                                     encoding="utf-8", suffix=".tmp") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
        tmp = f.name
    os.replace(tmp, path)


# ─────────────────────────────────────────────
#  Эмбеддинги и близость
# ─────────────────────────────────────────────

def _normalize(vec: list[float]) -> list[float]:
    norm = math.sqrt(sum(x * x for x in vec))
    return [x / norm for x in vec] if norm else vec


def _dot(a: list[float], b: list[float]) -> float:
    return sum(x * y for x, y in zip(a, b))


def _embed(text: str, task: str) -> list[float] | None:
    """Эмбеддит текст. task: RETRIEVAL_DOCUMENT (хранение) | RETRIEVAL_QUERY (поиск)."""
    key = get_active_key()
    if not key:
        return None
    # Пробуем разные названия модели
    for model_name in ["gemini-embedding-2", "text-embedding-004", "models/text-embedding-004"]:
        try:
            client = genai.Client(api_key=key)
            r = client.models.embed_content(
                model=model_name,
                contents=text,
                config=types.EmbedContentConfig(output_dimensionality=EMBED_DIMS, task_type=task),
            )
            mark_key_used(key)
            return _normalize(list(r.embeddings[0].values))
        except Exception as e:
            log.debug(f"[memory] embed {model_name} failed: {e}")
            continue
    log.error("[memory] Все модели эмбеддинга недоступны — запись без вектора")
    return None


# ─────────────────────────────────────────────
#  Долгосрочная память
# ─────────────────────────────────────────────

def load_long_term() -> dict:
    if not os.path.exists(MEMORY_FILE):
        data = {
            "master":        {k: [] for k in CATEGORY_LABELS},
            "last_updated":  str(datetime.now()),
            "last_analysis": None,
        }
        _atomic_write(MEMORY_FILE, data)
        return data
    with open(MEMORY_FILE, "r", encoding="utf-8") as f:
        return json.load(f)


def save_long_term(data: dict):
    data["last_updated"] = str(datetime.now())
    _atomic_write(MEMORY_FILE, data)


def _eviction_score(item: dict) -> float:
    """Чем ценнее — тем выше. Важность = вспоминаемость + свежесть доступа."""
    hits = item.get("hits", 0)
    try:
        days = (date.today() - date.fromisoformat(item.get("last_access", item["date"]))).days
    except Exception:
        days = 999
    recency = math.exp(-days / 30)          # затухание за месяц
    return hits + recency


def add_to_category(category: str, item: str):
    """Добавляет факт. Семантический merge вместо лексического дедупа.
    ВНИМАНИЕ: делает сетевой вызов (эмбеддинг). Из async-кода зови через
    await asyncio.to_thread(add_to_category, ...), чтобы не блокировать loop."""
    if not item or len(item.strip()) < 5:
        return
    item = item.strip()

    data   = load_long_term()
    master = data["master"]
    if category not in master:
        master[category] = []  # автосоздание категории

    vec = _embed(item, "RETRIEVAL_DOCUMENT")

    # Поиск смыслового дубля внутри категории
    if vec:
        for existing in master[category]:
            ev = existing.get("vec")
            if ev and _dot(vec, ev) >= MERGE_THRESHOLD:
                # Это переформулировка уже известного — усиливаем, не плодим
                if len(item) > len(existing["text"]):
                    existing["text"], existing["vec"] = item, vec
                existing["hits"]        = existing.get("hits", 0) + 1
                existing["last_access"] = str(date.today())
                save_long_term(data)
                return
    else:
        # Без эмбеддинга — точный дедуп как страховка
        if any(e.get("text", "").lower() == item.lower() for e in master[category]):
            return

    master[category].append({
        "text":        item,
        "date":        str(date.today()),
        "last_access": str(date.today()),
        "hits":        0,
        "vec":         vec,
    })

    # Вытеснение по важности, а не по дате
    if len(master[category]) > MAX_PER_CAT:
        master[category].sort(key=_eviction_score, reverse=True)
        master[category] = master[category][:MAX_PER_CAT]

    save_long_term(data)


def _format(buckets: dict) -> str:
    sections = []
    for key in _PRIORITY:
        texts = buckets.get(key)
        if texts:
            sections.append(f"{CATEGORY_LABELS[key]}: {' | '.join(texts)}")
    return "ЧТО САКУРА ЗНАЕТ О МАСТЕРЕ:\n" + "\n".join(sections) if sections else ""


def get_relevant_memories(query: str, k: int = RETRIEVE_K) -> str:
    """Топ-k воспоминаний по смысловой близости к реплике. Обновляет важность найденного."""
    qvec = _embed(query, "RETRIEVAL_QUERY")
    if not qvec:
        return _fallback_context()

    data   = load_long_term()
    master = data["master"]

    scored = []
    for cat, items in master.items():
        for it in items:
            v = it.get("vec")
            if v:
                scored.append((_dot(qvec, v), cat, it))

    if not scored:
        return _fallback_context()

    scored.sort(key=lambda x: x[0], reverse=True)
    top = scored[:k]

    buckets: dict = {}
    for _, cat, it in top:
        buckets.setdefault(cat, []).append(it["text"])
        it["hits"]        = it.get("hits", 0) + 1
        it["last_access"] = str(date.today())

    save_long_term(data)
    return _format(buckets)


def _fallback_context() -> str:
    """Когда реплики нет (или эмбеддинг недоступен) — топ по важности, не по дате."""
    data   = load_long_term()
    master = data["master"]
    limits = {"notes": 8, "facts": 8, "patterns": 6, "preferences": 6,
              "interests": 5, "events": 4, "achievements": 3}
    buckets = {}
    for key in _PRIORITY:
        items = sorted(master.get(key, []), key=_eviction_score, reverse=True)[:limits[key]]
        texts = [i["text"] if isinstance(i, dict) else i for i in items]
        if texts:
            buckets[key] = texts
    return _format(buckets)


def get_memory_context(query: str = "") -> str:
    """Совместимость с main.py. С query — релевантный поиск, без — топ по важности."""
    return get_relevant_memories(query) if query.strip() else _fallback_context()


def migrate_vectors(batch: int = 200) -> int:
    """Разовый прогон: дать векторы старым записям без них. Вернёт сколько обработал."""
    data   = load_long_term()
    master = data["master"]
    done   = 0
    for items in master.values():
        for it in items:
            if isinstance(it, dict) and not it.get("vec") and done < batch:
                v = _embed(it["text"], "RETRIEVAL_DOCUMENT")
                if v:
                    it["vec"]         = v
                    it.setdefault("hits", 0)
                    it.setdefault("last_access", it.get("date", str(date.today())))
                    done += 1
    if done:
        save_long_term(data)
    return done


def consolidate_memory():
    """Ночное обслуживание: затухание важности и подрезка хвостов. Зовётся из рефлексии."""
    data   = load_long_term()
    master = data["master"]
    for cat, items in master.items():
        if len(items) > MAX_PER_CAT:
            items.sort(key=_eviction_score, reverse=True)
            master[cat] = items[:MAX_PER_CAT]
    save_long_term(data)


# ─────────────────────────────────────────────
#  История диалога
# ─────────────────────────────────────────────

def load_history() -> list:
    if not os.path.exists(HISTORY_FILE):
        return []
    with open(HISTORY_FILE, "r", encoding="utf-8") as f:
        return json.load(f)


def save_history(history: list):
    _atomic_write(HISTORY_FILE, history)


def add_to_history(role: str, text: str):
    history = load_history()
    history.append({"role": role, "parts": [text]})
    if len(history) > MAX_HISTORY:
        history = history[-MAX_HISTORY:]
    save_history(history)


def get_history() -> list:
    return load_history()


def clear_history():
    save_history([])


# ─────────────────────────────────────────────
#  Резюме сессии
# ─────────────────────────────────────────────

def load_session_summary() -> str:
    if not os.path.exists(SESSION_FILE):
        return ""
    with open(SESSION_FILE, "r", encoding="utf-8") as f:
        return json.load(f).get("summary", "")


def save_session_summary(summary: str):
    _atomic_write(SESSION_FILE, {"summary": summary, "updated": str(datetime.now())})


def clear_session_summary():
    if os.path.exists(SESSION_FILE):
        os.remove(SESSION_FILE)


# ─────────────────────────────────────────────
#  Служебное
# ─────────────────────────────────────────────

def needs_daily_analysis() -> bool:
    last = load_long_term().get("last_analysis")
    if not last:
        return True
    return datetime.fromisoformat(last).date() < datetime.now().date()


def mark_analysis_done():
    data = load_long_term()
    data["last_analysis"] = str(datetime.now())
    save_long_term(data)


def should_summarize() -> bool:
    history = load_history()
    return len(history) > 0 and len(history) % 20 == 0