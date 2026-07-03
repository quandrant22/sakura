"""
modules/audio_control.py — управление аудио-устройством через Telegram/голос.

Команды:
  /устройства          — показать список устройств вывода
  /устройство 2        — переключить на устройство #2
  /устройство default  — вернуть на дефолт Windows

Голосом (через ws_handler):
  «Сакура, переключи звук на наушники» → команда switch_audio:<имя>
  «Сакура, список звуковых устройств»  → команда list_audio_devices

Интеграция в main.py:
  from modules.audio_control import handle_audio_command, format_devices_list

  # В handle_message или ws_handler:
  if text.startswith("/устройств"):
      reply = await handle_audio_command(text, connected_devices)
      await message.reply(reply)
"""

import logging

log = logging.getLogger("sakura.audio_control")


def format_devices_list(connected_devices: dict) -> str:
    """
    Запрашивает список устройств с подключённого агента.
    Агент должен прислать список через ws-сообщение audio_devices.
    Пока — возвращает инструкцию запустить list_devices.py.
    """
    if not connected_devices:
        return "Нет подключённых устройств."

    # Шлём команду агенту — он ответит сообщением audio_devices
    return (
        "Список устройств запрошен. Агент пришлёт через секунду.\n\n"
        "Или запусти вручную:\n"
        "```\npython list_devices.py\n```"
    )


async def send_switch_command(
    device: str | int,
    connected_devices: dict,
    target_device_id: str = None,
) -> str:
    """
    Отправляет команду смены аудио-устройства на агент.
    device: int (номер) или str ("default", "Realtek")
    """
    import json

    if not connected_devices:
        return "Нет подключённых устройств."

    # Определяем целевое устройство агента
    target = target_device_id or next(iter(connected_devices), None)
    if not target:
        return "Агент не подключён."

    ws = connected_devices.get(target)
    if not ws:
        return f"Устройство {target} не в сети."

    try:
        await ws.send(json.dumps({
            "type":    "command",
            "action":  f"switch_audio:{device}",
        }))
        return f"Переключаю звук на: {device}"
    except Exception as e:
        log.error(f"[audio_control] {e}")
        return "Не удалось переключить устройство."


async def handle_audio_command(
    text: str,
    connected_devices: dict,
) -> str:
    """
    Обрабатывает текстовую команду управления звуком.
    Вызывать из handle_message в main.py.
    """
    tl = text.strip().lower()

    # /устройства — список
    if "устройств" in tl and not any(c.isdigit() for c in tl) and "default" not in tl:
        return format_devices_list(connected_devices)

    # /устройство 2 или /устройство default
    parts = text.strip().split()
    if len(parts) >= 2:
        arg = parts[-1].strip()
        if arg.isdigit():
            return await send_switch_command(int(arg), connected_devices)
        if arg.lower() in ("default", "дефолт", "по умолчанию"):
            return await send_switch_command("default", connected_devices)
        # Поиск по имени
        return await send_switch_command(arg, connected_devices)

    return (
        "Команды:\n"
        "/устройства — список доступных\n"
        "/устройство 2 — переключить на #2\n"
        "/устройство default — вернуть на дефолт"
    )


# ── Обработчик на стороне агента (добавить в agent._run_command) ─────

def handle_switch_audio_command(action: str, player) -> dict:
    """
    Обрабатывает action='switch_audio:2' или 'switch_audio:Realtek'.
    Вызывать из core/agent.py в _run_command().
    """
    parts = action.split(":", 1)
    if len(parts) < 2:
        return {"result": "switch_audio: нет аргумента"}

    arg = parts[1].strip()

    if arg.isdigit():
        device_id = int(arg)
        player.switch_device(device_id)
        return {"result": f"Звук переключён на #{device_id}"}

    if arg.lower() in ("default", "дефолт"):
        player.switch_device(None)
        return {"result": "Звук переключён на дефолт"}

    # Поиск по имени
    try:
        import sounddevice as sd
        devs = sd.query_devices()
        arg_lower = arg.lower()
        for i, dev in enumerate(devs):
            if arg_lower in dev["name"].lower() and dev["max_output_channels"] > 0:
                player.switch_device(i)
                return {"result": f"Звук переключён на {dev['name']}"}
        return {"result": f"Устройство '{arg}' не найдено"}
    except Exception as e:
        return {"result": f"Ошибка: {e}"}


# ── Патч для core/agent.py ────────────────────────────────────────────
#
# В async def _run_command(self, action: str):
#   Добавить в начало:
#
#   if action.startswith("switch_audio:"):
#       from modules.audio_control import handle_switch_audio_command
#       out = handle_switch_audio_command(action, self.player)
#       log.info(out.get("result", ""))
#       return
#
# В ws_handler main.py, в блок handle_message добавить:
#
#   elif text.startswith("/устройств"):
#       from modules.audio_control import handle_audio_command
#       reply = await handle_audio_command(text, connected_devices)
#       await message.reply(reply)
#       return
