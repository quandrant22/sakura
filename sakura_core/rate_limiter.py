"""Квоты Gemma для browser agent (S2/S3): RPM, RPD и блокировки после 429.

На каждую модель — свой token bucket (ёмкость GEMMA_RPM, пополнение
GEMMA_RPM/60 в секунду) и суточный счётчик GEMMA_RPD. Сутки квоты Gemini API
считаются по тихоокеанскому времени: счётчик сбрасывается в полночь
America/Los_Angeles и хранится в data/gemma_quota.json (переживает рестарт).

После 429 модель блокируется на retry delay из ответа, иначе 4→8→16→32 с;
пятый 429 подряд (или RPD) — модель «исчерпана» до сброса суток (квота на
сутки) или минимум на минуту (квота на минуту). 500/503 — так же, но
5→10→20 с и потом модель выведена на SERVER_BLOCK_S (причина unavailable). Решение о переходе по
цепочке — у вызывающего (sakura_core/llm.generate_agent).

Лимитер ничего не ждёт сам: wait(model) говорит, сколько секунд до
возможности вызова (0 — можно сейчас), take(model) забирает токен.
"""

from __future__ import annotations

import datetime as dt
import json
import logging
import os
import time
from pathlib import Path
from zoneinfo import ZoneInfo

import config

log = logging.getLogger("sakura.rate_limiter")

PT = ZoneInfo("America/Los_Angeles")
BACKOFF_S = (4.0, 8.0, 16.0, 32.0, 32.0)    # повторы 1…5; дальше — следующая модель
MAX_429 = len(BACKOFF_S)
MINUTE_BLOCK_S = 60.0
SERVER_BACKOFF_S = (5.0, 10.0, 20.0)        # 500/503: повторы 1…3; дальше — следующая модель
MAX_5XX = len(SERVER_BACKOFF_S)
SERVER_BLOCK_S = 60.0                        # сколько модель выведена после 3 повторов 500
QUOTA_FILE = Path("data") / "gemma_quota.json"


def pt_day(now: float) -> str:
    return dt.datetime.fromtimestamp(now, PT).date().isoformat()


def next_reset(now: float) -> float:
    """Ближайшая полночь по тихоокеанскому времени (unix-время)."""
    local = dt.datetime.fromtimestamp(now, PT)
    midnight = dt.datetime.combine(local.date() + dt.timedelta(days=1), dt.time(0), PT)
    return midnight.timestamp()


