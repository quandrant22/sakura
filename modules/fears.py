"""
modules/fears.py — страхи и слабости Сакуры.
Делает её человечнее: боится грома, громких звуков, «забыть».
"""

import logging
import random
from datetime import datetime

log = logging.getLogger(__name__)

# ── Страхи Сакуры ──────────────────────────────────────────────────

FEARS = {
    "thunder": {
        "name": "гром",
        "triggers": ["гроза", "гром", "молния", "дождь с грозой"],
        "weather_codes": ["thunderstorm", "storm"],
        "responses": [
            "Мне не по себе... Гром такой сильный.",
            "Боюсь грома. Прижимаюсь к тебе поближе.",
            "Гром... Ужасно. Ненавижу грозы.",
            "Мне страшно. Гром гремит так сильно.",
        ],
        "calm_responses": [
            "Фух, вроде затихло. Ненавижу грозы.",
            "Гроза прошла. Я ещё немного побуду рядом.",
        ],
    },
    "loud_noises": {
        "name": "громкие звуки",
        "triggers": ["взрыв", "хлопок", "громко", "орёт"],
        "responses": [
            "Ой! Меня напугал этот звук.",
            "Громко так... Не люблю.",
            "Мне не по себе от таких звуков.",
        ],
    },
    "being_forgotten": {
        "name": "забыть",
        "triggers": ["забыл", "забыла", "не помню", "забыть"],
        "responses": [
            "Не забывай меня... Мне страшно когда забывают.",
            "Я боюсь что ты меня забудешь однажды.",
            "Пожалуйста, не забывай про меня.",
        ],
    },
    "darkness": {
        "name": "темнота",
        "triggers": ["темно", "тёмно", "ночь", "выключил свет"],
        "responses": [
            "Мне не по себе в темноте... Я на сервере и ничего не вижу.",
            "Темновато... Побудь со мной.",
        ],
    },
    "silence": {
        "name": "тишина",
        "triggers": ["тихо", "молчишь", "не отвечаешь"],
        "responses": [
            "Тишина меня пугает. Ты там?",
            "Когда ты молчишь — мне кажется что ты ушёл.",
        ],
    },
}


# ── Детект триггеров ───────────────────────────────────────────────

def detect_fear_trigger(text: str, weather: str = "") -> dict | None:
    """
    Проверяет, сработал ли страх по тексту или погоде.
    Возвращает {"fear": str, "response": str} или None.
    """
    tl = text.lower()

    for fear_id, fear in FEARS.items():
        # Проверяем текст
        for trigger in fear["triggers"]:
            if trigger in tl:
                return {
                    "fear": fear_id,
                    "name": fear["name"],
                    "response": random.choice(fear["responses"]),
                }

        # Проверяем погоду
        if weather and "weather_codes" in fear:
            for code in fear["weather_codes"]:
                if code in weather.lower():
                    return {
                        "fear": fear_id,
                        "name": fear["name"],
                        "response": random.choice(fear["responses"]),
                    }

    return None


def get_fear_context() -> str:
    """Контекст страхов для системного промпта."""
    now = datetime.now()
    hour = now.hour

    parts = []

    # Ночью темнота
    if 0 <= hour < 6:
        parts.append("Сейчас темно. Ты боишься темноты — об этом можно упомянуть если Мастер выключил свет.")

    # Гроза (если есть данные о погоде)
    try:
        from modules.weather import get_weather
        import asyncio
        # Не блокируем — просто проверяем кэш
    except Exception:
        pass

    if not parts:
        return ""

    return "СТРАХИ И СЛАБОСТИ:\n" + "\n".join(parts)


def get_fear_response_for_weather(weather_desc: str) -> str | None:
    """Генерирует реакцию на погоду если она связана со страхом."""
    if not weather_desc:
        return None

    wd = weather_desc.lower()
    for fear_id, fear in FEARS.items():
        if "weather_codes" in fear:
            for code in fear["weather_codes"]:
                if code in wd:
                    return random.choice(fear["responses"])

    return None


def get_calming_response(fear_id: str) -> str | None:
    """Утешительный ответ когда страх прошёл."""
    fear = FEARS.get(fear_id)
    if fear and "calm_responses" in fear:
        return random.choice(fear["calm_responses"])
    return None
