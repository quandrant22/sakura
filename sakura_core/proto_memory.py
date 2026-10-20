"""Протокол v2, порция 3: память Мастера (memory_*).

  memory_list {category?, offset, limit}  → memory_items {items, total, counts}
  memory_search {q, limit}                → memory_items
  memory_update {id, text}                → memory_items {items: [изменённая]}
  memory_delete {id}                      → memory_items {items: []}

Через существующие функции memory/db.py. Приватный класс: только
secure-соединение (proto_v2). Журнал изменений — без текстов: id,
категория, длина, устройство.
"""

from __future__ import annotations

import asyncio
import datetime as dt
import logging

from sakura_core import proto_v2
from sakura_core.proto_v2 import V2Error

log = logging.getLogger("sakura.memory_v2")
LIMIT_MAX = 200
TEXT_MAX = 1000


def _ts(created_at) -> float:
    try:
        return dt.datetime.fromisoformat(str(created_at)).timestamp()
    except ValueError:
        return 0.0


def _item(row: dict) -> dict:
    return {"id": f"m{row['id']}", "category": row["category"], "text": row["text"],
            "ts": _ts(row.get("created_at"))}


def _id(value) -> int:
    s = str(value or "").strip()
    s = s[1:] if s[:1] == "m" else s
    if not s.isdigit():
        raise V2Error("bad_request", "id: нужен id записи памяти")
    return int(s)


def _int(data, key, default, lo, hi):
    v = data.get(key, default)
    if isinstance(v, bool) or not isinstance(v, (int, float, str)):
        raise V2Error("bad_request", f"{key}: нужно число")
    try:
        v = int(v)
    except ValueError:
        raise V2Error("bad_request", f"{key}: нужно число") from None
    return max(lo, min(v, hi))


async def _counts() -> dict:
    from memory.db import list_memories
    return (await asyncio.to_thread(list_memories, None, 0, 1))[2]


async def _memory_list(ws, data, ctx):
    from memory.db import list_memories
    cat = data.get("category") or None
    if cat is not None and not isinstance(cat, str):
        raise V2Error("bad_request", "category: строка")
    items, total, counts = await asyncio.to_thread(
        list_memories, cat, _int(data, "offset", 0, 0, 10**6), _int(data, "limit", 50, 1, LIMIT_MAX))
    return {"type": "memory_items", "items": [_item(r) for r in items], "total": total,
            "counts": counts}


async def _memory_search(ws, data, ctx):
    from memory.db import find_memories
    q = data.get("q")
    if not isinstance(q, str) or not q.strip():
        raise V2Error("bad_request", "q: пустой запрос")
    rows = await asyncio.to_thread(find_memories, q.strip(), _int(data, "limit", 20, 1, LIMIT_MAX))
    return {"type": "memory_items", "items": [_item(r) for r in rows], "total": len(rows),
            "counts": await _counts()}


async def _memory_update(ws, data, ctx):
    from memory.db import update_memory
    row_id = _id(data.get("id"))
    text = data.get("text")
    if not isinstance(text, str) or not text.strip() or len(text) > TEXT_MAX:
        raise V2Error("bad_request", f"text: 1–{TEXT_MAX} символов")
    row = await asyncio.to_thread(update_memory, row_id, text)
    if row is None:
        raise V2Error("not_found", "запись не найдена")
    log.info(f"[memory] изменена запись m{row_id} ({row['category']}), {len(text)} симв, "
             f"устройство {data.get('device_id')}")
    return {"type": "memory_items", "items": [_item(row)], "total": 1, "counts": await _counts()}


async def _memory_delete(ws, data, ctx):
    from memory.db import delete_memory
    row_id = _id(data.get("id"))
    if not await asyncio.to_thread(delete_memory, row_id):
        raise V2Error("not_found", "запись не найдена")
    log.info(f"[memory] удалена запись m{row_id}, устройство {data.get('device_id')}")
    return {"type": "memory_items", "items": [], "total": 0, "counts": await _counts()}


for _k, _f in {"memory_list": _memory_list, "memory_search": _memory_search,
               "memory_update": _memory_update, "memory_delete": _memory_delete}.items():
    proto_v2.register(_k, _f)
