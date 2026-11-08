"""desktop.core.lookout — Фоновый визуальный дозор (Lookout).

Вдохновлен capri-desktop Lookout.cs:
Позволяет пользователю или агенту поручить Сакуре следить за экраном:
- «Скажи, когда скачается игра / будет 100%»
- «Предупреди, когда босс появится / закончится матч»
- «Сообщи, когда напишет [имя]»

Фоновый поток периодически захватывает кадр экрана (или активного окна),
выполняет поиск заданных условий (по ключевым словам / OCR / VLM)
и вызывает голосовое уведомление Сакуры.
"""

from __future__ import annotations

import logging
import re
import threading
import time
from dataclasses import dataclass, field
from typing import Callable, Optional

log = logging.getLogger("sakura.lookout")


@dataclass
class WatchCondition:
    id: int
    text: str
    repeat: bool = False
    created_at: float = field(default_factory=time.time)
    last_triggered: float = 0.0


class LookoutEngine:
    def __init__(
        self,
        capture_func: Optional[Callable[[], Optional[str]]] = None,  # возвращает распознанный текст или описание экрана
        on_alert: Optional[Callable[[str], None]] = None,
        poll_interval: float = 4.0,
    ):
        self.capture_func = capture_func
        self.on_alert = on_alert or (lambda msg: log.info("Lookout Alert: %s", msg))
        self.poll_interval = poll_interval
        self.watches: list[WatchCondition] = []
        self._next_id = 1
        self._lock = threading.Lock()
        self._stop_event = threading.Event()
        self._thread: Optional[threading.Thread] = None

    def add_watch(self, text: str, repeat: bool = False) -> int:
        """Добавить условие наблюдения за экраном."""
        clean_text = text.strip()
        if not clean_text:
            raise ValueError("Условие не может быть пустым.")

        with self._lock:
            watch_id = self._next_id
            self._next_id += 1
            watch = WatchCondition(id=watch_id, text=clean_text, repeat=repeat)
            self.watches.append(watch)
            log.info("Lookout: добавлено наблюдение #%d '%s'", watch_id, clean_text)

        self._ensure_running()
        return watch_id

    def remove_watch(self, target: str | int) -> list[str]:
        """Удалить наблюдение по номеру или подстроке."""
        removed = []
        with self._lock:
            if isinstance(target, int):
                for i in range(len(self.watches) - 1, -1, -1):
                    if self.watches[i].id == target:
                        removed.append(self.watches[i].text)
                        self.watches.pop(i)
            else:
                pat = str(target).lower().strip()
                for i in range(len(self.watches) - 1, -1, -1):
                    if not pat or pat in self.watches[i].text.lower():
                        removed.append(self.watches[i].text)
                        self.watches.pop(i)

            if not self.watches and self._thread:
                self.stop()

        return removed

    def list_watches(self) -> list[dict]:
        with self._lock:
            return [
                {
                    "id": w.id,
                    "text": w.text,
                    "repeat": w.repeat,
                    "active_seconds": round(time.time() - w.created_at, 1),
                }
                for w in self.watches
            ]

    def _ensure_running(self):
        with self._lock:
            if self._thread is None or not self._thread.is_alive():
                self._stop_event.clear()
                self._thread = threading.Thread(target=self._worker_loop, daemon=True, name="SakuraLookout")
                self._thread.start()

    def stop(self):
        self._stop_event.set()
        if self._thread and self._thread.is_alive():
            self._thread = None

    def _worker_loop(self):
        log.debug("Lookout worker started")
        while not self._stop_event.is_set():
            time.sleep(self.poll_interval)
            with self._lock:
                if not self.watches:
                    break
                active_copy = list(self.watches)

            if not self.capture_func:
                continue

            try:
                screen_text = self.capture_func()
                if not screen_text:
                    continue
                self._check_screen(screen_text, active_copy)
            except Exception as e:
                log.warning("Lookout capture error: %s", e)

    def _check_screen(self, screen_text: str, active_watches: list[WatchCondition]):
        now = time.time()
        to_remove = []

        for w in active_watches:
            # Проверка соответствия ключевым словам или условиям
            keywords = [k.strip().lower() for k in re.split(r"[,;]|\s+и\s+", w.text) if k.strip()]
            matched = False
            screen_lower = screen_text.lower()

            if all(k in screen_lower for k in keywords):
                matched = True

            if matched:
                w.last_triggered = now
                self.on_alert(f"Мастер, условие на экране сработало: {w.text}!")
                if not w.repeat:
                    to_remove.append(w.id)

        if to_remove:
            with self._lock:
                self.watches = [w for w in self.watches if w.id not in to_remove]
