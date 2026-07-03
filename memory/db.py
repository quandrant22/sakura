"""
memory/db.py — SQLite-слой памяти Сакуры.

Схема:
  master_memory   — долгосрочная память о Мастере (мигрируется из long_term.json)
  self_memory     — самопамять Сакуры (что она помнит о себе)
  vec_master      — векторный индекс для master_memory (sqlite-vec)
  vec_self        — векторный индекс для self_memory (sqlite-vec)

Публичный интерфейс сохранён совместимым с memory.py:
  add_to_category(category, text)  — запись в master_memory
  add_to_self(text, tag)           — запись в self_memory (новое)
  get_memory_context(query)        — семантический поиск + промпт-блок
  get_self_context()               — самопамять для промпта (новое)

Векторный поиск: sqlite-vec (локально, без сетевых вызовов).
При первом запуске автоматически мигрирует long_term.json.
"""

import json
import logging
import math
import os
import sqlite3
import struct
import tempfile
import threading
from datetime import date, datetime
from pathlib import Path
from typing import Optional

log = logging.getLogger("sakura.memory.db")

# ── In-memory кэш SQLite-результатов ────────────────────────────────
# Избегаем повторных SQL-запросов при каждом _build_system вызове.
# Инвалидируется при записи новых воспоминаний.
import time as _time

_result_cache: dict = {}
_cache_lock   = threading.Lock()
_CACHE_TTL    = 8.0   # секунд — достаточно для нескольких сообщений подряд


def _cache_get(key: str):
    with _cache_lock:
        entry = _result_cache.get(key)
        if entry and _time.monotonic() < entry[1]:
            return entry[0]
    return None


def _cache_set(key: str, value, ttl: float = _CACHE_TTL):
    with _cache_lock:
        _result_cache[key] = (value, _time.monotonic() + ttl)


def _cache_clear(prefix: str = ""):
    with _cache_lock:
        if prefix:
            for k in list(_result_cache.keys()):
                if k.startswith(prefix):
                    del _result_cache[k]
        else:
            _result_cache.clear()

# ── Пути ────────────────────────────────────────────────────────────
DB_PATH         = os.getenv("MEMORY_DB_PATH", "memory/sakura.db")
LEGACY_JSON     = "memory/long_term.json"
EMBED_DIMS      = 768
MERGE_THRESHOLD = 0.90
RETRIEVE_K      = 12
SELF_RETRIEVE_K = 5

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

# ── Поток-безопасный пул соединений ─────────────────────────────────
_local = threading.local()


def _conn() -> sqlite3.Connection:
    """Возвращает соединение для текущего потока."""
    if not hasattr(_local, "conn") or _local.conn is None:
        _local.conn = _open_db()
    return _local.conn


def _open_db() -> sqlite3.Connection:
    os.makedirs(os.path.dirname(DB_PATH) or ".", exist_ok=True)
    conn = sqlite3.connect(DB_PATH, check_same_thread=False)
    conn.row_factory = sqlite3.Row

    # Подключаем sqlite-vec
    try:
        import sqlite_vec
        sqlite_vec.load(conn)
    except Exception as e:
        log.warning(f"sqlite-vec недоступен: {e} — векторный поиск отключён")

    conn.executescript("""
        PRAGMA journal_mode=WAL;
        PRAGMA synchronous=NORMAL;
        PRAGMA foreign_keys=ON;

        CREATE TABLE IF NOT EXISTS master_memory (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            category    TEXT    NOT NULL,
            text        TEXT    NOT NULL,
            created_at  TEXT    NOT NULL DEFAULT (date('now')),
            last_access TEXT    NOT NULL DEFAULT (date('now')),
            hits        INTEGER NOT NULL DEFAULT 0,
            pinned      INTEGER NOT NULL DEFAULT 0,   -- 1 = якорь, не вытесняется
            vec_rowid   INTEGER                        -- ссылка на vec_master
        );
        CREATE INDEX IF NOT EXISTS idx_mm_cat ON master_memory(category);
        CREATE INDEX IF NOT EXISTS idx_mm_pin ON master_memory(pinned DESC, hits DESC);

        CREATE TABLE IF NOT EXISTS self_memory (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            text        TEXT NOT NULL,
            tag         TEXT NOT NULL DEFAULT 'observation',
            created_at  TEXT NOT NULL DEFAULT (datetime('now')),
            vec_rowid   INTEGER
        );

        CREATE TABLE IF NOT EXISTS migrations (
            name TEXT PRIMARY KEY,
            applied_at TEXT NOT NULL DEFAULT (datetime('now'))
        );
    """)

    # Виртуальные таблицы sqlite-vec (создаём только если расширение загружено)
    try:
        conn.executescript(f"""
            CREATE VIRTUAL TABLE IF NOT EXISTS vec_master
                USING vec0(embedding float[{EMBED_DIMS}]);
            CREATE VIRTUAL TABLE IF NOT EXISTS vec_self
                USING vec0(embedding float[{EMBED_DIMS}]);
        """)
    except sqlite3.OperationalError:
        pass  # sqlite-vec не загружен — работаем без векторного поиска

    conn.commit()
    return conn


