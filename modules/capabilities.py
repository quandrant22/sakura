"""
capabilities.py — Динамический блок возможностей из живого статуса устройств.
"""

from datetime import datetime
from modules.device_manager import get_online_devices, load_devices, KNOWN_DEVICES

_STALE_SECONDS = 90


def _is_device_fresh(device_id: str) -> bool:
    data = load_devices()
    dev = data["devices"].get(device_id)
    if not dev or not dev.get("online"):
        return False
    last_seen = dev.get("last_seen")
    if not last_seen:
        return False
    try:
        ts = datetime.strptime(last_seen, "%Y-%m-%d %H:%M:%S")
        return (datetime.now() - ts).total_seconds() < _STALE_SECONDS
    except Exception:
        return False


def get_capabilities_block() -> str:
    try:
        online = [did for did in get_online_devices() if _is_device_fresh(did)]

        if online:
            device_id = online[0]
            device_name = KNOWN_DEVICES.get(device_id, {}).get("name", device_id)
            return (
                "ЧТО ТЫ УМЕЕШЬ СЕЙЧАС\n"
                f"Руки доступны: {device_name} ({device_id}) online.\n"
                "Можешь: открывать приложения и сайты, управлять музыкой (Яндекс Музыка),\n"
                "YouTube, браузером, громкостью, делать скриншоты.\n"
                "Команды выполняет отдельная система. О статусе действия говоришь только то,\n"
                "что указано в СТАТУС КОМАНДЫ — не выдумывай ни успех, ни отказ."
            )
        else:
            return (
                "ЧТО ТЫ УМЕЕШЬ СЕЙЧАС\n"
                "Руки недоступны: все устройства offline. "
                "Управлять компьютером сейчас не можешь — говоришь об этом честно, "
                "одним предложением, без извинений и без обещаний «попробую ещё раз»."
            )
    except Exception:
        return (
            "ЧТО ТЫ УМЕЕШЬ СЕЙЧАС\n"
            "Руки недоступны: все устройства offline. "
            "Управлять компьютером сейчас не можешь — говоришь об этом честно, "
            "одним предложением, без извинений и без обещаний «попробую ещё раз»."
        )
