"""desktop.core.game_hud.telemetry.base — Базовый интерфейс для адаптеров нативной телеметрии игр."""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Optional

from desktop.core.game_hud.types import GameState


class TelemetryProvider(ABC):
    """Адаптер для получения точной телеметрии из официальных API игр (Shared Memory, UDP, GSI)."""

    @abstractmethod
    def is_available(self) -> bool:
        """Доступен ли источник телеметрии прямо сейчас (запущен ли сервер/игра)."""
        ...

    @abstractmethod
    def start(self) -> None:
        """Запуск слушателя/поллера телеметрии."""
        ...

    @abstractmethod
    def stop(self) -> None:
        """Остановка слушателя/поллера."""
        ...

    @abstractmethod
    def get_state(self) -> Optional[GameState]:
        """Возвращает актуальный GameState игры со 100% точностью."""
        ...