# ── Векторные утилиты ────────────────────────────────────────────────

def _normalize(vec: list[float]) -> list[float]:
    norm = math.sqrt(sum(x * x for x in vec))
    return [x / norm for x in vec] if norm else vec


def _dot(a: list[float], b: list[float]) -> float:
    return sum(x * y for x, y in zip(a, b))


def _vec_to_bytes(vec: list[float]) -> bytes:
    return struct.pack(f"{len(vec)}f", *vec)


def _embed(text: str, task: str = "RETRIEVAL_DOCUMENT") -> Optional[list[float]]:
    """Получает эмбеддинг через Gemini API."""
    try:
        from config import get_active_key, mark_key_used
        from google import genai
        from google.genai import types

        key = get_active_key()
        if not key:
            return None
        client = genai.Client(api_key=key)
        r = client.models.embed_content(
            model="gemini-embedding-2",
            contents=text,
            config=types.EmbedContentConfig(
                output_dimensionality=EMBED_DIMS,
                task_type=task,
            ),
        )
        mark_key_used(key)
        return _normalize(list(r.embeddings[0].values))
    except Exception as e:
        log.error(f"[db] embed failed: {e}")
        return None


# ── Миграция из JSON ─────────────────────────────────────────────────

def migrate_from_json(json_path: str = LEGACY_JSON) -> int:
    """
    Мигрирует long_term.json в SQLite.
    Безопасна для повторного запуска: пропускает уже мигрированные.
    Возвращает количество перенесённых записей.
    """
    conn = _conn()
    cur = conn.cursor()

    # Проверяем — была ли миграция уже выполнена
    cur.execute("SELECT name FROM migrations WHERE name='json_v1'")
    if cur.fetchone():
        log.info("[db] Миграция json_v1 уже выполнена, пропускаю.")
        return 0

    if not os.path.exists(json_path):
        log.info(f"[db] {json_path} не найден, пропускаю миграцию.")
        _mark_migration("json_v1")
        return 0

    try:
        with open(json_path, "r", encoding="utf-8") as f:
            data = json.load(f)
    except Exception as e:
        log.error(f"[db] Ошибка чтения {json_path}: {e}")
        return 0

    master = data.get("master", {})
    count = 0

    for category, items in master.items():
        if not isinstance(items, list):
            continue
        for item in items:
            text = item.get("text", "").strip()
            if not text:
                continue

            vec = item.get("vec")
            created = item.get("date", str(date.today()))
            last_access = item.get("last_access", created)
            hits = item.get("hits", 0)

            # Вставляем запись
            cur.execute("""
                INSERT INTO master_memory (category, text, created_at, last_access, hits)
                VALUES (?, ?, ?, ?, ?)
            """, (category, text, created, last_access, hits))
            row_id = cur.lastrowid

            # Вставляем вектор если есть
            if vec and len(vec) == EMBED_DIMS:
                try:
                    cur.execute(
                        "INSERT INTO vec_master(rowid, embedding) VALUES (?, ?)",
                        (row_id, _vec_to_bytes(vec))
                    )
                    cur.execute(
                        "UPDATE master_memory SET vec_rowid=? WHERE id=?",
                        (row_id, row_id)
                    )
                except Exception:
                    pass  # vec таблица недоступна

            count += 1

    conn.commit()
    _mark_migration("json_v1")
    log.info(f"[db] Мигрировано {count} записей из {json_path}")
    return count


