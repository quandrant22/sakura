"""
modules/weather.py — погода → настроение Сакуры (бэклог №9).

Получает погоду по IP сервера (VPS в Финляндии) или по координатам Мастера.
Влияет на mood_vector с малым blend — подтекстом, не явно.

Кэш: 30 минут (погода меняется медленно).
"""

import asyncio
import json
import logging
import time
import urllib.request
from typing import Optional

log = logging.getLogger("sakura.weather")

_cache: dict = {}
_CACHE_TTL   = 1800  # 30 минут

# Маппинг WMO weather codes → настроение
_WEATHER_MOOD = {
    # Ясно
    "clear":     {"valence":  0.15, "arousal":  0.05, "desc": "ясно"},
    # Облачно
    "cloudy":    {"valence": -0.05, "arousal": -0.05, "desc": "облачно"},
    # Дождь
    "rain":      {"valence": -0.10, "arousal": -0.10, "desc": "дождь"},
    # Гроза
    "storm":     {"valence": -0.15, "arousal":  0.15, "desc": "гроза"},
    # Снег
    "snow":      {"valence":  0.05, "arousal": -0.08, "desc": "снег"},
    # Туман
    "fog":       {"valence": -0.08, "arousal": -0.12, "desc": "туман"},
}

# WMO codes → категории
def _wmo_to_category(code: int) -> str:
    if code == 0:                       return "clear"
    if code in (1, 2, 3):              return "cloudy"
    if code in (45, 48):               return "fog"
    if code in range(51, 68):          return "rain"
    if code in range(71, 78):          return "snow"
    if code in range(80, 87):          return "rain"
    if code in range(95, 100):         return "storm"
    return "cloudy"


# Координаты по умолчанию — берутся из конфига или фолбэк Москва
_DEFAULT_LAT = None
_DEFAULT_LON = None

def set_location(lat: float, lon: float):
    """Устанавливает координаты Мастера (вызывать при старте из конфига)."""
    global _DEFAULT_LAT, _DEFAULT_LON
    _DEFAULT_LAT, _DEFAULT_LON = lat, lon
    log.info(f"[weather] Координаты установлены: {lat}, {lon}")


async def get_weather(lat: float = None, lon: float = None) -> Optional[dict]:
    """
    Получает текущую погоду через Open-Meteo (бесплатно, без ключа).
    Порядок приоритета координат:
      1. Переданные явно (lat/lon параметры)
      2. Установленные через set_location() из конфига
      3. По IP (последний резерв — может дать финские координаты!)
    """
    # Используем переданные или дефолтные
    if lat is None:
        lat = _DEFAULT_LAT
    if lon is None:
        lon = _DEFAULT_LON

    cache_key = f"{lat}:{lon}"
    entry = _cache.get(cache_key)
    if entry and time.monotonic() - entry["fetched_at"] < _CACHE_TTL:
        return entry

    try:
        # Только если координаты вообще не заданы — определяем по IP
        if lat is None or lon is None:
            lat, lon = await _get_coords_by_ip()
        if lat is None:
            return None

        url = (
            f"https://api.open-meteo.com/v1/forecast"
            f"?latitude={lat}&longitude={lon}"
            f"&current=temperature_2m,weathercode,windspeed_10m,precipitation"
            f"&daily=temperature_2m_max,temperature_2m_min,weathercode,precipitation_sum,precipitation_probability_max"
            f"&forecast_days=3"
            f"&timezone=auto"
        )
        data = await asyncio.to_thread(_fetch_json, url)
        if not data:
            return None

        current  = data.get("current", {})
        wmo_code = current.get("weathercode", 0)
        temp     = current.get("temperature_2m", 0)
        wind     = current.get("windspeed_10m", 0)
        precip   = current.get("precipitation", 0)
        category = _wmo_to_category(wmo_code)
        mood     = _WEATHER_MOOD.get(category, _WEATHER_MOOD["cloudy"])

        result = {
            "temp":       round(temp, 1),
            "category":   category,
            "desc":       mood["desc"],
            "wind":       round(wind, 1),
            "precip":     precip,
            "valence":    mood["valence"],
            "arousal":    mood["arousal"],
            "lat":        lat,
            "lon":        lon,
            "fetched_at": time.monotonic(),
        }

        # Дневной прогноз (на завтра и послезавтра)
        daily = data.get("daily", {})
        if daily:
            dates = daily.get("time", [])
            t_max = daily.get("temperature_2m_max", [])
            t_min = daily.get("temperature_2m_min", [])
            codes = daily.get("weathercode", [])
            pops  = daily.get("precipitation_probability_max", [])
            result["daily"] = []
            for i, d in enumerate(dates[:3]):
                result["daily"].append({
                    "date":     d,
                    "t_max":    round(t_max[i], 1) if i < len(t_max) else None,
                    "t_min":    round(t_min[i], 1) if i < len(t_min) else None,
                    "weather":  _wmo_to_category(codes[i]) if i < len(codes) else "cloudy",
                    "pop":      pops[i] if i < len(pops) else 0,
                })
        _cache[cache_key] = result
        log.info(f"[weather] {result['temp']}°C, {result['desc']} ({lat}, {lon})")
        return result

    except Exception as e:
        log.error(f"[weather] Ошибка: {e}")
        return None


