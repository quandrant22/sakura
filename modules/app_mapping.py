"""Маппинг приложений: find_in_mapping, resolve_app.

Перенесено из main.py (stage 7D).
"""

from __future__ import annotations

import json
import logging
import os
import time

from modules.state import connected_devices

log = logging.getLogger(__name__)


def mapping_names(device_id: str) -> tuple[str, ...]:
    """Разговорные имена приложений из маппинга (keys, без значений).

    Используется фильтром param.resolve: installed_apps в реестре:
    агентский список имён латинские («Discord», «Steam»), а говорит
    Мастер «дискорд»/«стим» — разговорные варианты живут здесь.
    """
    try:
        path = f"memory/apps_mapping_{device_id}.json"
        if not os.path.exists(path):
            return ()
        with open(path, "r", encoding="utf-8") as f:
            mapping = json.load(f)
        return tuple(mapping.keys())
    except Exception as e:
        log.debug(f"mapping_names({device_id}): {type(e).__name__}: {e}")
        return ()


def find_in_mapping(query: str, device_id: str) -> str | None:
    try:
        path = f"memory/apps_mapping_{device_id}.json"
        if not os.path.exists(path):
            return None
        with open(path, "r", encoding="utf-8") as f:
            mapping = json.load(f)
        q = query.lower().strip()
        if not q:
            return None

        if q in mapping:
            return mapping[q]
        for name, val in mapping.items():
            if q in name or name in q:
                return val

        import difflib
        names = list(mapping.keys())
        best = difflib.get_close_matches(q, names, n=1, cutoff=0.7)
        if best:
            return mapping[best[0]]

        for word in q.split():
            if len(word) < 4:
                continue
            best = difflib.get_close_matches(word, names, n=1, cutoff=0.78)
            if best:
                return mapping[best[0]]
    except Exception as e:
        log.error(f"Mapping search error: {e}")
    return None


def resolve_app(query: str, prefer_device: str | None = None):
    order = ([prefer_device] if prefer_device else []) + \
            [d for d in connected_devices if d != prefer_device]
    for dev in order:
        target = find_in_mapping(query, dev)
        if target:
            return dev, target
    return None, None


def find_vip_by_name(text: str):
    import difflib
    try:
        with open("memory/users.json", encoding="utf-8") as f:
            vips = json.load(f).get("vip", {})
    except Exception:
        return None
    names = {info.get("name", "").lower(): cid for cid, info in vips.items() if info.get("name")}
    if not names:
        return None
    for w in text.lower().replace(",", " ").split():
        if len(w) < 3:
            continue
        m = difflib.get_close_matches(w, list(names.keys()), n=1, cutoff=0.62)
        if m:
            return names[m[0]], m[0]
    return None
