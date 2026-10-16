"""Лимиты рукопожатий (PROTOCOL.md §6): защита от перебора и исчерпания.

  * параллельных рукопожатий с одного IP — 4, всего — 64;
  * новых рукопожатий с одного IP — 30 в минуту (скользящее окно).
IP берётся из сокета (remote_address), не из заголовков.
"""

from __future__ import annotations

import threading
import time
from collections import defaultdict, deque

PER_IP_PARALLEL = 4
TOTAL_PARALLEL = 64
PER_IP_PER_MINUTE = 30
WINDOW_S = 60.0


class HandshakeLimiter:
    def __init__(self, *, per_ip_parallel=PER_IP_PARALLEL, total_parallel=TOTAL_PARALLEL,
                 per_ip_per_minute=PER_IP_PER_MINUTE, clock=time.monotonic):
        self.per_ip_parallel = per_ip_parallel
        self.total_parallel = total_parallel
        self.per_ip_per_minute = per_ip_per_minute
        self._clock = clock
        self._lock = threading.Lock()
        self._active: dict[str, int] = defaultdict(int)
        self._total = 0
        self._recent: dict[str, deque] = defaultdict(deque)

    def try_begin(self, ip: str) -> bool:
        now = self._clock()
        with self._lock:
            q = self._recent[ip]
            while q and now - q[0] >= WINDOW_S:
                q.popleft()
            if (self._total >= self.total_parallel
                    or self._active[ip] >= self.per_ip_parallel
                    or len(q) >= self.per_ip_per_minute):
                return False
            q.append(now)
            self._active[ip] += 1
            self._total += 1
            return True

    def end(self, ip: str) -> None:
        with self._lock:
            if self._active.get(ip, 0) > 0:
                self._active[ip] -= 1
                self._total -= 1
                if not self._active[ip]:
                    del self._active[ip]
