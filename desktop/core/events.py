"""core/events.py — шина событий ядра.

Ядро излучает события («слушаю», «реплика пользователя», …), оболочка слушает.
Шина не знает про UI: оболочку можно заменить (сейчас Qt, потом хоть Rust) —
ядро при этом не меняется.
"""

import logging
import threading

log = logging.getLogger("sakura.events")


class EventBus:
    def __init__(self):
        self._subscribers = []
        self._lock = threading.Lock()

    def subscribe(self, callback):
        """callback(event: str, data: dict). Может вызываться из любого потока."""
        with self._lock:
            self._subscribers.append(callback)

    def emit(self, event: str, **data):
        with self._lock:
            subscribers = list(self._subscribers)
        for callback in subscribers:
            try:
                callback(event, data)
            except Exception as e:
                log.error(f"подписчик на «{event}»: {e}")
