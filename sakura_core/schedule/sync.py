"""Приём расписания из любого источника и фоновый цикл.

ingest() — единый вход (R3): прямой опрос и букмарклет приносят один и тот же
ttable, дальше путь общий: разбор → проверка группы → слияние → изменения →
уведомления. loop() — раз в минуту: напоминания/изменения (notify) и, если
включён источник direct, опрос сайта в часы SCHEDULE_SYNC_HOURS.
"""
from __future__ import annotations

import asyncio
import hashlib
import logging
import time as _time
from dataclasses import dataclass, field
from datetime import datetime, timedelta

import config
from sakura_core.schedule.diff import Change, diff
from sakura_core.schedule.parse import ParseError, parse_eios, parse_ttable
from sakura_core.schedule.store import ScheduleStore, get_store, merge

log = logging.getLogger("sakura.schedule")

BLOCKED_RETRY = timedelta(hours=24)
_lock = asyncio.Lock()


@dataclass
class SyncResult:
    ok: bool
    source: str
    count: int = 0
    changes: list[Change] = field(default_factory=list)
    error: str | None = None

    def summary(self) -> str:
        if not self.ok:
            return {
                "not_schedule": "пришло не расписание (похоже на страницу проверки сайта)",
                "wrong_group": f"это расписание другой группы, жду {config.MUIV_GROUP}",
                "empty_suspicious": "пришло пустое расписание, старое оставила",
                "blocked": "сайт не пускает сервер (защита)",
                "auth": "ЭИОС не принял логин или пароль",
                "auth_stopped": "входы в ЭИОС остановлены после неверного пароля — исправь .env и перезапусти",
                "no_credentials": "не заданы EIOS_USERNAME и EIOS_PASSWORD",
            }.get(self.error or "", f"ошибка: {self.error}")
        n = self.count
        pairs = "занятие" if n % 10 == 1 and n % 100 != 11 else (
            "занятия" if 2 <= n % 10 <= 4 and not 12 <= n % 100 <= 14 else "занятий")
        c = len(self.changes)
        ch = "без изменений" if c == 0 else f"изменений: {c}"
        return f"{n} {pairs}, {ch}"


def _parse(raw: str, source: str):
    if source == "eios":
        return parse_eios(raw, config.MUIV_GROUP)
    return parse_ttable(raw)


def ingest(ttable: str, source: str, now: datetime,
           store: ScheduleStore | None = None, notifier=None) -> SyncResult:
    """Сырьё источника → хранилище. ttable — фрагмент www (direct/push) или
    страница ЭИОС (eios): разбор выбирается по источнику."""
    t0 = _time.monotonic()
    store = store or get_store()
    try:
        new = _parse(ttable, source)
    except ParseError:
        res = SyncResult(False, source, error="not_schedule")
        _log(res, t0)
        return res
    if new and not any(x.group == config.MUIV_GROUP for x in new):
        res = SyncResult(False, source, error="wrong_group")
        _log(res, t0)
        return res
    new = [x for x in new if x.group in (config.MUIV_GROUP, "")]
    today = now.date()
    old = store.lessons()
    if not new and any(x.date > today for x in old):
        res = SyncResult(False, source, error="empty_suspicious")
        _log(res, t0)
        return res

    changes = diff(old, new, today) if store.fetched_at() is not None else []
    store.replace(merge(old, new, today), source=source, now=now,
                  changes=[c.to_dict() for c in changes])
    store.set_meta("ttable_sha", hashlib.sha1(ttable.encode()).hexdigest()[:12])
    if notifier is None:
        from sakura_core.schedule.notify import get_notifier
        notifier = get_notifier()
    notifier.enqueue_changes(changes, now)
    res = SyncResult(True, source, count=len(new), changes=changes)
    _log(res, t0)
    return res


def _log(res: SyncResult, t0: float) -> None:
    log.info(f"[schedule] источник={res.source} ok={res.ok} занятий={res.count} "
             f"изменений={len(res.changes)} ошибка={res.error} за {time_since(t0):.2f} с")


def time_since(t0: float) -> float:
    return _time.monotonic() - t0


