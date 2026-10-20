import json
import os
from datetime import datetime

import config
from modules.jsonio import save_json

DEVICES_FILE = "memory/devices.json"

# Описания известных id; для остальных из DEVICES имя — сам id.
_DEVICE_INFO = {
    "pc":      {"name": "Игровой ПК",      "type": "pc"},
    "laptop":  {"name": "Ноутбук",         "type": "laptop"},
    "mostech": {"name": "Рабочий ноутбук", "type": "laptop"},
    "phone":   {"name": "Телефон",         "type": "phone", "always_notify": True},
}


def build_known_devices(ids=None) -> dict:
    """KNOWN_DEVICES из DEVICES конфига (по умолчанию pc, laptop, mostech, phone)."""
    if ids is None:
        ids = getattr(config, "DEVICES", None) or list(_DEVICE_INFO)
    known = {}
    for i, did in enumerate(ids, 1):
        info = dict(_DEVICE_INFO.get(did) or {"name": did, "type": "pc"})
        info["priority"] = i
        known[did] = info
    return known


KNOWN_DEVICES = build_known_devices()


def device_name(device_id: str | None) -> str:
    """Имя для показа; неизвестный id показываем как есть."""
    return (KNOWN_DEVICES.get(device_id) or {}).get("name") or str(device_id)


def _blank() -> dict:
    return {"online": False, "last_seen": None, "active_window": None, "context": None}


def load_devices() -> dict:
    if not os.path.exists(DEVICES_FILE):
        default = {"active_device": None,
                   "devices": {k: _blank() for k in KNOWN_DEVICES}}
        save_devices(default)
        return default
    with open(DEVICES_FILE, "r", encoding="utf-8") as f:
        data = json.load(f)
    for k in KNOWN_DEVICES:          # файл мог быть создан до появления устройства
        data.setdefault("devices", {}).setdefault(k, _blank())
    return data


def save_devices(data: dict):
    save_json(DEVICES_FILE, data)


def update_device(device_id: str, active_window: str = None,
                  context: str = None, system_info: dict = None):
    if not device_id:
        return
    data = load_devices()
    # Неизвестный id (не в DEVICES) тоже заводим: показываем под своим id.
    dev = data["devices"].setdefault(device_id, _blank())
    dev["online"]    = True
    dev.pop("offline_reason", None)
    dev["last_seen"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    if active_window is not None:
        dev["active_window"] = active_window
    if context is not None:
        dev["context"] = context
    if system_info is not None:
        dev["system_info"] = system_info

    # «Активное устройство» здесь не ведётся: оно одно — presence_sync.
    save_devices(data)   # один вызов вместо двух


def get_active_device() -> str | None:
    """Делегирует presence_sync — единственному источнику активного устройства."""
    from modules.presence_sync import get_active_device as _active
    return _active()


def get_device_status() -> str:
    data   = load_devices()
    active = get_active_device()
    lines  = []

    for device_id, info in data["devices"].items():
        name      = device_name(device_id)
        is_active = " ← активное" if device_id == active else ""

        if info["online"]:
            line = f"✓ {name}{is_active}"
            if info.get("active_window"):
                line += f"\n  └ {info['active_window']}"
            if info.get("context"):
                line += f"\n  └ {info['context']}"
            sys_info = info.get("system_info", {})
            if sys_info:
                cpu = sys_info.get("cpu", "?")
                ram = sys_info.get("ram", "?")
                line += f"\n  └ CPU: {cpu}% | RAM: {ram}%"
                if "battery" in sys_info:
                    plugged = "🔌" if sys_info.get("plugged") else "🔋"
                    line += f" | {plugged} {sys_info['battery']}%"
        else:
            why = {"shutdown": "выключен", "sleep": "спит", "exit": "агент закрыт"}.get(
                info.get("offline_reason"))
            line = (f"✗ {name} — оффлайн" + (f", {why}" if why else "")
                    + f" (был: {info.get('last_seen', 'никогда')})")

        lines.append(line)

    return "\n\n".join(lines)


def get_device_context() -> str:
    data   = load_devices()
    active = get_active_device()
    if not active:
        return "Активное устройство неизвестно."

    dev    = data["devices"].get(active, {})
    name   = device_name(active)
    result = f"Мастер сейчас за {name}."
    if dev.get("active_window"):
        result += f" Активное окно: {dev['active_window']}."
    if dev.get("context"):
        result += f" Контекст: {dev['context']}."
    return result


def set_device_offline(device_id: str, reason: str | None = None):
    data = load_devices()
    if device_id in data["devices"]:
        data["devices"][device_id]["online"] = False
        if reason is not None:            # обычный обрыв не стирает причину из bye
            data["devices"][device_id]["offline_reason"] = reason
        save_devices(data)


def get_online_devices() -> list[str]:
    data = load_devices()
    return [did for did, info in data["devices"].items() if info["online"]]


def parse_device_from_text(text: str) -> str | None:
    text = text.lower()
    if any(w in text for w in ["пк", "компьютер", "системник", "десктоп"]):
        return "pc"
    if any(w in text for w in ["ноут", "ноутбук", "лаптоп"]):
        return "laptop"
    if any(w in text for w in ["телефон", "смартфон", "мобильник"]):
        return "phone"
    return None