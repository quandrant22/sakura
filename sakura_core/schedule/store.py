"""Хранилище расписания: memory/muiv_schedule.json (атомарно, modules/jsonio).

Сайт показывает только будущее (≈2 недели), поэтому выгрузка — не полная
замена: прошлые дни храним 30 суток («что было вчера»), дни после горизонта
новой выгрузки не трогаем. Внутри горизонта (завтра … последний день новой
выгрузки) новая выгрузка авторитетна. Сегодня — объединение по uid: прошедшая
пара могла исчезнуть с сайта, а это не отмена.
"""
from __future__ import annotations

import json
import logging
import os
from dataclasses import asdict
from datetime import date, datetime, time, timedelta

import config
from modules.jsonio import save_json
from sakura_core.schedule.parse import Lesson

log = logging.getLogger("sakura.schedule")

KEEP_PAST_DAYS = 30
HISTORY_MAX = 50
VERSION = 1


def lesson_to_dict(x: Lesson) -> dict:
    d = asdict(x)
    d["date"] = x.date.isoformat()
    d["start"] = x.start.strftime("%H:%M")
    d["end"] = x.end.strftime("%H:%M")
    return d


def lesson_from_dict(d: dict) -> Lesson:
    return Lesson(
        date=date.fromisoformat(d["date"]),
        start=time.fromisoformat(d["start"]), end=time.fromisoformat(d["end"]),
        group=d.get("group", ""), subject=d.get("subject", ""), room=d.get("room", ""),
        kind=d.get("kind", "other"), kind_raw=d.get("kind_raw", ""), teacher=d.get("teacher", ""),
        department=d.get("department", ""),
    )


def _sort(lessons) -> list[Lesson]:
    return sorted(lessons, key=lambda x: (x.date, x.start, x.subject))


def merge(old: list[Lesson], new: list[Lesson], today: date) -> list[Lesson]:
    """Слияние по правилам модуля (см. docstring)."""
    keep_from = today - timedelta(days=KEEP_PAST_DAYS)
    horizon = max((x.date for x in new), default=today)
    out: dict[str, Lesson] = {}
    for x in old:
        if x.date < keep_from:
            continue
        if x.date < today or x.date == today or x.date > horizon:
            out[x.uid] = x
    for x in new:
        if x.date >= today:          # прошлое с сайта не берём: оно уже наше
            out[x.uid] = x
    return _sort(out.values())


class ScheduleStore:
    def __init__(self, path: str | None = None):
        self.path = path or config.SCHEDULE_PATH
        self._data: dict | None = None

    # ── сырьё ──────────────────────────────────────────────────────
    def _load(self) -> dict:
        if self._data is None:
            data: dict = {}
            if os.path.exists(self.path):
                try:
                    with open(self.path, encoding="utf-8") as f:
                        data = json.load(f)
                except (OSError, ValueError) as e:
                    log.warning(f"[schedule] хранилище не прочитано: {type(e).__name__}")
            data.setdefault("version", VERSION)
            data.setdefault("lessons", [])
            data.setdefault("history", [])
            data.setdefault("meta", {})
            self._data = data
        return self._data

    def _save(self) -> None:
        save_json(self.path, self._load())

    def reload(self) -> None:
        self._data = None

    # ── чтение ─────────────────────────────────────────────────────
    def lessons(self) -> list[Lesson]:
        out = []
        for d in self._load()["lessons"]:
            try:
                out.append(lesson_from_dict(d))
            except (KeyError, ValueError):
                continue
        return out

    def fetched_at(self) -> datetime | None:
        raw = self._load().get("fetched_at")
        try:
            return datetime.fromisoformat(raw) if raw else None
        except ValueError:
            return None

    def source(self) -> str | None:
        return self._load().get("source")

    def history(self) -> list[dict]:
        return list(self._load()["history"])

    def meta(self, key: str, default=None):
        return self._load()["meta"].get(key, default)

    # ── запись ─────────────────────────────────────────────────────
    def set_meta(self, key: str, value) -> None:
        self._load()["meta"][key] = value
        self._save()

    def replace(self, lessons: list[Lesson], *, source: str, now: datetime,
                changes: list[dict]) -> None:
        data = self._load()
        data["group"] = config.MUIV_GROUP
        data["source"] = source
        data["fetched_at"] = now.isoformat(timespec="seconds")
        data["horizon_to"] = max((x.date for x in lessons), default=now.date()).isoformat()
        data["lessons"] = [lesson_to_dict(x) for x in lessons]
        if changes:
            data["history"] = (data["history"] + [
                {"at": now.isoformat(timespec="seconds"), "changes": changes}])[-HISTORY_MAX:]
        self._save()


_store: ScheduleStore | None = None


def get_store() -> ScheduleStore:
    global _store
    if _store is None or _store.path != config.SCHEDULE_PATH:
        _store = ScheduleStore()
    return _store
