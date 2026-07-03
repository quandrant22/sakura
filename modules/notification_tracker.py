"""
modules/notification_tracker.py — Трекер уведомлений.

Агент присылает уведомления с ПК (Telegram Desktop, Discord, Windows).
Сервер анализирует важность и решает — предупредить ли голосом.
"""

import json
import logging
import os
import time
from typing import Optional

log = logging.getLogger("sakura.notifications")

NOTIFICATIONS_FILE = "memory/notifications.json"
_MAX_STORED = 50

# Ключевые слова важных уведомлений
_URGENT_KEYWORDS = [
    "срочно", "важно", "дедлайн", "дедлайн", "deadline",
    "термин", "звонок", "встреча", "начало через",
    "оплата", "подписка", "подтверд", "верификация",
]

# Ключевые слова спама
_SPAM_KEYWORDS = [
    "подписыв", "акция", "скидк", "промо", "реклам",
    "рассылка", "новости от", "подборк", "рекоменду",
]


class Notification:
    def __init__(self, source: str, title: str, body: str,
                 urgent: bool = False, timestamp: float = None):
        self.source = source          # "telegram", "discord", "windows"
        self.title = title
        self.body = body
        self.urgent = urgent
        self.timestamp = timestamp or time.time()
        self.shown = False

    def to_dict(self) -> dict:
        return {
            "source": self.source,
            "title": self.title,
            "body": self.body,
            "urgent": self.urgent,
            "timestamp": self.timestamp,
            "shown": self.shown,
        }

    @classmethod
    def from_dict(cls, d: dict) -> "Notification":
        n = cls(
            source=d.get("source", ""),
            title=d.get("title", ""),
            body=d.get("body", ""),
            urgent=d.get("urgent", False),
            timestamp=d.get("timestamp", 0),
        )
        n.shown = d.get("shown", False)
        return n

    def __repr__(self):
        return f"Notification({self.source}: {self.title[:30]})"


def _load() -> list[dict]:
    if os.path.exists(NOTIFICATIONS_FILE):
        with open(NOTIFICATIONS_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    return []


def _save(data: list[dict]):
    os.makedirs(os.path.dirname(NOTIFICATIONS_FILE), exist_ok=True)
    with open(NOTIFICATIONS_FILE, "w", encoding="utf-8") as f:
        json.dump(data[-_MAX_STORED:], f, ensure_ascii=False, indent=2)


def _classify_urgency(title: str, body: str) -> bool:
    """Определяет важность уведомления по содержимому."""
    text = (title + " " + body).lower()
    if any(kw in text for kw in _URGENT_KEYWORDS):
        return True
    if any(kw in text for kw in _SPAM_KEYWORDS):
        return False
    return False


def add_notification(source: str, title: str, body: str) -> Optional[Notification]:
    """
    Добавляет уведомление от агента.
    Возвращает Notification если нужно показать, None если пропустить.
    """
    urgent = _classify_urgency(title, body)
    notif = Notification(source=source, title=title, body=body, urgent=urgent)

    data = _load()
    data.append(notif.to_dict())
    _save(data)

    log.info(f"[notif] {source}: {title[:40]} (urgent={urgent})")
    return notif


def get_unshown() -> list[Notification]:
    """Возвращает не показанные уведомления."""
    data = _load()
    result = []
    for d in data:
        if not d.get("shown"):
            result.append(Notification.from_dict(d))
    return result


def mark_shown(timestamp: float):
    """Помечает уведомление как показанное."""
    data = _load()
    for d in data:
        if abs(d.get("timestamp", 0) - timestamp) < 1:
            d["shown"] = True
    _save(data)


def get_recent_summary(hours: float = 2) -> str:
    """Краткая сводка за последние N часов."""
    cutoff = time.time() - hours * 3600
    data = _load()
    recent = [d for d in data if d.get("timestamp", 0) > cutoff]
    if not recent:
        return ""

    by_source = {}
    for d in recent:
        src = d.get("source", "unknown")
        by_source.setdefault(src, []).append(d)

    lines = []
    for src, items in by_source.items():
        urgent_count = sum(1 for i in items if i.get("urgent"))
        total = len(items)
        lines.append(f"  {src}: {total} шт" + (f" ({urgent_count} важных)" if urgent_count else ""))

    return "Уведомления за последние часы:\n" + "\n".join(lines)


def get_urgent_pending() -> list[Notification]:
    """Возвращает срочные непрочитанные уведомления."""
    return [n for n in get_unshown() if n.urgent]
