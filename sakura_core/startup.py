"""Startup helpers — extracted from main.py."""

import asyncio
import logging

log = logging.getLogger("sakura.startup")


def guarded_add(db_add_to_category, cat: str, item: str):
    """Guarded memory write: skips intimacy windows and intimate content."""
    from modules.intimacy_mode import consume_check, is_intimate_content
    if consume_check():
        log.info("[memory] reflection write skipped: intimacy in window")
        return False
    if is_intimate_content(item):
        log.info(f"[memory] интимный фильтр (reflection): {item[:40]}")
        return False
    return db_add_to_category(cat, item)


async def init_japanese_vocab():
    await asyncio.sleep(5)
    try:
        from modules.learn_japanese import init_vocabulary
        await asyncio.to_thread(init_vocabulary)
    except Exception as e:
        log.error(f"[japanese] Ошибка инициализации: {e}")


async def init_weather(MASTER_LAT, MASTER_LON):
    await asyncio.sleep(3)
    from modules.weather import set_location, get_weather, apply_weather_to_mood
    if MASTER_LAT and MASTER_LON:
        set_location(MASTER_LAT, MASTER_LON)
    weather = await get_weather()
    if weather:
        await asyncio.to_thread(apply_weather_to_mood, weather)
        log.info(f"[weather] {weather['temp']}°C, {weather['desc']}")
