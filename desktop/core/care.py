"""desktop.core.care — Система заботы и мониторинга состояния пользователя (Care System).

Вдохновлен capri-desktop Care.cs:
Отслеживает непрерывную активность за компьютером:
- "water": напоминание выпить воды (раз в 45-60 минут).
- "stretch": размять спину и шею (раз в 60-90 минут).
- "eyes": дать глазам отдохнуть (правило 20-20-20 каждые 30-40 минут).
- "late": ночной упрек/напоминание лечь спать (после 01:00 ночи).
- "game_break": перерыв после длинной игровой сессии (>2 часов в игре).
- "bored": забавный комментарий, если за компьютером долго скучают.

Интегрируется с модулем проактивности и голосом Сакуры.
"""

from __future__ import annotations

import datetime
import enum
import logging
import time
from dataclasses import dataclass, field
from typing import Callable, Dict, Optional

log = logging.getLogger("sakura.care")


class CareKind(enum.Enum):
    WATER = "water"
    STRETCH = "stretch"
    EYES = "eyes"
    LATE = "late"
    GAME_BREAK = "game_break"
    BORED = "bored"


_DEFAULT_INTERVALS = {
    CareKind.WATER: 50 * 60,       # 50 минут
    CareKind.STRETCH: 75 * 60,     # 75 минут
    CareKind.EYES: 35 * 60,        # 35 минут
    CareKind.GAME_BREAK: 120 * 60, # 2 часа
    CareKind.BORED: 60 * 60,       # 1 час
}

_CARE_MESSAGES = {
    CareKind.WATER: "Мастер, сделай пару глотков воды. Не забывай про гидратацию!",
    CareKind.STRETCH: "Ты уже больше часа сидишь в одной позе. Встань и потянись, спина спасибо скажет.",
    CareKind.EYES: "Оторви взгляд от монитора на 20 секунд и посмотри в окно. Глазам нужен отдых.",
    CareKind.LATE: "Уже глубокая ночь. Хватит залипать в экран, иди спать, завтра будешь жалеть!",
    CareKind.GAME_BREAK: "Ты непрерывно играешь уже два часа. Сделай паузу на чай, катка никуда не убежит.",
    CareKind.BORED: "Что-то тут слишком тихо... Всё в порядке или ты уснул за клавиатурой?",
}


class CareManager:
    """Мониторинг времени и отправка ненавязчивых напоминаний о здоровье."""

    def __init__(
        self,
        on_care_nudge: Optional[Callable[[CareKind, str], None]] = None,
        enabled: bool = True,
        bedtime_hour: int = 1,  # 01:00 ночи
    ):
        self.on_care_nudge = on_care_nudge or (lambda k, msg: log.info("Care Nudge [%s]: %s", k.value, msg))
        self.enabled = enabled
        self.bedtime_hour = bedtime_hour
        self.active_since: float = time.time()
        self.last_user_activity: float = time.time()
        self.game_started_at: Optional[float] = None
        self.is_playing_game: bool = False

        self.last_nudge_time: Dict[CareKind, float] = {k: time.time() for k in CareKind}
        self.nudge_intervals = dict(_DEFAULT_INTERVALS)

    def note_user_activity(self):
        """Отметка пользовательского ввода (движение мыши, клик, сообщение)."""
        self.last_user_activity = time.time()

    def set_gaming_state(self, playing: bool, game_name: str = ""):
        """Обновление состояния игры."""
        if playing and not self.is_playing_game:
            self.game_started_at = time.time()
            self.last_nudge_time[CareKind.GAME_BREAK] = time.time()
        elif not playing:
            self.game_started_at = None
        self.is_playing_game = playing

    def check(self, now_time: Optional[float] = None, current_dt: Optional[datetime.datetime] = None) -> list[CareKind]:
        """Периодическая проверка (вызывается раз в минуту или из тикера)."""
        if not self.enabled:
            return []

        now = now_time or time.time()
        dt = current_dt or datetime.datetime.now()
        triggered: list[CareKind] = []

        # 1. Ночной упрек (Late night)
        if dt.hour >= self.bedtime_hour and dt.hour < 6:
            if now - self.last_nudge_time[CareKind.LATE] >= 4 * 3600:  # Раз в 4 часа
                triggered.append(CareKind.LATE)
                self.last_nudge_time[CareKind.LATE] = now
                self.on_care_nudge(CareKind.LATE, _CARE_MESSAGES[CareKind.LATE])

        # 2. Вода
        if now - self.last_nudge_time[CareKind.WATER] >= self.nudge_intervals[CareKind.WATER]:
            triggered.append(CareKind.WATER)
            self.last_nudge_time[CareKind.WATER] = now
            self.on_care_nudge(CareKind.WATER, _CARE_MESSAGES[CareKind.WATER])

        # 3. Разминка
        if now - self.last_nudge_time[CareKind.STRETCH] >= self.nudge_intervals[CareKind.STRETCH]:
            triggered.append(CareKind.STRETCH)
            self.last_nudge_time[CareKind.STRETCH] = now
            self.on_care_nudge(CareKind.STRETCH, _CARE_MESSAGES[CareKind.STRETCH])

        # 4. Глаза
        if now - self.last_nudge_time[CareKind.EYES] >= self.nudge_intervals[CareKind.EYES]:
            triggered.append(CareKind.EYES)
            self.last_nudge_time[CareKind.EYES] = now
            self.on_care_nudge(CareKind.EYES, _CARE_MESSAGES[CareKind.EYES])

        # 5. Игровой перерыв
        if self.is_playing_game and self.game_started_at:
            if now - self.game_started_at >= self.nudge_intervals[CareKind.GAME_BREAK]:
                if now - self.last_nudge_time[CareKind.GAME_BREAK] >= self.nudge_intervals[CareKind.GAME_BREAK]:
                    triggered.append(CareKind.GAME_BREAK)
                    self.last_nudge_time[CareKind.GAME_BREAK] = now
                    self.on_care_nudge(CareKind.GAME_BREAK, _CARE_MESSAGES[CareKind.GAME_BREAK])

        return triggered
