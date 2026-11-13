"""modules/game_sessions.py — память игровых сессий и реакции Сакуры на игровые события с ПК.

ПК (desktop/core/game_director.py) шлёт:
  game_session_start {game, game_key, level, reason}
  game_event         {game, game_key, level, event, event_text, detail, stats, minutes}
  game_session_end   {game, game_key, level, minutes, stats, highlights, speak}
Уровень присутствия (silent / reactions / commentator / coop) выбирает Мастер для каждой игры;
ПК уже отфильтровал события по уровню, сервер дополнительно ограничивает частоту (MIN_GAP_S).

Память: data/game_sessions.json — по каждой игре последние сессии (дата, минуты, счёт, лучшие моменты),
чтобы при следующем запуске Сакура могла сказать «в прошлый раз ты застрял на боссе».
Промпты — короткие реплики в характере; построение промптов — чистые функции (тесты).
"""
from __future__ import annotations

import json
import logging
import os
import threading
import time
from typing import Optional

log = logging.getLogger("sakura.game_sessions")

DATA_FILE = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data", "game_sessions.json")
KEEP_PER_GAME = 10
MIN_GAP_S = {"silent": float("inf"), "reactions": 30.0, "commentator": 12.0, "coop": 6.0}
URGENT = {"victory", "defeat", "achievement", "tilt", "ace"}
REMIND_AFTER_S = 3 * 3600   # «в прошлый раз…» — только если с прошлой сессии прошло больше 3 часов
LEVELS = ("silent", "reactions", "commentator", "coop")

_lock = threading.Lock()
_last_spoken: dict[str, float] = {}
_current_level: dict[str, str] = {}  # device_id → уровень текущей игры (для window_watcher)


def _load(path: str = DATA_FILE) -> dict:
    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def _save(data: dict, path: str = DATA_FILE) -> None:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=1)
    os.replace(tmp, path)


def record_session(key: str, game: str, minutes: int, stats: dict, highlights: list,
                   now: float | None = None, path: str = DATA_FILE) -> dict:
    entry = {"ts": int(now or time.time()), "game": game, "minutes": int(minutes or 0),
             "stats": {k: int(v) for k, v in (stats or {}).items() if isinstance(v, (int, float))},
             "highlights": [str(h)[:120] for h in (highlights or [])][-8:]}
    with _lock:
        data = _load(path)
        items = data.get(key) or []
        items.append(entry)
        data[key] = items[-KEEP_PER_GAME:]
        _save(data, path)
    return entry


def last_session(key: str, path: str = DATA_FILE) -> Optional[dict]:
    items = _load(path).get(key) or []
    return items[-1] if items else None


def set_level(device: str, level: str) -> None:
    _current_level[device or "laptop"] = level if level in LEVELS else "reactions"


def clear_level(device: str) -> None:
    _current_level.pop(device or "laptop", None)


def presence_level(device: str = "laptop") -> Optional[str]:
    """Уровень присутствия текущей игры на устройстве (None — игры нет)."""
    return _current_level.get(device or "laptop")


def may_speak(device: str, level: str, event: str, now: float | None = None) -> bool:
    if level == "silent":
        return False
    now = now or time.monotonic()
    gap = 5.0 if event in URGENT else MIN_GAP_S.get(level, 30.0)
    last = _last_spoken.get(device, -1e9)
    if now - last < gap:
        return False
    _last_spoken[device] = now
    return True


def _score(stats: dict) -> str:
    k, d = int(stats.get("kills", 0)), int(stats.get("deaths", 0))
    w, l_ = int(stats.get("wins", 0)), int(stats.get("losses", 0))
    parts = []
    if k or d:
        parts.append(f"убийств {k}, смертей {d}")
    if w or l_:
        parts.append(f"побед {w}, поражений {l_}")
    return "; ".join(parts)


STYLE = {
    "reactions": "одной короткой живой фразой (до 10 слов)",
    "commentator": "одной короткой фразой комментатора (до 12 слов), можно с лёгкой иронией",
    "coop": "как напарница рядом — одной короткой фразой (до 12 слов), по-дружески",
}


def event_prompt(game: str, level: str, event_text: str, detail: str, minutes: int, stats: dict) -> str:
    style = STYLE.get(level, STYLE["reactions"])
    extra = f" ({detail})" if detail else ""
    score = _score(stats)
    base = (f"Мастер играет в «{game}» уже {minutes} мин." + (f" Счёт сессии: {score}." if score else "")
            + f" Только что: {event_text}{extra}. Отреагируй {style}, в своём характере. Без смайликов,"
              " без кавычек, не повторяй название события дословно.")
    if event_text.startswith("серия смертей"):
        base += " Это тильт: поддержи, можно предложить короткую паузу, но не нудно."
    return base


def start_prompt(game: str, last: Optional[dict], now: float | None = None) -> Optional[str]:
    """«В прошлый раз…» при запуске игры — если прошлая сессия была давно и в ней было что-то яркое."""
    if not last:
        return None
    now = now or time.time()
    if now - int(last.get("ts", 0)) < REMIND_AFTER_S:
        return None
    hl = ", ".join(last.get("highlights") or [])
    score = _score(last.get("stats") or {})
    if not hl and not score:
        return None
    return (f"Мастер снова запустил «{game}». В прошлый раз он играл {last.get('minutes', 0)} мин"
            + (f", счёт: {score}" if score else "") + (f", запомнилось: {hl}" if hl else "")
            + ". Поприветствуй его в игре одной короткой фразой (до 14 слов), можно вспомнить прошлый раз.")


def end_prompt(game: str, minutes: int, stats: dict, highlights: list) -> str:
    score = _score(stats)
    hl = ", ".join(highlights or [])
    return (f"Мастер закончил играть в «{game}»: {minutes} мин" + (f", {score}" if score else "")
            + (f", лучшие моменты: {hl}" if hl else "")
            + ". Подведи итог одной-двумя короткими фразами в своём характере, без списков.")
