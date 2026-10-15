"""Хронометраж голосового хода: строка [turn] и p50/p90 раз в час.

Отметки — миллисекунды от приёма запроса (voice_turns.start), каждая
ставится один раз за ход:

  verdict       вердикт роутера (команда / разговор)
  first_token   первый токен ответа LLM
  stage1_start  старт синтеза первой стадии
  first_audio   первый аудиопакет ушёл на устройство
  llm_done      стрим LLM закончен
  tts_end       ход закрыт (tts_end)

По завершении хода (обработчик вернулся и tts_end ушёл) — одна строка:
  [turn] 9f2c41d0a7b3 dev=mostech kind=conversation verdict=870
         first_token=730 stage1_start=750 first_audio=1350 llm_done=830
         tts_end=5340 мс
Раз в TURN_STATS_PERIOD_S — сводка по видам ходов:
  [turn] за 60 мин: conversation n=14 first_audio p50=1420 p90=2310 …
"""

from __future__ import annotations

import asyncio
import logging
import statistics
import time
from collections import defaultdict

import config

log = logging.getLogger("sakura.turn")

STAGES = ("verdict", "first_token", "stage1_start", "first_audio", "llm_done", "tts_end")
# Ход не закрылся tts_end (устройство пропало) — строка всё равно через столько.
REPORT_FALLBACK_S = 30.0

_samples: list[tuple[str, dict[str, float]]] = []
_summary_task: asyncio.Task | None = None


def _cur():
    from sakura_core import voice_turns
    return voice_turns.current()


def mark(name: str, turn=None) -> None:
    """Отметить этап хода (первая отметка этапа выигрывает)."""
    t = turn if turn is not None else _cur()
    if t is None or name in t.marks:
        return
    t.marks[name] = (time.monotonic() - t.t_recv) * 1000.0


def set_kind(kind: str, turn=None) -> None:
    t = turn if turn is not None else _cur()
    if t is not None:
        t.kind = kind


def flag(name: str, turn=None) -> None:
    """Пометка хода в строке [turn] (early_gate, verdict_after_audio …)."""
    t = turn if turn is not None else _cur()
    if t is not None and name not in t.flags:
        t.flags.append(name)


def line(t) -> str:
    stages = " ".join(f"{k}={t.marks[k]:.0f}" for k in STAGES if k in t.marks)
    extra = "".join(f" {f}" for f in t.flags)
    if t.cancelled:
        extra += " cancelled"
    return (f"[turn] {t.turn_id} dev={t.device_id} kind={t.kind}"
            f"{extra} {stages or '—'} мс")


def maybe_report(t, force: bool = False) -> None:
    """Строка [turn], когда ход завершён и закрыт (или force)."""
    if t.reported or not t.done:
        return
    if not force and not (t.ended or t.cancelled):
        return
    t.reported = True
    log.info(line(t))
    if not t.cancelled:
        _samples.append((t.kind, dict(t.marks)))
    _ensure_summary()


def on_done(t) -> None:
    """Обработчик хода вернулся."""
    maybe_report(t)
    if not t.reported:
        try:
            asyncio.get_running_loop().call_later(
                REPORT_FALLBACK_S, maybe_report, t, True)
        except RuntimeError:
            maybe_report(t, force=True)


def _pct(values: list[float], p: float) -> float:
    v = sorted(values)
    return v[min(len(v) - 1, int(round(p * (len(v) - 1))))]


def summary(samples=None) -> list[str]:
    """Сводка p50/p90 по видам ходов и этапам."""
    samples = _samples if samples is None else samples
    by_kind: dict[str, dict[str, list[float]]] = defaultdict(lambda: defaultdict(list))
    for kind, marks in samples:
        for k, v in marks.items():
            by_kind[kind][k].append(v)
    out = []
    for kind in sorted(by_kind):
        stages = by_kind[kind]
        n = max(len(v) for v in stages.values())
        parts = [f"{k} p50={statistics.median(stages[k]):.0f} p90={_pct(stages[k], 0.9):.0f}"
                 for k in STAGES if stages.get(k)]
        out.append(f"{kind} n={n} " + " | ".join(parts))
    return out


async def _summary_loop() -> None:
    period = config.TURN_STATS_PERIOD_S
    while True:
        await asyncio.sleep(period)
        if not _samples:
            continue
        for s in summary():
            log.info(f"[turn] за {period / 60:.0f} мин: {s}")
        _samples.clear()


def _ensure_summary() -> None:
    global _summary_task
    if _summary_task is not None and not _summary_task.done():
        return
    try:
        from sakura_core.tasks import spawn
        _summary_task = spawn(_summary_loop(), name="turn-stats")
    except RuntimeError:
        pass
