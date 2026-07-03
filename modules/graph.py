"""
modules/graph.py — Граф связей памяти (бэклог: continuity / personality-in-data).

Поверх плоской семантической памяти (master_memory) строим лёгкий граф:
кто/что с кем/чем связан. Сущности — люди, проекты, места, игры, события.
Рёбра — отношения между ними с весом (как часто всплывают вместе).

Принципы под ограничения сервера:
  • НИКАКОГО фонового цикла и постоянного CPU — граф пополняется попутно,
    в том же extract_and_remember, который уже зовёт LLM раз в N сообщений.
  • НИКАКИХ эмбеддингов и сети на пути чтения — только SQL по sakura.db.
  • Чисто аддитивно — таблицы создаются лениво, старая память не трогается.

Публичный API:
  ingest(entities, relations)        — записать (из extract_and_remember)
  get_graph_context(query="") -> str — компактный блок для системного промпта
  related(name) -> list[dict]        — «что связано с X» (для голоса/чата)
  anniversaries_today() -> list[dict]— события-годовщины на сегодня (для briefing)
  forget(name) -> int                — стереть сущность и её рёбра («забудь X»)
"""

import logging
from datetime import datetime, date
from typing import Optional

log = logging.getLogger("sakura.graph")

# Типы сущностей (мягкая онтология; 'thing' — дефолт/заглушка)
_TYPES = {"person", "project", "place", "game", "org", "event", "thing"}
_GENERIC = "thing"


# ── Схема (ленивое создание) ─────────────────────────────────────────

