"""Bounded, thread-safe reconnect queue; wire messages remain unchanged."""
import asyncio
from collections import deque
import json
import logging
import threading
import time

log = logging.getLogger("sakura.agent")


class Outbox:
    LIMIT = 10
    TTL = 30.0

    def __init__(self):
        self._pending = deque()
        self._lock = threading.Lock()
        self._sending = asyncio.Lock()

    def _expire(self):
        now = time.monotonic()
        while self._pending and now - self._pending[0][0] >= self.TTL:
            _, kind, _ = self._pending.popleft()
            log.warning("[outbox] discarded type=%s: older than 30s", kind)

    def put(self, obj):
        kind = obj.get("type", "unknown")
        # Snapshot before crossing threads; do not retain mutable caller data.
        try:
            wire = json.dumps(obj)
        except (TypeError, ValueError):
            log.exception("[outbox] discarded type=%s: invalid JSON", kind)
            return False
        with self._lock:
            self._expire()
            if len(self._pending) >= self.LIMIT:
                _, discarded, _ = self._pending.popleft()
                log.warning("[outbox] discarded type=%s: queue full", discarded)
            self._pending.append((time.monotonic(), kind, wire))
        return True

    async def flush(self, ws):
        async with self._sending:
            while True:
                with self._lock:
                    self._expire()
                    if not self._pending:
                        return
                    item = self._pending[0]
                # Retain on failure, using the original timestamp for TTL.
                await ws.send(item[2])
                with self._lock:
                    # A producer may have evicted this item during the await.
                    if self._pending and self._pending[0] is item:
                        self._pending.popleft()


def log_send_result(future, kind):
    try:
        future.result()
    except Exception:
        log.exception("[outbox] send failed type=%s", kind)