class RateLimiter:
    def __init__(self, rpm: int | None = None, rpd: int | None = None,
                 path: Path | None = QUOTA_FILE, clock=time.time):
        self.rpm = max(1, int(rpm if rpm is not None else config.GEMMA_RPM))
        self.rpd = max(1, int(rpd if rpd is not None else config.GEMMA_RPD))
        self.path = path
        self.clock = clock
        self._tokens: dict[str, float] = {}
        self._refilled: dict[str, float] = {}
        self._day = pt_day(clock())
        self._used: dict[str, int] = {}
        self._blocked: dict[str, float] = {}        # model → до какого времени нельзя
        self._exhausted: dict[str, float] = {}      # model → до какого времени исчерпана
        self._strikes: dict[str, int] = {}          # 429 подряд
        self._strikes_5xx: dict[str, int] = {}      # 500/503 подряд
        self._why: dict[str, str] = {}              # причина вывода: quota | unavailable
        self._load()

    # ── RPD: персистентность ──────────────────────────────────────

    def _load(self) -> None:
        if self.path is None:
            return
        try:
            raw = json.loads(self.path.read_text(encoding="utf-8"))
        except FileNotFoundError:
            return
        except (OSError, ValueError) as e:
            log.warning(f"[quota] {self.path}: не прочитан ({type(e).__name__})")
            return
        if raw.get("day") == self._day:
            self._used = {str(k): int(v) for k, v in (raw.get("used") or {}).items()}

    def _save(self) -> None:
        if self.path is None:
            return
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            tmp = self.path.with_suffix(".tmp")
            tmp.write_text(json.dumps({"day": self._day, "used": self._used}), encoding="utf-8")
            os.replace(tmp, self.path)
        except OSError as e:
            log.warning(f"[quota] {self.path}: не сохранён ({type(e).__name__})")

    def _roll_day(self, now: float) -> None:
        day = pt_day(now)
        if day != self._day:
            self._day = day
            self._used = {}
            self._exhausted = {m: t for m, t in self._exhausted.items() if t > now}
            self._save()

    # ── RPM: token bucket ─────────────────────────────────────────

    def _refill(self, model: str, now: float) -> float:
        rate = self.rpm / 60.0
        tokens = self._tokens.get(model, float(self.rpm))
        last = self._refilled.get(model, now)
        tokens = min(float(self.rpm), tokens + (now - last) * rate)
        self._tokens[model] = tokens
        self._refilled[model] = now
        return tokens

    # ── API ───────────────────────────────────────────────────────

    def used(self, model: str) -> int:
        self._roll_day(self.clock())
        return self._used.get(model, 0)

    def exhausted_until(self, model: str) -> float | None:
        """До какого времени модель исчерпана (RPD или пять 429), иначе None."""
        now = self.clock()
        self._roll_day(now)
        if self._used.get(model, 0) >= self.rpd:
            return next_reset(now)
        until = self._exhausted.get(model)
        return until if until and until > now else None

    def exhausted_reason(self, model: str) -> str:
        """quota (429/RPD) или unavailable (500/503)."""
        if self._used.get(model, 0) >= self.rpd:
            return "quota"
        return self._why.get(model, "quota")

    def wait(self, model: str) -> float:
        """Секунд до возможности вызова; 0 — можно сейчас. Исчерпанная модель —
        время до её восстановления."""
        now = self.clock()
        until = self.exhausted_until(model)
        if until is not None:
            return until - now
        wait = max(0.0, self._blocked.get(model, 0.0) - now)
        tokens = self._refill(model, now)
        if tokens < 1.0:
            wait = max(wait, (1.0 - tokens) * 60.0 / self.rpm)
        return wait

    def take(self, model: str) -> None:
        """Забрать токен RPM и единицу RPD (вызов уходит в API)."""
        now = self.clock()
        self._roll_day(now)
        self._tokens[model] = self._refill(model, now) - 1.0
        self._used[model] = self._used.get(model, 0) + 1
        self._save()

    def on_success(self, model: str) -> None:
        self._strikes.pop(model, None)
        self._strikes_5xx.pop(model, None)
        self._blocked.pop(model, None)

    def on_server_error(self, model: str) -> bool:
        """Учесть 500/503. True — повторить после wait(), False — модель
        выведена на SERVER_BLOCK_S (причина unavailable)."""
        now = self.clock()
        strikes = self._strikes_5xx.get(model, 0) + 1
        self._strikes_5xx[model] = strikes
        if strikes > MAX_5XX:
            self._exhausted[model] = now + SERVER_BLOCK_S
            self._why[model] = "unavailable"
            self._strikes_5xx.pop(model, None)
            return False
        self._blocked[model] = now + SERVER_BACKOFF_S[strikes - 1]
        return True

    def on_429(self, model: str, retry_delay: float | None = None,
               per_day: bool = False) -> bool:
        """Учесть 429. True — модель можно повторить (после wait()),
        False — повторы исчерпаны, модель выведена до восстановления."""
        now = self.clock()
        strikes = self._strikes.get(model, 0) + 1
        self._strikes[model] = strikes
        if per_day:
            self._exhausted[model] = next_reset(now)
            self._why[model] = "quota"
            self._strikes.pop(model, None)
            return False
        if strikes > MAX_429:
            self._exhausted[model] = now + max(retry_delay or 0.0, MINUTE_BLOCK_S)
            self._why[model] = "quota"
            self._strikes.pop(model, None)
            return False
        delay = retry_delay if retry_delay and retry_delay > 0 else BACKOFF_S[strikes - 1]
        self._blocked[model] = now + delay
        return True


_limiter: RateLimiter | None = None


def get() -> RateLimiter:
    global _limiter
    if _limiter is None:
        _limiter = RateLimiter()
    return _limiter
