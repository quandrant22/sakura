"""Уведомления расписания: напоминание перед первой парой дня, изменения,
устаревшие данные.

- Изменения в ближайшие 48 ч (отмена, перенос, другая аудитория) — сразу.
  Остальные — только в историю: их покажет утренняя сводка.
- Напоминание — за SCHEDULE_REMIND_BEFORE_MIN до первой пары дня, один раз.
- Данные старше SCHEDULE_STALE_DAYS — мягкая просьба обновить, раз в сутки.

Гейты: ночь (23–7) и тишина (созвон, полноэкранная игра) откладывают
доставку, а не отменяют её. Состояние — в meta хранилища, переживает рестарт.
"""
from __future__ import annotations

import logging
from datetime import datetime, timedelta

import config
from sakura_core.schedule import query
from sakura_core.schedule.diff import Change, room_suffix, short_subject
from sakura_core.schedule.store import ScheduleStore, get_store

log = logging.getLogger("sakura.schedule")

URGENT_WINDOW = timedelta(hours=48)
NIGHT_START, NIGHT_END = 23, 7
STALE_NAG_HOUR = 10
URGENT_KINDS = ("removed", "moved", "room_changed", "time_changed", "added")


def _default_quiet() -> bool:
    try:
        from modules.window_watcher import is_quiet_mode
        return is_quiet_mode()
    except (ImportError, OSError, ValueError):
        return False


async def _default_deliver(text: str) -> None:
    from adapters.telegram import send_telegram_text
    from modules.proactive import mark_sent
    from sakura_core.proactive import _reply_proactive
    await send_telegram_text(config.MASTER_ID, text)
    await _reply_proactive(text)
    try:
        mark_sent("schedule", text=text)
    except (OSError, ValueError) as e:
        log.debug(f"[schedule] mark_sent: {type(e).__name__}")


class Notifier:
    def __init__(self, store: ScheduleStore | None = None, deliver=None, quiet=None):
        self._store = store
        self.deliver = deliver or _default_deliver
        self.quiet = quiet or _default_quiet

    @property
    def store(self) -> ScheduleStore:
        return self._store or get_store()

    # ── изменения ──────────────────────────────────────────────────
    def enqueue_changes(self, changes: list[Change], now: datetime) -> None:
        urgent = []
        for c in changes:
            if c.kind not in URGENT_KINDS:
                continue
            soonest = datetime.combine(c.lesson.date, c.lesson.start)
            if c.old is not None:
                soonest = min(soonest, datetime.combine(c.old.date, c.old.start))
            if now <= soonest <= now + URGENT_WINDOW:
                urgent.append(c.text())
        if urgent:
            pending = list(self.store.meta("pending", []) or [])
            self.store.set_meta("pending", (pending + urgent)[-10:])

    # ── такт ───────────────────────────────────────────────────────
    async def tick(self, now: datetime) -> list[str]:
        if now.hour >= NIGHT_START or now.hour < NIGHT_END:
            return []
        if self.quiet():
            return []
        sent: list[str] = []
        for text in (self._pending(), self._reminder(now), self._stale(now)):
            if not text:
                continue
            try:
                await self.deliver(text)
                sent.append(text)
            except Exception as e:  # noqa: BLE001 — сеть/Telegram: любой сбой доставки = попробовать позже
                log.warning(f"[schedule] доставка не удалась: {type(e).__name__}")
                break
        return sent

    def _pending(self) -> str | None:
        pending = self.store.meta("pending", []) or []
        if not pending:
            return None
        self.store.set_meta("pending", [])
        return "Расписание поменялось. " + " ".join(pending)

    def _reminder(self, now: datetime) -> str | None:
        before = config.SCHEDULE_REMIND_BEFORE_MIN
        if before <= 0:
            return None
        today = now.date().isoformat()
        if self.store.meta("reminded") == today:
            return None
        lessons = query.on(now.date(), self.store)
        if not lessons:
            return None
        first = lessons[0]
        start = datetime.combine(first.date, first.start)
        if not (now < start <= now + timedelta(minutes=before)):
            return None
        self.store.set_meta("reminded", today)
        more = len(lessons) - 1
        tail = f" Всего сегодня пар: {len(lessons)}." if more else ""
        return (f"В {first.start:%H:%M} {short_subject(first.subject)}"
                f"{room_suffix(first.room)}.{tail}")

    def _stale(self, now: datetime) -> str | None:
        at = self.store.fetched_at()
        if at is None or not query.is_stale(now, self.store) or now.hour < STALE_NAG_HOUR:
            return None
        today = now.date().isoformat()
        if self.store.meta("stale_nag") == today:
            return None
        self.store.set_meta("stale_nag", today)
        return (f"Расписание у меня от {at:%d.%m}. Открой страницу расписания и нажми "
                f"закладку «Сакура: расписание» — обновлю.")


_notifier: Notifier | None = None


def get_notifier() -> Notifier:
    global _notifier
    if _notifier is None:
        _notifier = Notifier()
    return _notifier
