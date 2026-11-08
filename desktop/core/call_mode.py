"""desktop.core.call_mode — Режим звонков (Call Mode) для Discord, Telegram, Zoom.

Вдохновлен capri-desktop CallMode.cs:
Позволяет Сакуре выступать компаньоном во время голосовых звонков:
1. Поручения (Errands):
   - «Зайди в звонок, скажи ребятам, что я отойду, и запусти то, что они выберут».
   - Сакура объявляет в войс причину отсутствия мастера с фирменным юмором.
   - Слушает реплики друзей и исполняет выбор (запуск игры, песни).
2. Безопасность (Security Separation):
   - Реплики друзей помечаются как собеседники звонка (callers).
   - Только голос мастера или ввод в локальный чат Сакуры может подтвердить выполнение системных команд.
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional

log = logging.getLogger("sakura.call_mode")


@dataclass
class CallErrand:
    action: str  # e.g. "launch_game", "play_song", "pass_message"
    message_to_say: str = ""
    timeout: float = 300.0  # 5 минут
    created_at: float = field(default_factory=time.time)

    @property
    def is_expired(self) -> bool:
        return time.time() - self.created_at > self.timeout


@dataclass
class HeldRequest:
    caller_text: str
    suggested_action: str
    suggested_args: Dict[str, Any]
    created_at: float = field(default_factory=time.time)
    expires_in: float = 60.0

    @property
    def is_expired(self) -> bool:
        return time.time() - self.created_at > self.expires_in


class CallModeManager:
    """Управление состоянием звонка, поручениями и подтверждениями безопасности."""

    def __init__(
        self,
        on_say_in_call: Optional[Callable[[str], None]] = None,
        on_action: Optional[Callable[[str, Dict[str, Any]], None]] = None,
    ):
        self.on_say_in_call = on_say_in_call or (lambda text: log.info("Call Say: %s", text))
        self.on_action = on_action or (lambda act, args: log.info("Call Action: %s (%s)", act, args))
        self.active: bool = False
        self.current_app: str = "Discord"  # Discord, Telegram, Zoom, Teams
        self.active_errand: Optional[CallErrand] = None
        self.held_request: Optional[HeldRequest] = None

    def enable(self, app_name: str = "Discord"):
        self.active = True
        self.current_app = app_name
        log.info("Call mode enabled for %s", app_name)

    def disable(self):
        self.active = False
        self.active_errand = None
        self.held_request = None
        log.info("Call mode disabled")

    def set_errand(self, action: str, message: str = "") -> CallErrand:
        """Назначить поручение для звонка."""
        errand = CallErrand(action=action, message_to_say=message)
        self.active_errand = errand
        self.active = True
        if message:
            self.on_say_in_call(message)
        return errand

    def process_caller_speech(self, text: str) -> Optional[str]:
        """Обработка реплики участника звонка (друга)."""
        if not self.active:
            return None

        clean = text.lower().strip()

        # Если активно поручение на выбор игры
        if self.active_errand and not self.active_errand.is_expired:
            if self.active_errand.action == "launch_game":
                # Друг назвал игру
                game_name = text.strip()
                self.held_request = HeldRequest(
                    caller_text=text,
                    suggested_action="launch_game",
                    suggested_args={"game": game_name},
                )
                self.active_errand = None
                return f"Ребята в звонке предлагают запустить «{game_name}». Запустить? (Скажи «Да» для подтверждения)"

        return None

    def confirm_held_request(self, confirmed: bool) -> Optional[str]:
        """Подтверждение запроса из звонка самим пользователем."""
        if not self.held_request or self.held_request.is_expired:
            self.held_request = None
            return "Нет активных запросов от друзей для подтверждения."

        req = self.held_request
        self.held_request = None

        if confirmed:
            self.on_action(req.suggested_action, req.suggested_args)
            return f"Отлично, запускаю {req.suggested_args.get('game', '')} по просьбе ребят!"
        return "Отклонила предложение ребят."
