"""
modules/game_hub.py — Игровой хаб: контекст, подсказки, поиск гайдов.

Предоставляет игровой контекст для оверлея и умные ответы
во время игровой сессии.
"""

import json
import logging
import os
import time
from typing import Optional

log = logging.getLogger("sakura.game_hub")

GAME_CONTEXT_FILE = "memory/game_hub.json"

# Текущее состояние игровой сессии
_session: dict = {
    "game": None,
    "started_at": None,
    "last_screenshot": None,
    "mood": "neutral",        # calm / intense / farming / boss / exploration
    "mood_changed_at": None,
    "highlights": [],
    "questions": [],          # вопросы игрока во время сессии
}


def get_game_context() -> dict:
    """Возвращает текущий игровой контекст для промпта."""
    return _session.copy()


def set_game_active(game_name: str):
    """Отмечает что игра запущена."""
    _session["game"] = game_name
    _session["started_at"] = time.time()
    _session["mood"] = "neutral"
    _session["mood_changed_at"] = time.time()
    log.info(f"[game_hub] Игра активна: {game_name}")


def set_game_mood(mood: str):
    """Обновляет настроение игры (calm/intense/farming/boss/exploration)."""
    if mood != _session.get("mood"):
        old = _session.get("mood")
        _session["mood"] = mood
        _session["mood_changed_at"] = time.time()
        log.info(f"[game_hub] Настроение: {old} → {mood}")


def set_game_idle():
    """Игра завершена или не активна."""
    if _session.get("game"):
        duration = time.time() - (_session.get("started_at") or time.time())
        log.info(f"[game_hub] Сессия завершена: {_session['game']} ({duration/60:.0f}мин)")
    _session["game"] = None
    _session["started_at"] = None
    _session["mood"] = "neutral"


def add_highlight(description: str):
    """Добавляет хайлайт в текущую сессию."""
    highlight = {
        "time": time.time(),
        "description": description,
        "mood": _session.get("mood", "neutral"),
    }
    _session.setdefault("highlights", []).append(highlight)
    # Ограничение — последние 20 хайлайтов
    if len(_session["highlights"]) > 20:
        _session["highlights"] = _session["highlights"][-20:]
    log.info(f"[game_hub] Хайлайт: {description[:50]}")


def get_session_duration() -> float:
    """Длительность текущей сессии в секундах."""
    if _session.get("started_at"):
        return time.time() - _session["started_at"]
    return 0


def get_session_summary() -> str:
    """Краткое резюме сессии для озвучки."""
    game = _session.get("game")
    if not game:
        return "Сейчас не играю."

    dur = get_session_duration()
    minutes = int(dur / 60)
    highlights = _session.get("highlights", [])

    parts = [f"Играю в {game}"]
    if minutes > 0:
        parts.append(f"Уже {minutes} минут")
    if highlights:
        last = highlights[-1]["description"]
        parts.append(f"Последнее: {last}")

    return ". ".join(parts) + "."


def get_mood_color() -> str:
    """Цвет для оверлея по настроению игры."""
    colors = {
        "calm":        "#4a9eff",   # спокойный синий
        "neutral":     "#9a7fb5",   # фиолетовый
        "intense":     "#ff4444",   # красный
        "farming":     "#44cc88",   # зелёный
        "boss":        "#ff6622",   # оранжевый
        "exploration": "#88aaff",   # голубой
        "victory":     "#ffd700",   # золотой
    }
    return colors.get(_session.get("mood", "neutral"), "#9a7fb5")


def build_game_prompt_context() -> str:
    """Строит контекст для промпта LLM во время игры."""
    if not _session.get("game"):
        return ""

    game = _session["game"]
    mood = _session.get("mood", "neutral")
    dur = get_session_duration()
    minutes = int(dur / 60)

    lines = [f"Мастер играет в {game} уже {minutes} минут."]
    lines.append(f"Настроение игры: {mood}.")

    highlights = _session.get("highlights", [])
    if highlights:
        lines.append(f"Хайлайты сессии: {len(highlights)} шт.")
        if highlights:
            lines.append(f"Последний: {highlights[-1]['description']}")

    return "\n".join(lines)


def should_suggest_break() -> bool:
    """Нужно ли предложить перерыв (после 2+ часов)."""
    dur = get_session_duration()
    return dur > 7200  # 2 часа


def get_game_context_for_device(active_window: str) -> Optional[str]:
    """Определяет игру из активного окна и обновляет контекст."""
    if not active_window:
        return None

    aw = active_window.lower()

    # Популярные игры — ключевые слова в названии окна
    _game_hints = {
        "minecraft":  "Minecraft",
        "terraria":   "Terraria",
        "gta":        "GTA V",
        "cyberpunk":  "Cyberpunk 2077",
        "witcher":    "The Witcher 3",
        "elden":      "Elden Ring",
        "dark souls": "Dark Souls",
        "valorant":   "Valorant",
        "cs2":        "Counter-Strike 2",
        "counter-strike": "Counter-Strike 2",
        "dota":       "Dota 2",
        "league":     "League of Legends",
        "fortnite":   "Fortnite",
        "apex":       "Apex Legends",
        "pubg":       "PUBG",
        "rust":       "Rust",
        "starfield":  "Starfield",
        "palworld":   "Palworld",
        "helldivers": "Helldivers 2",
        "steam":      None,
    }

    for hint, game in _game_hints.items():
        if hint in aw and game:
            if _session.get("game") != game:
                set_game_active(game)
            return game

    # Если окно не похоже на игру — сбрасываем
    if _session.get("game") and not any(
        h in aw for h in _game_hints if _game_hints[h]
    ):
        # Небольшая задержка перед сбросом (окно может мелькнуть)
        if _session.get("mood_changed_at"):
            elapsed = time.time() - _session["mood_changed_at"]
            if elapsed > 10:
                set_game_idle()

    return _session.get("game")
