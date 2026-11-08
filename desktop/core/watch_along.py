"""desktop.core.watch_along — Совместный просмотр видео и стримов (Watch Along).

Вдохновлен capri-desktop WatchAlong.cs:
Пользователь включает YouTube, фильм, аниме или стрим и просит: «Сакура, посмотри со мной».
- Сакура отслеживает происходящее на экране и звук с компьютера.
- Поддерживает скользящую память реплик сюжета (до 24 последних реплик).
- Периодически отпускает живые комментарии и эмоции к происходящему в своём неповторимом стиле.
"""

from __future__ import annotations

import collections
import logging
import time
from dataclasses import dataclass, field
from typing import Callable, Optional

log = logging.getLogger("sakura.watch_along")


@dataclass
class WatchMemory:
    max_lines: int = 24
    lines: collections.deque[str] = field(default_factory=collections.deque)

    def add_line(self, text: str):
        cleaned = text.strip()
        if not cleaned:
            return
        self.lines.append(cleaned)
        while len(self.lines) > self.max_lines:
            self.lines.popleft()

    def get_summary_context(self) -> str:
        return "\n".join(self.lines)

    def clear(self):
        self.lines.clear()


class WatchAlongManager:
    """Управление режимом совместного просмотра."""

    def __init__(
        self,
        on_comment: Optional[Callable[[str], None]] = None,
        min_comment_gap: float = 25.0,  # Сакура не перебивает фильм слишком часто
    ):
        self.on_comment = on_comment or (lambda text: log.info("Watch Along Comment: %s", text))
        self.min_comment_gap = min_comment_gap
        self.active: bool = False
        self.memory = WatchMemory()
        self.last_comment_time: float = 0.0

    def start(self, initial_topic: str = ""):
        self.active = True
        self.memory.clear()
        if initial_topic:
            self.memory.add_line(f"[Тема: {initial_topic}]")
        self.last_comment_time = time.time()
        self.on_comment("Включай, я смотрю вместе с тобой!")
        log.info("Watch along started")

    def stop(self):
        self.active = False
        self.memory.clear()
        self.on_comment("Ладно, потом досмотрим.")
        log.info("Watch along stopped")

    def feed_speech(self, text: str):
        """Добавить услышанную из видео фразу в память."""
        if not self.active:
            return
        self.memory.add_line(text)

    def maybe_comment(self, prompt_generator: Optional[Callable[[str], str]] = None) -> Optional[str]:
        """Проверить, уместно ли сейчас отпустить реплику."""
        if not self.active:
            return None

        now = time.time()
        if now - self.last_comment_time < self.min_comment_gap:
            return None

        context = self.memory.get_summary_context()
        if not context:
            return None

        self.last_comment_time = now
        comment = prompt_generator(context) if prompt_generator else "Ого, вот это поворот!"
        if comment:
            self.on_comment(comment)
        return comment
