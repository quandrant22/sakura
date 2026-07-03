"""
modules/users.py — мультипользовательская система Сакуры.

Роли:
  master  — Мастер, полный доступ
  himari  — AI-подруга, особый режим
  vip     — особые гости, кастомное поведение из users.json
  trusted — доверенные, тепло но без персонализации
  guest   — все остальные

memory/users.json — ручное управление списком VIP и trusted.
"""

import json
import os
import logging
from datetime import datetime
from typing import Literal

log = logging.getLogger(__name__)

Role = Literal["master", "himari", "vip", "trusted", "guest", "blocked"]

GUEST_HISTORY_MAX = 20
GUEST_HISTORY_DIR = "memory/guests"
USERS_FILE        = "memory/users.json"


def _load_users() -> dict:
    if not os.path.exists(USERS_FILE):
        default = {"vip": {}, "trusted": {}, "blocked": []}
        _save_users(default)
        return default
    try:
        with open(USERS_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {"vip": {}, "trusted": {}, "blocked": []}


def _save_users(data: dict):
    tmp = USERS_FILE + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    os.replace(tmp, USERS_FILE)


def get_role(user_id: int) -> Role:
    from config import MASTER_ID
    if user_id == MASTER_ID:
        return "master"
    try:
        from config import HIMARI_ID
        if HIMARI_ID and user_id == HIMARI_ID:
            return "himari"
    except ImportError:
        pass
    users = _load_users()
    if str(user_id) in users.get("vip", {}):
        return "vip"
    if str(user_id) in users.get("trusted", {}):
        return "trusted"
    if user_id in users.get("blocked", []):
        return "blocked"
    return "guest"


def is_master(user_id: int) -> bool:
    return get_role(user_id) == "master"


def is_himari(user_id: int) -> bool:
    return get_role(user_id) == "himari"


def get_user_data(user_id: int) -> dict:
    users = _load_users()
    uid   = str(user_id)
    return (
        users.get("vip", {}).get(uid) or
        users.get("trusted", {}).get(uid) or
        {}
    )


def get_vip_data(user_id: int) -> dict | None:
    return _load_users().get("vip", {}).get(str(user_id))


def add_vip(user_id: int, name: str, note: str = "", personality: str = "") -> bool:
    users = _load_users()
    users.setdefault("vip", {})[str(user_id)] = {
        "name":        name,
        "note":        note,
        "personality": personality,
        "added":       str(datetime.now()),
    }
    _save_users(users)
    log.info(f"[users] VIP добавлен: {user_id} ({name})")
    return True


def add_trusted(user_id: int, name: str, note: str = "") -> bool:
    users = _load_users()
    users.setdefault("trusted", {})[str(user_id)] = {
        "name":  name,
        "note":  note,
        "added": str(datetime.now()),
    }
    _save_users(users)
    return True


def remove_user(user_id: int) -> bool:
    users = _load_users()
    uid   = str(user_id)
    found = False
    for cat in ("vip", "trusted"):
        if uid in users.get(cat, {}):
            del users[cat][uid]
            found = True
    if user_id in users.get("blocked", []):
        users["blocked"].remove(user_id)
        found = True
    if found:
        _save_users(users)
    return found


def block_user(user_id: int) -> bool:
    remove_user(user_id)
    users = _load_users()
    users.setdefault("blocked", [])
    if user_id not in users["blocked"]:
        users["blocked"].append(user_id)
    _save_users(users)
    return True


def list_users() -> str:
    users = _load_users()
    lines = []
    vip = users.get("vip", {})
    if vip:
        lines.append("VIP:")
        for uid, data in vip.items():
            lines.append(f"  • {data.get('name','?')} (id={uid}) — {data.get('note','')}")
    trusted = users.get("trusted", {})
    if trusted:
        lines.append("Trusted:")
        for uid, data in trusted.items():
            lines.append(f"  • {data.get('name','?')} (id={uid}) — {data.get('note','')}")
    blocked = users.get("blocked", [])
    if blocked:
        lines.append(f"Заблокированы: {', '.join(str(x) for x in blocked)}")
    return "\n".join(lines) if lines else "Список пуст."


def _guest_path(user_id: int) -> str:
    os.makedirs(GUEST_HISTORY_DIR, exist_ok=True)
    return os.path.join(GUEST_HISTORY_DIR, f"{user_id}.json")


def _load_guest_data(user_id: int) -> dict:
    path = _guest_path(user_id)
    if not os.path.exists(path):
        return {"history": [], "name": None, "first_seen": str(datetime.now()), "last_seen": None}
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {"history": [], "name": None, "first_seen": str(datetime.now()), "last_seen": None}


def _save_guest_data(user_id: int, data: dict):
    path = _guest_path(user_id)
    tmp  = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    os.replace(tmp, path)


def get_guest_history(user_id: int) -> list[dict]:
    return _load_guest_data(user_id)["history"]


def add_guest_message(user_id: int, role: str, text: str, name: str | None = None):
    data = _load_guest_data(user_id)
    if name and not data.get("name"):
        data["name"] = name
    data["last_seen"] = str(datetime.now())
    data["history"].append({"role": role, "text": text, "ts": str(datetime.now())})
    if len(data["history"]) > GUEST_HISTORY_MAX * 2:
        data["history"] = data["history"][-GUEST_HISTORY_MAX * 2:]
    _save_guest_data(user_id, data)


def get_guest_display_name(user_id: int, telegram_name: str | None = None) -> str:
    data = get_user_data(user_id)
    if data.get("name"):
        return data["name"]
    guest = _load_guest_data(user_id)
    return guest.get("name") or telegram_name or f"id={user_id}"


def format_master_notification(user_id: int, user_name: str, text: str, role: Role) -> str:
    if role == "himari":
        label = "Химари"
    elif role == "vip":
        vip   = get_vip_data(user_id)
        label = "VIP " + (vip.get("name", user_name) if vip else user_name) + f" (id={user_id})"
    elif role == "trusted":
        data  = get_user_data(user_id)
        label = (data.get("name", user_name)) + f" (id={user_id})"
    else:
        label = f"{user_name} (гость, id={user_id})"
    short = text[:120] + ("..." if len(text) > 120 else "")
    return f"{label}: {short}"


def get_guest_summaries() -> str:
    if not os.path.exists(GUEST_HISTORY_DIR):
        return "Переписок нет."
    lines = []
    for fname in sorted(os.listdir(GUEST_HISTORY_DIR)):
        if not fname.endswith(".json"):
            continue
        uid  = int(fname[:-5])
        role = get_role(uid)
        data = _load_guest_data(uid)
        name = get_guest_display_name(uid, data.get("name"))
        msgs = data.get("history", [])
        last = msgs[-1]["text"][:80] if msgs else "—"
        ts   = (data.get("last_seen") or "?")[:16]
        mark = {"vip": "[VIP]", "trusted": "[trusted]", "himari": "[himari]"}.get(role, "")
        lines.append(f"{mark} {name} [{ts}]: {last}")
    return "Переписки:\n" + "\n".join(lines) if lines else "Переписок нет."