async def _get_coords_by_ip() -> tuple[Optional[float], Optional[float]]:
    """Определяет координаты по IP через ip-api.com."""
    try:
        data = await asyncio.to_thread(_fetch_json, "http://ip-api.com/json/?fields=lat,lon,city")
        if data and "lat" in data:
            log.info(f"[weather] Город по IP: {data.get('city')}")
            return data["lat"], data["lon"]
    except Exception:
        pass
    return None, None


def _fetch_json(url: str) -> Optional[dict]:
    with urllib.request.urlopen(url, timeout=5) as r:
        return json.loads(r.read().decode())


def apply_weather_to_mood(weather: dict):
    """Применяет погоду к mood_vector с малым blend — подтекстом."""
    if not weather:
        return
    try:
        from modules.mood_vector import set_target, get_current
        current  = get_current()
        new_v    = current["valence"] + weather["valence"] * 0.3  # мягко
        new_a    = current["arousal"] + weather["arousal"] * 0.3
        set_target(new_v, new_a, blend=0.15)
        log.debug(f"[weather] Влияние на mood: Δv={weather['valence']:.2f} Δa={weather['arousal']:.2f}")
    except Exception as e:
        log.debug(f"[weather] apply_to_mood: {e}")


def get_weather_context(weather: dict) -> str:
    """Строка для системного промпта — погода как подтекст."""
    if not weather:
        return ""
    desc = weather["desc"]
    temp = weather["temp"]
    # Только если погода интересная — не говорим про ясно каждый раз
    if weather["category"] == "clear":
        return ""
    return (
        f"ПОГОДА ЗА ОКНОМ: {desc}, {temp}°C. "
        "Это может тонко влиять на твоё настроение — не говори об этом прямо, "
        "просто будь чуть более [задумчивой если дождь / спокойной если туман / "
        "оживлённой если гроза]."
    )


# ── Город и день из фразы («какая погода завтра в Питере») ────────────

import re as _re
from urllib.parse import quote as _quote

DAY_WORDS = {"сегодня": 0, "сейчас": 0, "завтра": 1, "послезавтра": 2}
DAY_LABELS = {0: "Сегодня", 1: "Завтра", 2: "Послезавтра"}

# Разговорные имена → название для геокодера.
CITY_ALIASES = {
    "питер": "Санкт-Петербург", "питере": "Санкт-Петербург", "спб": "Санкт-Петербург",
    "петербург": "Санкт-Петербург", "петербурге": "Санкт-Петербург",
    "санкт-петербург": "Санкт-Петербург", "санкт-петербурге": "Санкт-Петербург",
    "мск": "Москва", "москва": "Москва", "москве": "Москва",
    "екб": "Екатеринбург", "екатеринбурге": "Екатеринбург",
    "нижнем": "Нижний Новгород", "нижнем новгороде": "Нижний Новгород",
    "ростове": "Ростов-на-Дону", "ростове-на-дону": "Ростов-на-Дону",
}

