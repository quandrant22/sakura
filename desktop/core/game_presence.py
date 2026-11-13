"""desktop.core.game_presence — насколько Сакура «рядом» в игре. Заменяет прежнее «в полноэкранной игре
молчать 30 минут».

Уровни (настройка по каждой игре — game_presence {exe: уровень}, по умолчанию — game_presence_default):
  silent      — молчит; только показывает всплывашки на сцене и копит итоги сессии;
  reactions   — короткие реплики на важное: смерть серией, победа, достижение, редкое событие;
  commentator — комментирует чаще и на большее число событий;
  coop        — «напарник»: реагирует на всё заметное, подбадривает при тильте, отвечает быстрее.

Ограничение частоты — здесь (до сервера) и ещё раз на сервере: даже «напарник» не тараторит.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Mapping

LEVELS = ("silent", "reactions", "commentator", "coop")
LEVEL_NAMES = {"silent": "Молчит", "reactions": "Реакции", "commentator": "Комментатор", "coop": "Напарник"}
DEFAULT_LEVEL = "reactions"

# Минимальная пауза между голосовыми реакциями, с.
MIN_GAP_S = {"silent": float("inf"), "reactions": 45.0, "commentator": 18.0, "coop": 8.0}

# Какие события озвучивать на каком уровне (остальные — только всплывашка на сцене).
SPOKEN = {
    "silent": frozenset(),
    "reactions": frozenset({"victory", "defeat", "multikill", "ace", "achievement", "tilt", "round_win_streak",
                            "boss", "level_up"}),
    "commentator": frozenset({"victory", "defeat", "multikill", "ace", "achievement", "tilt", "round_win_streak",
                              "boss", "level_up", "death", "kill", "round_win", "round_loss", "bomb_planted",
                              "objective", "flash", "low_hp"}),
    "coop": frozenset({"victory", "defeat", "multikill", "ace", "achievement", "tilt", "round_win_streak", "boss",
                       "level_up", "death", "kill", "round_win", "round_loss", "bomb_planted", "objective", "flash",
                       "low_hp", "hurt", "dark", "session_start"}),
}
# Важное обходит паузу (победа, достижение, тильт) — но не чаще раза в 5 с.
URGENT = frozenset({"victory", "defeat", "achievement", "tilt", "ace"})
URGENT_GAP_S = 5.0


def normalize(level: object) -> str:
    s = str(level or "").strip().lower()
    return s if s in LEVELS else DEFAULT_LEVEL


def level_for(game_key: str, per_game: Mapping[str, object] | None, default: object = DEFAULT_LEVEL) -> str:
    per = per_game or {}
    if game_key and game_key in per:
        return normalize(per[game_key])
    return normalize(default)


@dataclass
class SpeechGate:
    """Решает, озвучивать ли событие: уровень, пауза с прошлой реплики, срочность."""
    last_spoken: float = -1e9
    spoken_count: int = 0
    _history: list = field(default_factory=list)

    def should_speak(self, level: str, event: str, now: float) -> bool:
        level = normalize(level)
        if event not in SPOKEN[level]:
            return False
        gap = now - self.last_spoken
        if event in URGENT:
            ok = gap >= URGENT_GAP_S
        else:
            ok = gap >= MIN_GAP_S[level]
        if ok:
            self.last_spoken = now
            self.spoken_count += 1
        return ok


@dataclass
class TiltMeter:
    """«Тильт»: много смертей подряд за короткое время → один раз поддержать (не чаще раза в 15 мин)."""
    window_s: float = 600.0
    threshold: int = 4
    cooldown_s: float = 900.0
    deaths: list = field(default_factory=list)
    last_fired: float = -1e9

    def death(self, now: float) -> bool:
        self.deaths = [t for t in self.deaths if now - t <= self.window_s] + [now]
        if len(self.deaths) >= self.threshold and now - self.last_fired >= self.cooldown_s:
            self.last_fired = now
            self.deaths.clear()
            return True
        return False

    def win(self) -> None:
        self.deaths.clear()