def _ensure_tables():
    from memory.db import _conn
    conn = _conn()
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS entities (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            name        TEXT    NOT NULL UNIQUE,   -- нормализованное (lower)
            display     TEXT    NOT NULL,          -- как написал Мастер
            type        TEXT    NOT NULL DEFAULT 'thing',
            mentions    INTEGER NOT NULL DEFAULT 1,
            event_date  TEXT,                      -- ISO, только для type='event'
            first_seen  TEXT    NOT NULL DEFAULT (datetime('now')),
            last_seen   TEXT    NOT NULL DEFAULT (datetime('now'))
        );
        CREATE TABLE IF NOT EXISTS edges (
            src         INTEGER NOT NULL,
            dst         INTEGER NOT NULL,
            relation    TEXT    NOT NULL DEFAULT 'связан',
            weight      INTEGER NOT NULL DEFAULT 1,
            last_seen   TEXT    NOT NULL DEFAULT (datetime('now')),
            PRIMARY KEY (src, dst, relation)
        );
        CREATE INDEX IF NOT EXISTS idx_entities_last  ON entities(last_seen DESC);
        CREATE INDEX IF NOT EXISTS idx_edges_src      ON edges(src);
        CREATE INDEX IF NOT EXISTS idx_edges_dst      ON edges(dst);
    """)
    conn.commit()


def _norm(name: str) -> str:
    return " ".join((name or "").strip().lower().split())


def _stem(w: str) -> str:
    """Грубая основа: отбрасываем окончание. Дёшево против склонений."""
    return w[:max(3, len(w) - 2)] if len(w) > 3 else w


def _query_match(name: str, query_tokens: list) -> bool:
    """Имя сущности «встречается» в запросе с учётом склонений (префикс по основе)."""
    for part in name.split():
        if len(part) < 3:
            continue
        ps = _stem(part)
        for qt in query_tokens:
            if len(qt) < 3:
                continue
            if qt == part or qt.startswith(ps) or part.startswith(_stem(qt)):
                return True
    return False


# ── Запись ───────────────────────────────────────────────────────────

def _upsert_entity(conn, name: str, etype: str = _GENERIC,
                   event_date: Optional[str] = None) -> Optional[int]:
    norm = _norm(name)
    if not norm or len(norm) > 80:
        return None
    etype = etype if etype in _TYPES else _GENERIC
    row = conn.execute("SELECT id, type FROM entities WHERE name=?", (norm,)).fetchone()
    if row:
        eid, cur_type = row[0], row[1]
        # Уточняем тип, если раньше был дефолтным
        new_type = etype if (cur_type == _GENERIC and etype != _GENERIC) else cur_type
        conn.execute(
            "UPDATE entities SET mentions=mentions+1, last_seen=datetime('now'), "
            "type=?, event_date=COALESCE(?, event_date) WHERE id=?",
            (new_type, event_date, eid),
        )
        return eid
    cur = conn.execute(
        "INSERT INTO entities(name, display, type, event_date) VALUES(?,?,?,?)",
        (norm, name.strip()[:80], etype, event_date),
    )
    return cur.lastrowid


def ingest(entities: list, relations: list) -> None:
    """
    entities:  [{"name": str, "type": str, "date": "YYYY-MM-DD"?}]
    relations: [{"from": str, "to": str, "rel": str}]
    Вызывать из extract_and_remember — без отдельного LLM-запроса.
    """
    try:
        _ensure_tables()
        from memory.db import _conn
        conn = _conn()

        for e in (entities or []):
            if isinstance(e, dict) and e.get("name"):
                _upsert_entity(conn, e["name"], e.get("type", _GENERIC), e.get("date"))
            elif isinstance(e, str):
                _upsert_entity(conn, e)

        for r in (relations or []):
            if not isinstance(r, dict):
                continue
            a, b = r.get("from"), r.get("to")
            if not a or not b:
                continue
            sid = _upsert_entity(conn, a)
            did = _upsert_entity(conn, b)
            if not sid or not did or sid == did:
                continue
            rel = (r.get("rel") or "связан").strip()[:40]
            conn.execute(
                "INSERT INTO edges(src, dst, relation) VALUES(?,?,?) "
                "ON CONFLICT(src, dst, relation) DO UPDATE SET "
                "weight=weight+1, last_seen=datetime('now')",
                (sid, did, rel),
            )
        conn.commit()
    except Exception as e:
        log.debug(f"[graph] ingest: {e}")


# ── Чтение для промпта ───────────────────────────────────────────────

def _neighbors(conn, eid: int, limit: int = 3) -> list:
    rows = conn.execute(
        """
        SELECT e.display, x.relation, x.weight FROM (
            SELECT dst AS other, relation, weight FROM edges WHERE src=?
            UNION ALL
            SELECT src AS other, relation, weight FROM edges WHERE dst=?
        ) x JOIN entities e ON e.id = x.other
        ORDER BY x.weight DESC, e.last_seen DESC
        LIMIT ?
        """,
        (eid, eid, limit),
    ).fetchall()
    return [(r[0], r[1]) for r in rows]


def get_graph_context(query: str = "", max_entities: int = 4) -> str:
    """
    Компактный блок связей для системного промпта. Только SQL, без сети.
    Если в query есть имя известной сущности — показываем её и соседей.
    Иначе — самые свежие/частые сущности с их сильнейшей связью.
    """
    try:
        _ensure_tables()
        from memory.db import _conn
        conn = _conn()

        seeds = []
        q = _norm(query)
        if q:
            q_tokens = q.split()
            rows = conn.execute("SELECT id, display, name FROM entities").fetchall()
            for r in rows:
                if r[2] and _query_match(r[2], q_tokens):
                    seeds.append((r[0], r[1]))
        if not seeds:
            rows = conn.execute(
                "SELECT id, display FROM entities "
                "ORDER BY last_seen DESC, mentions DESC LIMIT ?",
                (max_entities,),
            ).fetchall()
            seeds = [(r[0], r[1]) for r in rows]

        seeds = seeds[:max_entities]
        if not seeds:
            return ""

        lines = ["СВЯЗИ В ПАМЯТИ:"]
        for eid, disp in seeds:
            nb = _neighbors(conn, eid)
            if nb:
                joined = ", ".join(f"{name} ({rel})" for name, rel in nb)
                lines.append(f"  {disp} ↔ {joined}")
            else:
                lines.append(f"  {disp}")
        return "\n".join(lines) if len(lines) > 1 else ""
    except Exception as e:
        log.debug(f"[graph] context: {e}")
        return ""


def related(name: str, limit: int = 8) -> list:
    """«Что связано с X» — для голоса/чата."""
    try:
        _ensure_tables()
        from memory.db import _conn
        conn = _conn()
        row = conn.execute("SELECT id FROM entities WHERE name=?", (_norm(name),)).fetchone()
        if not row:
            # фоллбэк: матч по основе (склонения: «Сакурой» → «сакура»)
            q_tokens = _norm(name).split()
            for r in conn.execute("SELECT id, name FROM entities").fetchall():
                if _query_match(r[1], q_tokens):
                    row = (r[0],)
                    break
        if not row:
            return []
        return [{"name": n, "relation": r} for n, r in _neighbors(conn, row[0], limit)]
    except Exception as e:
        log.debug(f"[graph] related: {e}")
        return []


def anniversaries_today() -> list:
    """События с датой, у которых сегодня годовщина (для утреннего briefing)."""
    try:
        _ensure_tables()
        from memory.db import _conn
        conn = _conn()
        today = date.today()
        out = []
        rows = conn.execute(
            "SELECT display, event_date FROM entities "
            "WHERE type='event' AND event_date IS NOT NULL"
        ).fetchall()
        for disp, ds in rows:
            try:
                d = date.fromisoformat(ds[:10])
            except Exception:
                continue
            if d.month == today.month and d.day == today.day and d.year < today.year:
                out.append({"name": disp, "date": ds, "years": today.year - d.year})
        return out
    except Exception as e:
        log.debug(f"[graph] anniversaries: {e}")
        return []


def forget(name: str) -> int:
    """Стереть сущность и все её рёбра. Возвращает число удалённых рёбер."""
    try:
        _ensure_tables()
        from memory.db import _conn
        conn = _conn()
        row = conn.execute("SELECT id FROM entities WHERE name=?", (_norm(name),)).fetchone()
        if not row:
            return 0
        eid = row[0]
        n = conn.execute("DELETE FROM edges WHERE src=? OR dst=?", (eid, eid)).rowcount
        conn.execute("DELETE FROM entities WHERE id=?", (eid,))
        conn.commit()
        return n
    except Exception as e:
        log.debug(f"[graph] forget: {e}")
        return 0


def stats() -> dict:
    try:
        _ensure_tables()
        from memory.db import _conn
        conn = _conn()
        return {
            "entities": conn.execute("SELECT COUNT(*) FROM entities").fetchone()[0],
            "edges":    conn.execute("SELECT COUNT(*) FROM edges").fetchone()[0],
        }
    except Exception:
        return {"entities": 0, "edges": 0}