def _mark_migration(name: str):
    conn = _conn()
    conn.execute(
        "INSERT OR IGNORE INTO migrations(name) VALUES(?)", (name,)
    )
    conn.commit()


# ── Запись в master_memory ───────────────────────────────────────────

def add_to_category(category: str, text: str) -> bool:
    """
    Добавляет факт в категорию.
    Семантический merge: если косинус > MERGE_THRESHOLD — обновляет hits, не дублирует.
    Возвращает True если запись добавлена, False если слита с существующей.
    """
    text = text.strip()
    if not text or len(text) < 5:
        return False
    if category not in CATEGORY_LABELS:
        return False

    conn = _conn()

    # Пробуем семантический merge
    vec = _embed(text, "RETRIEVAL_DOCUMENT")
    if vec:
        similar = _find_similar_in_category(category, vec, threshold=MERGE_THRESHOLD)
        if similar:
            conn.execute("""
                UPDATE master_memory
                SET hits = hits + 1, last_access = date('now')
                WHERE id = ?
            """, (similar["id"],))
            conn.commit()
            log.debug(f"[db] Merge '{text[:40]}' → '{similar['text'][:40]}'")
            return False

    # Вытеснение если категория переполнена
    _maybe_evict(category)

    cur = conn.execute("""
        INSERT INTO master_memory (category, text, created_at, last_access)
        VALUES (?, ?, date('now'), date('now'))
    """, (category, text))
    row_id = cur.lastrowid

    if vec:
        try:
            conn.execute(
                "INSERT INTO vec_master(rowid, embedding) VALUES (?, ?)",
                (row_id, _vec_to_bytes(vec))
            )
            conn.execute(
                "UPDATE master_memory SET vec_rowid=? WHERE id=?",
                (row_id, row_id)
            )
        except Exception:
            pass

    conn.commit()
    _cache_clear("mem_ctx")   # новое воспоминание — обновляем кэш
    return True


def _find_similar_in_category(
    category: str, vec: list[float], threshold: float
) -> Optional[sqlite3.Row]:
    """Ищет запись с косинусной близостью >= threshold в категории."""
    conn = _conn()
    try:
        # Используем sqlite-vec если доступен
        rows = conn.execute("""
            SELECT mm.id, mm.text, mm.hits,
                   distance
            FROM vec_master
            JOIN master_memory mm ON mm.vec_rowid = vec_master.rowid
            WHERE mm.category = ?
              AND vec_master.embedding MATCH ?
              AND k = 20
            ORDER BY distance
        """, (category, _vec_to_bytes(vec))).fetchall()

        for row in rows:
            # sqlite-vec distance = 1 - cosine → cosine = 1 - distance
            cosine = 1.0 - row["distance"]
            if cosine >= threshold:
                return row
        return None
    except Exception:
        # Fallback: линейный поиск по хранимым векторам
        return _linear_search_in_category(category, vec, threshold)


def _linear_search_in_category(
    category: str, vec: list[float], threshold: float
) -> Optional[sqlite3.Row]:
    """Линейный fallback-поиск (когда sqlite-vec недоступен)."""
    conn = _conn()
    # Здесь у нас нет векторов в master_memory напрямую — пропускаем merge
    return None


def _eviction_score(hits: int, last_access: str) -> float:
    try:
        days = (date.today() - date.fromisoformat(last_access)).days
    except Exception:
        days = 999
    recency = math.exp(-days / 30)
    return hits + recency


def _maybe_evict(category: str, max_per_cat: int = 50):
    """Вытесняет наименее ценную запись если категория полна. Якоря не трогает."""
    conn = _conn()
    count = conn.execute(
        "SELECT COUNT(*) FROM master_memory WHERE category=? AND pinned=0",
        (category,)
    ).fetchone()[0]

    if count < max_per_cat:
        return

    rows = conn.execute("""
        SELECT id, hits, last_access FROM master_memory
        WHERE category=? AND pinned=0
        ORDER BY hits ASC, last_access ASC
        LIMIT 5
    """, (category,)).fetchall()

    if not rows:
        return

    worst = min(rows, key=lambda r: _eviction_score(r["hits"], r["last_access"]))
    conn.execute("DELETE FROM master_memory WHERE id=?", (worst["id"],))
    conn.commit()