# ── автоматические источники: eios (ЭИОС под учёткой Мастера), direct ──

AUTO_SOURCES = ("eios", "direct")


def _fetcher(source: str):
    if source == "eios":
        from sakura_core.schedule.eios import fetch_eios
        return fetch_eios
    from sakura_core.schedule.fetch import fetch_direct
    return fetch_direct


def auto_source() -> str | None:
    """Первый включённый автоматический источник (eios — только с учёткой)."""
    for src in config.SCHEDULE_SOURCES:
        if src == "eios" and config.EIOS_USERNAME and config.EIOS_PASSWORD:
            return src
        if src == "direct":
            return src
    return None


def auto_due(now: datetime, store: ScheduleStore, source: str) -> bool:
    if source not in config.SCHEDULE_SOURCES or now.hour not in config.SCHEDULE_SYNC_HOURS:
        return False
    # джиттер ±20 мин вокруг часа, детерминированный по дате и часу
    slot = f"{now.date().isoformat()}-{now.hour}"
    jitter = int(hashlib.sha1(slot.encode()).hexdigest(), 16) % 40
    if now.minute < jitter:
        return False
    if store.meta(f"{source}_slot") == slot:
        return False
    blocked = store.meta(f"{source}_blocked_at")
    if blocked:
        try:
            if now - datetime.fromisoformat(blocked) < BLOCKED_RETRY:
                return False
        except ValueError:
            pass
    return True


async def sync_auto(source: str, now: datetime, store: ScheduleStore | None = None,
                    fetch=None, notifier=None) -> SyncResult:
    from sakura_core.schedule.eios import AuthError
    from sakura_core.schedule.fetch import Blocked, FetchError
    store = store or get_store()
    fetch = fetch or _fetcher(source)
    async with _lock:
        store.set_meta(f"{source}_slot", f"{now.date().isoformat()}-{now.hour}")
        got = await fetch()
        if isinstance(got, Blocked):
            store.set_meta(f"{source}_blocked_at", now.isoformat(timespec="seconds"))
            log.info(f"[schedule] источник={source} статус=blocked — следующая попытка через 24 ч")
            return SyncResult(False, source, error="blocked")
        if isinstance(got, AuthError):
            if got.reason == "auth":
                if notifier is None:
                    from sakura_core.schedule.notify import get_notifier
                    notifier = get_notifier()
                notifier.enqueue_text(
                    "ЭИОС не пускает меня под твоей учёткой — проверь EIOS_USERNAME и "
                    "EIOS_PASSWORD в .env и перезапусти меня.")
            return SyncResult(False, source, error=got.reason)
        if isinstance(got, FetchError):
            log.info(f"[schedule] источник={source} статус=error причина={got.reason}")
            return SyncResult(False, source, error=got.reason)
        store.set_meta(f"{source}_blocked_at", None)
        return await asyncio.to_thread(ingest, got.ttable, source, now, store, notifier)


def direct_due(now: datetime, store: ScheduleStore) -> bool:
    return auto_due(now, store, "direct")


async def sync_direct(now: datetime, store: ScheduleStore | None = None,
                      fetch=None, notifier=None) -> SyncResult:
    return await sync_auto("direct", now, store, fetch, notifier)


async def loop(clock=datetime.now) -> None:  # наивное локальное время (R10)
    """Фоновая задача schedule (main.py, background). Одна на процесс."""
    from sakura_core.schedule.notify import get_notifier
    await asyncio.sleep(30)
    first = True
    while True:
        now = clock()
        try:
            store = get_store()
            src = auto_source()
            # первый такт после старта — сразу, если данных нет или они устарели
            if src and ((first and query_stale(now, store)) or auto_due(now, store, src)):
                await sync_auto(src, now, store)
            await get_notifier().tick(now)
        except Exception as e:  # noqa: BLE001 — граница фоновой задачи: цикл не должен умирать
            log.warning(f"[schedule] цикл: {type(e).__name__}: {e}")
        first = False
        await asyncio.sleep(60)


def query_stale(now: datetime, store: ScheduleStore) -> bool:
    from sakura_core.schedule.query import is_stale
    return is_stale(now, store)
