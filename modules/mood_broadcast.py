"""
modules/mood_broadcast.py — рассылка mood-параметров подключённым устройствам.

Вызывать из ask_gemini() и ask_gemini_voice() после получения реплики.
VPS шлёт {"type": "mood_update", "params": {...}} на все активные устройства.

Интеграция в main.py:
  from modules.mood_broadcast import broadcast_mood

  # В конце ask_gemini() после auto_detect:
  asyncio.create_task(broadcast_mood(connected_devices))

  # В ask_gemini_voice() после определения emotion:
  asyncio.create_task(broadcast_mood(connected_devices))
"""

import asyncio
import json
import logging

log = logging.getLogger("sakura.mood_broadcast")


async def broadcast_mood(connected_devices: dict):
    """
    Рассылает текущие параметры орба всем подключённым устройствам.
    Не падает если устройств нет или WS закрыт.
    """
    try:
        from modules.mood_vector import get_orb_params
        params = await asyncio.to_thread(get_orb_params)
    except Exception as e:
        log.debug(f"mood_broadcast: не удалось получить параметры: {e}")
        return

    if not connected_devices:
        return

    msg = json.dumps({"type": "mood_update", "params": params})
    for device_id, ws in list(connected_devices.items()):
        try:
            await ws.send(msg)
            log.debug(f"mood_broadcast: отправлено {device_id} valence={params.get('valence',0):.2f}")
        except Exception:
            pass


async def broadcast_mood_after_reply(
    reply: str,
    user_message: str,
    emotion_label: str,
    connected_devices: dict,
):
    """
    Удобная обёртка: сначала обновляет вектор настроения по EMOTION-метке,
    затем рассылает новые параметры.

    emotion_label: "good" / "evil" / "neutral" / "playful" / ... (из LLM)
    """
    try:
        from modules.mood_vector import auto_detect_from_llm, mark_interaction
        # Создаём фейковую строку с EMOTION-меткой если она уже распарсена
        fake_reply = f"{reply}\nEMOTION:{emotion_label}"
        await asyncio.to_thread(auto_detect_from_llm, fake_reply, user_message)
        await asyncio.to_thread(mark_interaction)
    except Exception as e:
        log.debug(f"mood_broadcast: auto_detect failed: {e}")

    await broadcast_mood(connected_devices)