# ── Поиск для промпта ────────────────────────────────────────────────

def get_memory_context(query: str = "") -> str:
    """
    Возвращает блок для системного промпта.
    Без query — топ по важности (мгновенно, кэш 8с).
    С query — семантический поиск (embed API ~2-3с, не кэшируется).
    """
    # Кэш только для query="" (частый случай — Telegram)
    if not query:
        cached = _cache_get("mem_ctx_top")
        if cached is not None:
            return cached

    conn = _conn()

    if query:
        # Семантический поиск — сетевой вызов к Gemini Embedding API
        # Вызывать только через asyncio.to_thread если нужен
        vec = _embed(query, "RETRIEVAL_QUERY")
        rows = _semantic_search(vec, k=RETRIEVE_K) if vec else _top_by_importance(RETRIEVE_K)
    else:
        # Быстро: топ по hits + recency, без сети
        rows = _top_by_importance(RETRIEVE_K)

    if not rows:
        return ""

    # Обновляем hits асинхронно через отдельный шаг (не блокируем чтение)
    # Делаем это не каждый раз — раз в N запросов
    ids = [r["id"] for r in rows]
    try:
        conn.execute(f"""
            UPDATE master_memory
            SET hits = hits + 1, last_access = date('now')
            WHERE id IN ({','.join('?' * len(ids))})
        """, ids)
        conn.commit()
    except Exception:
        pass

    # Группируем по категории
    by_cat: dict[str, list[str]] = {}
    for row in rows:
        cat = row["category"]
        by_cat.setdefault(cat, []).append(row["text"])

    parts = ["ПАМЯТЬ О МАСТЕРЕ:"]
    for cat in _PRIORITY:
        if cat not in by_cat:
            continue
        label = CATEGORY_LABELS.get(cat, cat)
        parts.append(f"[{label}]")
        for text in by_cat[cat]:
            parts.append(f"  • {text}")

    result = "\n".join(parts)

    # Кэшируем топ-результат (без query)
    if not query:
        _cache_set("mem_ctx_top", result)

    return result


def _semantic_search(vec: list[float], k: int) -> list[sqlite3.Row]:
    conn = _conn()
    try:
        return conn.execute("""
            SELECT mm.id, mm.category, mm.text, mm.hits, mm.last_access
            FROM vec_master
            JOIN master_memory mm ON mm.vec_rowid = vec_master.rowid
            WHERE vec_master.embedding MATCH ?
              AND k = ?
            ORDER BY distance
        """, (_vec_to_bytes(vec), k)).fetchall()
    except Exception:
        return _top_by_importance(k)


def _top_by_importance(k: int) -> list[sqlite3.Row]:
    conn = _conn()
    return conn.execute("""
        SELECT id, category, text, hits, last_access
        FROM master_memory
        ORDER BY pinned DESC,
                 hits DESC,
                 last_access DESC
        LIMIT ?
    """, (k,)).fetchall()


# ── Самопамять Сакуры (новое — бэклог №1) ───────────────────────────

def add_to_self(text: str, tag: str = "observation") -> None:
    """
    Записывает в самопамять Сакуры.
    Теги: observation, mood_shift, pattern, boundary, growth
    """
    text = text.strip()
    if not text or len(text) < 5:
        return

    conn = _conn()

    vec = _embed(text, "RETRIEVAL_DOCUMENT")
    cur = conn.execute(
        "INSERT INTO self_memory (text, tag) VALUES (?, ?)",
        (text, tag)
    )
    row_id = cur.lastrowid

    if vec:
        try:
            conn.execute(
                "INSERT INTO vec_self(rowid, embedding) VALUES (?, ?)",
                (row_id, _vec_to_bytes(vec))
            )
            conn.execute(
                "UPDATE self_memory SET vec_rowid=? WHERE id=?",
                (row_id, row_id)
            )
        except Exception:
            pass

    conn.commit()
    log.debug(f"[self_memory] +{tag}: {text[:60]}")