# «в …», после которого идёт не город, а время или обстоятельство.
_NOT_CITY = frozenset("""
понедельник вторник среду четверг пятницу субботу воскресенье выходные будни
обед полдень полночь ночь ночи утро вечер течение ближайшие ближайшее эти это
последнее целом общем принципе городе городу мире стране регионе области
доме квартире комнате офисе
""".split())

_CITY_RE = _re.compile(
    r"(?<!\w)(?:в|во)\s+([a-zа-яё][a-zа-яё\-]+(?:\s+(?:новгороде|челнах|тагиле|осколе))?)",
    _re.IGNORECASE)

_geo_cache: dict[str, Optional[tuple[float, float, str]]] = {}


def parse_weather_query(text: str, param: str = "") -> tuple[Optional[str], int]:
    """Фраза (и параметр от LLM-разбора) → (город как назван | None, день 0..2)."""
    low = f"{text or ''} {param or ''}".lower()
    day = 0
    for word, offset in sorted(DAY_WORDS.items(), key=lambda kv: -len(kv[0])):
        if _re.search(rf"(?<!\w){word}(?!\w)", low):
            day = offset
            break
    city = None
    for m in _CITY_RE.finditer((text or "").lower()):
        cand = m.group(1).strip()
        if cand.split()[0] in _NOT_CITY or cand in DAY_WORDS:
            continue
        city = cand
        break
    if city is None and param:
        # Параметр LLM-разбора: «Санкт-Петербург завтра» → город без слов дня.
        rest = " ".join(w for w in param.replace(";", " ").replace(",", " ").split()
                        if w.lower() not in DAY_WORDS and w.lower() not in ("в", "во"))
        city = rest.strip().lower() or None
    return city, day


def _city_candidates(city: str) -> list[str]:
    """Название в том виде, как произнесли (часто предложный падеж),
    → варианты именительного для геокодера, самые вероятные первыми."""
    c = city.strip().lower()
    if c in CITY_ALIASES:
        return [CITY_ALIASES[c]]
    out = []
    if c.endswith("е"):
        out += [c[:-1], c[:-1] + "а", c[:-1] + "о"]       # Минске, Москве, Орле
    elif c.endswith("и"):
        out += [c[:-1] + "ь", c[:-1] + "а", c]            # Казани, Сочи
    elif c.endswith("ах"):
        out += [c[:-2] + "ы", c]                          # Чебоксарах
    out.append(c)
    seen, uniq = set(), []
    for v in out:
        if v and v not in seen:
            seen.add(v)
            uniq.append(v)
    return uniq


async def geocode(city: str) -> Optional[tuple[float, float, str]]:
    """Город → (широта, долгота, название). None — не найден или сервис молчит."""
    key = (city or "").strip().lower()
    if not key:
        return None
    if key in _geo_cache:
        return _geo_cache[key]
    for name in _city_candidates(key):
        url = ("https://geocoding-api.open-meteo.com/v1/search"
               f"?name={_quote(name)}&count=1&language=ru&format=json")
        try:
            data = await asyncio.to_thread(_fetch_json, url)
        except Exception as e:
            log.info(f"[weather] геокодер: {type(e).__name__} на «{name}»")
            return None                      # сервис недоступен — не кэшируем
        results = (data or {}).get("results") or []
        if results:
            r = results[0]
            found = (float(r["latitude"]), float(r["longitude"]), r.get("name") or name)
            _geo_cache[key] = found
            log.info(f"[weather] город «{city}» → {found[2]} ({found[0]}, {found[1]})")
            return found
    _geo_cache[key] = None
    return None


def describe(category: str) -> str:
    return _WEATHER_MOOD.get(category, _WEATHER_MOOD["cloudy"])["desc"]
