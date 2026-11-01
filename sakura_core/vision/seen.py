"""seen — что Сакура видела на экране недавно.

Пишется и при разовом вопросе, и при взгляде (даже если она промолчала):
«что ты видела?» получает правду, а не догадку. Живёт в памяти процесса
SEEN_TTL_S; описание короткое (≤ 200 симв), сам кадр не хранится.
"""

from __future__ import annotations

import time
from dataclasses import dataclass

import config

SAW_MAX = 200


@dataclass(frozen=True)
class Seen:
    device_id: str
    title: str
    saw: str
    purpose: str
    at: float          # time.monotonic()
    subject: str = ""  # название игры/программы на экране (для продолжения разговора)


_last: Seen | None = None


def record(device_id: str, title: str, saw: str, purpose: str, *, now: float | None = None,
           subject: str = "") -> None:
    global _last
    saw = " ".join((saw or "").split())
    if not saw:
        return
    if len(saw) > SAW_MAX:
        saw = saw[:SAW_MAX].rstrip() + "…"
    _last = Seen(device_id, (title or "")[:200], saw, purpose,
                 time.monotonic() if now is None else now, (subject or "")[:80])


def latest(*, now: float | None = None) -> Seen | None:
    if _last is None:
        return None
    now = time.monotonic() if now is None else now
    if now - _last.at > config.SEEN_TTL_S:
        return None
    return _last


def context_line(*, now: float | None = None) -> str:
    """Строка для системного промпта или пусто."""
    s = latest(now=now)
    if s is None:
        return ""
    now = time.monotonic() if now is None else now
    minutes = max(0, int((now - s.at) // 60))
    when = "только что" if minutes < 1 else f"{minutes} мин назад"
    how = "Мастер просил посмотреть" if s.purpose == "ask" else "ты сама глянула"
    window = f" (окно «{s.title}»)" if s.title else ""
    return f"[Экран Мастера {when}{window}, {how}: {s.saw}]"


def reset() -> None:
    global _last
    _last = None