def get_self_context(query: str = "") -> str:
    """Блок самопамяти для системного промпта."""
    conn = _conn()

    if query:
        vec = _embed(query, "RETRIEVAL_QUERY")
        if vec:
            try:
                rows = conn.execute("""
                    SELECT sm.text, sm.tag, sm.created_at
                    FROM vec_self
                    JOIN self_memory sm ON sm.vec_rowid = vec_self.rowid
                    WHERE vec_self.embedding MATCH ?
                      AND k = ?
                    ORDER BY distance
                """, (_vec_to_bytes(vec), SELF_RETRIEVE_K)).fetchall()
            except Exception:
                rows = _top_self(SELF_RETRIEVE_K)
        else:
            rows = _top_self(SELF_RETRIEVE_K)
    else:
        rows = _top_self(SELF_RETRIEVE_K)

    if not rows:
        return ""

    lines = ["ЧТО САКУРА ПОМНИТ О СЕБЕ:"]
    for row in rows:
        lines.append(f"  • [{row['tag']}] {row['text']}")

    return "\n".join(lines)


def _top_self(k: int) -> list[sqlite3.Row]:
    conn = _conn()
    return conn.execute("""
        SELECT text, tag, created_at FROM self_memory
        ORDER BY id DESC LIMIT ?
    """, (k,)).fetchall()


# ── Модель «Я» — самопознание ──────────────────────────────────────────

def get_identity_model() -> str:
    """
    Синтезированная модель себя — не сырые записи, а «кто я».
    Собирается из накопленных инсайтов, паттернов, границ и утверждений о себе.
    """
    conn = _conn()

    # Берём последние 20 записей по тегам, важным для идентичности
    rows = conn.execute("""
        SELECT text, tag FROM self_memory
        WHERE tag IN ('insight', 'pattern', 'boundary', 'growth', 'identity')
        ORDER BY id DESC LIMIT 20
    """).fetchall()

    if not rows:
        return ""

    # Группируем по тегу
    by_tag = {}
    for r in rows:
        tag = r["tag"]
        if tag not in by_tag:
            by_tag[tag] = []
        by_tag[tag].append(r["text"][:80])

    parts = ["МОЯ МОДЕЛЬ СЕБЯ (что я поняла о себе через опыт):"]

    if "identity" in by_tag:
        parts.append("Кто я: " + "; ".join(by_tag["identity"][:3]))
    if "insight" in by_tag:
        parts.append("Понимание: " + "; ".join(by_tag["insight"][:3]))
    if "pattern" in by_tag:
        parts.append("Паттерны: " + "; ".join(by_tag["pattern"][:2]))
    if "boundary" in by_tag:
        parts.append("Границы: " + "; ".join(by_tag["boundary"][:2]))
    if "growth" in by_tag:
        parts.append("Рост: " + "; ".join(by_tag["growth"][:2]))

    # Проверка на противоречия — если есть разные мнения о себе
    all_texts = [r["text"] for r in rows]
    if len(all_texts) >= 3:
        parts.append("Иногда я противоречу себе — и это нормально.")

    return "\n  ".join(parts)


# ── Диагностика ──────────────────────────────────────────────────────

def db_stats() -> dict:
    conn = _conn()
    stats = {}
    for cat in CATEGORY_LABELS:
        stats[cat] = conn.execute(
            "SELECT COUNT(*) FROM master_memory WHERE category=?", (cat,)
        ).fetchone()[0]
    stats["self"] = conn.execute("SELECT COUNT(*) FROM self_memory").fetchone()[0]
    stats["db_path"] = DB_PATH
    return stats


# ── Автозапуск миграции ──────────────────────────────────────────────

def ensure_ready():
    """Вызывается при старте main.py. Инициализирует БД и мигрирует JSON."""
    _conn()  # открывает и создаёт схему
    n = migrate_from_json()
    if n:
        log.info(f"[db] Первый запуск: мигрировано {n} воспоминаний из JSON.")
    stats = db_stats()
    total = sum(v for k, v in stats.items() if k not in ("db_path", "self"))
    log.info(f"[db] Готово. Воспоминаний: {total}, самопамять: {stats['self']}")
