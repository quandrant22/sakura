"""TG command handler implementations — extracted from adapters/telegram.py.

Thin @dp wrappers stay in telegram.py; logic lives here.
"""

from __future__ import annotations

import os
import subprocess
import time
import logging
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from aiogram.types import Message

log = logging.getLogger("sakura.cmd")


def _is_master(message: "Message") -> bool:
    from modules.users import is_master
    return is_master(message.from_user.id)


async def cmd_help_impl(message: "Message"):
    from modules import device_commands
    await message.answer(device_commands.help_text())


async def cmd_health_impl(message: "Message"):
    import psutil
    cpu  = psutil.cpu_percent(interval=0.5)
    ram  = psutil.virtual_memory()
    disk = psutil.disk_usage("/")
    load = os.getloadavg()
    up   = int(time.monotonic() - _get_start_time())
    await message.answer(
        f"Сервер:\n"
        f"CPU: {cpu:.0f}%  |  load: {load[0]:.2f} {load[1]:.2f} {load[2]:.2f}\n"
        f"RAM: {ram.percent:.0f}% ({ram.used >> 20} / {ram.total >> 20} МБ)\n"
        f"Диск: {disk.percent:.0f}% (свободно {disk.free >> 30} ГБ)\n"
        f"Аптайм: {up // 3600}ч {(up % 3600) // 60}м"
    )


async def cmd_restart_impl(message: "Message"):
    await message.answer("Перезапускаюсь, Мастер. Вернусь через пару секунд.")
    subprocess.Popen(["systemctl", "restart", "sakura.service"])


async def cmd_start_impl(message: "Message", ask_gemini):
    reply = await ask_gemini("Мастер только что запустил бота. Поприветствуй коротко.")
    await message.answer(reply)


async def cmd_status_impl(message: "Message"):
    from modules.device_manager import get_device_status
    await message.answer(get_device_status())


async def cmd_memory_impl(message: "Message"):
    from memory.db import get_memory_context as db_get_memory_context
    ctx = db_get_memory_context()
    await message.answer(ctx if ctx else "Память пока пуста.")


async def cmd_tasks_impl(message: "Message"):
    from modules.tasks import get_tasks_context
    ctx = get_tasks_context()
    await message.answer(ctx if ctx else "Задач пока нет.")


async def cmd_clear_impl(message: "Message", ask_gemini):
    from memory.memory import clear_history, clear_session_summary
    clear_history()
    clear_session_summary()
    reply = await ask_gemini("Мастер очистил историю диалога. Отреагируй коротко.")
    await message.answer(reply)


async def cmd_clean_slate_impl(message: "Message", clean_slate_fn):
    await clean_slate_fn()
    await message.answer("Протокол выполнен. Я тебя не помню.")


async def cmd_guests_impl(message: "Message"):
    from modules.users import get_guest_summaries
    await message.answer(get_guest_summaries())


async def cmd_vip_impl(message: "Message"):
    from modules.users import add_vip
    parts = (message.text or "").split(maxsplit=1)
    if len(parts) < 2:
        await message.answer("Использование: /vip @username или /vip id")
        return
    arg = parts[1].strip()
    uid = None
    if arg.isdigit():
        uid = int(arg)
    else:
        await message.answer("Укажи числовой Telegram ID: поиск по @username недоступен.")
        return
    if uid:
        add_vip(uid, name=arg)
        await message.answer(f"Пользователь {uid} добавлен в VIP.")
    else:
        await message.answer("Не нашла такого пользователя.")


async def cmd_trusted_impl(message: "Message"):
    from modules.users import add_trusted
    parts = (message.text or "").split(maxsplit=1)
    if len(parts) < 2:
        await message.answer("Использование: /trusted @username или /trusted id")
        return
    arg = parts[1].strip()
    uid = None
    if arg.isdigit():
        uid = int(arg)
    else:
        await message.answer("Укажи числовой Telegram ID: поиск по @username недоступен.")
        return
    if uid:
        add_trusted(uid, name=arg)
        await message.answer(f"Пользователь {uid} добавлен в доверенные.")
    else:
        await message.answer("Не нашла такого пользователя.")


async def cmd_users_impl(message: "Message"):
    from modules.users import list_users
    await message.answer(list_users())


async def cmd_unvip_impl(message: "Message"):
    from modules.users import remove_user
    parts = (message.text or "").split(maxsplit=1)
    if len(parts) < 2:
        await message.answer("Использование: /unvip id")
        return
    arg = parts[1].strip()
    if arg.isdigit():
        remove_user(int(arg))
        await message.answer(f"Пользователь {arg} удалён.")
    else:
        await message.answer("Укажи numeric ID.")


async def cmd_block_impl(message: "Message"):
    from modules.users import block_user
    parts = (message.text or "").split(maxsplit=1)
    if len(parts) < 2:
        await message.answer("Использование: /block id")
        return
    arg = parts[1].strip()
    if arg.isdigit():
        block_user(int(arg))
        await message.answer(f"Пользователь {arg} заблокирован.")
    else:
        await message.answer("Укажи numeric ID.")


_start_time = None

def _get_start_time() -> float:
    global _start_time
    if _start_time is None:
        # _START живёт в adapters.telegram (переехал туда при 7D-2).
        # Импорт ленивый: telegram → commands, обратный на уровне модуля дал бы цикл.
        import adapters.telegram as _tg
        _start_time = _tg._START
    return _start_time


async def device_control_impl(message: "Message", *, connected_devices,
                               stream_tts_to_device, get_current_emotion):
    import asyncio, json
    text = (message.text or "").removeprefix("/устройство").strip()
    if not text:
        await message.answer("Что сделать с устройством? (выкл, перезагрузка, спящий режим)")
        return
    from modules.presence_sync import get_active_device
    dev_id = get_active_device() or "laptop"
    ws = connected_devices.get(dev_id)
    if not ws:
        await message.answer("Устройство оффлайн.")
        return
    cmd_map = {
        "выкл": "system.shutdown",
        "выключить": "system.shutdown",
        "перезагрузка": "system.restart",
        "перезагрузить": "system.restart",
        "спящий": "system.sleep",
        "спящий режим": "system.sleep",
        "спать": "system.sleep",
    }
    action = None
    for key, val in cmd_map.items():
        if key in text.lower():
            action = val
            break
    if not action:
        await message.answer("Не поняла команду. Доступно: выкл, перезагрузка, спящий режим.")
        return
    await ws.send(json.dumps({"type": "command", "action": action}))
    await message.answer(f"Команда {action} отправлена на {dev_id}.")
    await asyncio.sleep(0.3)
    if action == "system.shutdown":
        asyncio.create_task(stream_tts_to_device(
            "Выключаюсь, Мастер. Спокойной ночи.", ws, dev_id,
            literal=True, emotion=get_current_emotion()))
