import json
import os
from datetime import datetime

DEVICES_FILE = "memory/devices.json"

KNOWN_DEVICES = {
    "pc":     {"name": "Игровой ПК",  "type": "pc",     "priority": 1},
    "laptop": {"name": "Ноутбук",     "type": "laptop", "priority": 2},
    "phone":  {"name": "Телефон",     "type": "phone",  "priority": 3, "always_notify": True},
}


def load_devices() -> dict:
    if not os.path.exists(DEVICES_FILE):
        default = {
            "active_device": None,
            "devices": {
                k: {"online": False, "last_seen": None, "active_window": None, "context": None}
                for k in KNOWN_DEVICES
            }
        }
        save_devices(default)
        return default
    with open(DEVICES_FILE, "r", encoding="utf-8") as f:
        return json.load(f)


def save_devices(data: dict):
    with open(DEVICES_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def update_device(device_id: str, active_window: str = None,
                  context: str = None, system_info: dict = None):
    data = load_devices()
    if device_id not in data["devices"]:
        return

    dev = data["devices"][device_id]
    dev["online"]    = True
    dev["last_seen"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    if active_window is not None:
        dev["active_window"] = active_window
    if context is not None:
        dev["context"] = context
    if system_info is not None:
        dev["system_info"] = system_info

    if device_id != "phone":
        data["active_device"] = device_id

    save_devices(data)   # один вызов вместо двух


def get_active_device() -> str | None:
    return load_devices().get("active_device")


def get_device_status() -> str:
    data   = load_devices()
    active = data.get("active_device")
    lines  = []

    for device_id, info in data["devices"].items():
        name      = KNOWN_DEVICES[device_id]["name"]
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
            line = f"✗ {name} — оффлайн (был: {info.get('last_seen', 'никогда')})"

        lines.append(line)

    return "\n\n".join(lines)


def get_device_context() -> str:
    data   = load_devices()
    active = data.get("active_device")
    if not active:
        return "Активное устройство неизвестно."

    dev    = data["devices"].get(active, {})
    name   = KNOWN_DEVICES[active]["name"]
    result = f"Мастер сейчас за {name}."
    if dev.get("active_window"):
        result += f" Активное окно: {dev['active_window']}."
    if dev.get("context"):
        result += f" Контекст: {dev['context']}."
    return result


def set_device_offline(device_id: str):
    data = load_devices()
    if device_id in data["devices"]:
        data["devices"][device_id]["online"] = False
        if data.get("active_device") == device_id:
            data["active_device"] = None
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