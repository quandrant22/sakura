"""desktop.core.loop_lag — сторож задержки цикла событий ядра.

Спит PERIOD_S и меряет, насколько позже проснулся: это время цикл был занят синхронным кодом
(COM, psutil, сеть в корутине). Задержка больше WARN_MS — WARNING «[loop] lag N ms» (не чаще раза
в WARN_EVERY_S, с максимумом за это время). Раз в REPORT_S — сводка p50/p95/max в DEBUG и в stats().
"""
import asyncio
import logging
import os
import time

log = logging.getLogger("sakura.loop")

PERIOD_S = 0.05
WARN_MS = 50
WARN_EVERY_S = 1.0
REPORT_S = 10.0


def enable_debug(loop=None, env=None) -> bool:
    """SAKURA_LOOP_DEBUG=1 (start_dev.ps1 ставит его сам): asyncio debug и slow_callback_duration 0,05 с —
    asyncio пишет в журнал «Executing <Task …> took 0.06 seconds» с именем корутины/колбэка."""
    env = os.environ if env is None else env
    if env.get("SAKURA_LOOP_DEBUG") != "1":
        return False
    loop = loop or asyncio.get_running_loop()
    loop.set_debug(True)
    loop.slow_callback_duration = WARN_MS / 1000
    logging.getLogger("asyncio").setLevel(logging.WARNING)
    log.warning("[loop] отладка цикла включена: медленные колбэки > %d мс — в журнал", WARN_MS)
    return True


FREEZE_AFTER_S = 20.0


async def freeze_heap(delay: float = FREEZE_AFTER_S) -> None:
    """Через delay после старта (модели речи, torch и индекс файлов загружены): одна полная сборка и
    gc.freeze() — загруженное уходит в постоянное поколение, полная сборка его больше не обходит.
    Без этого каждая полная сборка держала цикл 56–64 мс (периодические «[loop] lag 59–75 ms»)."""
    import gc
    await asyncio.sleep(delay)
    t = time.monotonic()
    gc.collect()
    gc.freeze()
    log.info("[loop] куча заморожена: %d объектов, %.0f мс", gc.get_freeze_count(), (time.monotonic() - t) * 1000)


class LoopLag:
    def __init__(self, clock=time.monotonic, period=PERIOD_S, warn_ms=WARN_MS):
        self.clock = clock
        self.period = period
        self.warn_ms = warn_ms
        self._window: list[float] = []
        self._last_warn = -1e9
        self._pending_max = 0.0
        self.last_report: dict = {"count": 0}

    def observe(self, lag_ms: float, now: float | None = None) -> None:
        """Одно измерение (тестируется без цикла)."""
        now = self.clock() if now is None else now
        self._window.append(lag_ms)
        if lag_ms > self.warn_ms:
            self._pending_max = max(self._pending_max, lag_ms)
            if now - self._last_warn >= WARN_EVERY_S:
                log.warning("[loop] lag %d ms", round(self._pending_max))
                self._last_warn, self._pending_max = now, 0.0

    def report(self) -> dict:
        vals = sorted(self._window)
        self._window = []
        if not vals:
            self.last_report = {"count": 0}
            return self.last_report

        def pick(q):
            return round(vals[min(len(vals) - 1, int(q * len(vals)))], 1)
        self.last_report = {"count": len(vals), "p50": pick(0.5), "p95": pick(0.95), "max": round(vals[-1], 1)}
        log.debug("[loop] задержка за %d с: p50 %.1f мс, p95 %.1f мс, max %.1f мс", REPORT_S,
                  self.last_report["p50"], self.last_report["p95"], self.last_report["max"])
        return self.last_report

    async def run(self):
        next_report = self.clock() + REPORT_S
        while True:
            t0 = self.clock()
            await asyncio.sleep(self.period)
            now = self.clock()
            self.observe(max(0.0, (now - t0 - self.period) * 1000), now)
            if now >= next_report:
                next_report = now + REPORT_S
                self.report()
