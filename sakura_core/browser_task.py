"""BrowserTask — состояние задачи browser agent на сервере (S5).

Расширение и desktop состояния задачи не держат: цель, журнал шагов,
сжатая сводка, ответы теста, лимиты — здесь. После каждого шага —
чекпоинт data/browser_tasks/<task_id>.json БЕЗ кадров и текста страниц:
журнал хранит только tool, status и note шага; рассуждения решателя и
тексты вопросов живут только в памяти процесса. Кадры — в deque размером
BROWSER_FRAMES_IN_CONTEXT; выпавший кадр заменяется в журнале своей note.

Переподключение desktop: задача продолжается со следующего browser_step
(по task_id — из памяти или из чекпоинта). Одна активная задача на окно
агента: новая задача в том же окне отменяет прежнюю (browser_step.py).
"""

from __future__ import annotations

import json
import logging
import os
import time
import uuid
from collections import deque
from dataclasses import dataclass, field
from pathlib import Path

import config

log = logging.getLogger("sakura.browser_task")

TASKS_DIR = Path("data") / "browser_tasks"
ACTIVE = ("running", "paused")
STATES = ("running", "paused", "done", "fail", "cancelled")
NOTE_MAX = 200

# Поля чекпоинта: всё, что нужно для продолжения, и ничего со страницы.
_PERSISTED = ("task_id", "goal", "start_url", "device_id", "window_id", "tab_id",
              "steps", "notes", "summary", "summarized_upto", "answers", "started_at",
              "tokens_used", "state", "step", "pause_kind", "pause_reason", "resume_at",
              "last_note", "last_url", "stale_streak", "form_retries", "finished_at",
              "paused_s", "paused_since", "metrics")


@dataclass
class Frame:
    """Кадр шага: только в памяти, только до завершения задачи."""

    step: int
    frame_id: str
    kind: str                      # page | question
    data: bytes = field(repr=False)
    q_index: int | None = None
    mime: str = "image/jpeg"


@dataclass
class BrowserTask:
    task_id: str
    goal: str
    start_url: str = ""
    device_id: str = ""
    window_id: str | None = None
    tab_id: str | None = None
    steps: list = field(default_factory=list)     # [{n, tool, status, note}]
    notes: dict = field(default_factory=dict)     # шаг выпавшего кадра → его note
    frames: deque = field(default_factory=lambda: deque(
        maxlen=max(1, config.BROWSER_FRAMES_IN_CONTEXT)))
    summary: str = ""
    summarized_upto: int = 0                      # шаги ≤ этого — уже в summary
    answers: list = field(default_factory=list)   # [{index, kind, answer, status}]
    started_at: float = field(default_factory=time.time)
    tokens_used: int = 0
    state: str = "running"
    step: int = 0
    pause_kind: str = ""                          # captcha | quota | confirm
    pause_reason: str = ""
    resume_at: float | None = None
    last_note: str = ""
    last_url: str = ""
    stale_streak: int = 0
    form_retries: dict = field(default_factory=dict)
    finished_at: float | None = None
    paused_s: float = 0.0                         # сколько задача простояла на паузах
    paused_since: float | None = None
    # Метрики (только числа): вызовы по роли:модели, ошибки по коду, ожидание
    # лимитера, задержки удачных вызовов (browser_step.record_event).
    metrics: dict = field(default_factory=lambda: {"calls": {}, "errors": {},
                                                    "wait_s": 0.0, "lat": []})
    # ── только в памяти ──
    ws: object = field(default=None, repr=False)
    reasoning: dict = field(default_factory=dict, repr=False)   # index → рассуждение решателя
    quiz: dict = field(default_factory=dict, repr=False)        # очередь вопросов (тексты)
    held_action: dict | None = field(default=None, repr=False)  # ждёт подтверждения
    pending: dict = field(default_factory=dict, repr=False)     # служебные ожидания шага
    progress_at: float = 0.0
    progress_msg: object = field(default=None, repr=False)

    # ── журнал и кадры ────────────────────────────────────────────

    @property
    def active(self) -> bool:
        return self.state in ACTIVE

    def active_seconds(self, now: float | None = None) -> float:
        """Время работы без пауз (лимит BROWSER_MAX_SECONDS)."""
        now = time.time() if now is None else now
        paused = self.paused_s + (now - self.paused_since if self.paused_since else 0.0)
        return max(0.0, now - self.started_at - paused)

    def add_frame(self, frame: Frame) -> None:
        """Положить кадр; выпавший из окна заменяется в журнале своей note."""
        if len(self.frames) == self.frames.maxlen:
            old = self.frames[0]
            self.notes[str(old.step)] = self.note_of(old.step) or f"кадр шага {old.step}"
        self.frames.append(frame)

    def note_of(self, step: int) -> str:
        for s in reversed(self.steps):
            if s.get("n") == step:
                return s.get("note") or ""
        return ""

    def record(self, tool: str, note: str, status: str = "sent") -> dict:
        entry = {"n": self.step, "tool": tool, "status": status, "note": note[:NOTE_MAX]}
        self.steps.append(entry)
        self.last_note = entry["note"]
        return entry

    def set_last_status(self, status: str) -> None:
        if self.steps and self.steps[-1].get("status") == "sent":
            self.steps[-1]["status"] = status

    def journal(self) -> list[dict]:
        """Шаги после сводки (то, что ещё не сжато)."""
        return [s for s in self.steps if s.get("n", 0) > self.summarized_upto]

    def drop_frames(self) -> None:
        self.frames.clear()
        self.quiz.clear()
        self.reasoning.clear()
        self.held_action = None

    # ── чекпоинт ──────────────────────────────────────────────────

    def to_checkpoint(self) -> dict:
        return {k: getattr(self, k) for k in _PERSISTED}

    @classmethod
    def from_checkpoint(cls, raw: dict) -> BrowserTask:
        kw = {k: raw[k] for k in _PERSISTED if k in raw}
        if kw.get("state") not in STATES:
            kw["state"] = "fail"
        return cls(**kw)


_tasks: dict[str, BrowserTask] = {}


def _path(task_id: str) -> Path:
    return TASKS_DIR / f"{task_id}.json"


def _valid_id(task_id) -> bool:
    return isinstance(task_id, str) and 0 < len(task_id) <= 64 \
        and all(c.isalnum() or c in "-_" for c in task_id)


def checkpoint(task: BrowserTask) -> None:
    """Записать чекпоинт атомарно; ошибка записи — в лог, задача идёт дальше."""
    try:
        TASKS_DIR.mkdir(parents=True, exist_ok=True)
        path = _path(task.task_id)
        tmp = path.with_suffix(".tmp")
        tmp.write_text(json.dumps(task.to_checkpoint(), ensure_ascii=False), encoding="utf-8")
        os.replace(tmp, path)
    except OSError as e:
        log.warning(f"[browser] {task.task_id}: чекпоинт не записан ({type(e).__name__})")


def new_task(goal: str, device_id: str = "", start_url: str = "") -> BrowserTask:
    task = BrowserTask(task_id=uuid.uuid4().hex[:16], goal=goal.strip(),
                       start_url=start_url or "", device_id=device_id or "")
    _tasks[task.task_id] = task
    checkpoint(task)
    return task


def get(task_id) -> BrowserTask | None:
    """Задача из памяти, иначе из чекпоинта (рестарт сервера)."""
    if not _valid_id(task_id):
        return None
    task = _tasks.get(task_id)
    if task is not None:
        return task
    try:
        raw = json.loads(_path(task_id).read_text(encoding="utf-8"))
    except FileNotFoundError:
        return None
    except (OSError, ValueError) as e:
        log.warning(f"[browser] {task_id}: чекпоинт не прочитан ({type(e).__name__})")
        return None
    task = BrowserTask.from_checkpoint(raw)
    _tasks[task.task_id] = task
    log.info(f"[browser] {task_id}: восстановлена из чекпоинта, шаг {task.step}, {task.state}")
    return task


def active_tasks() -> list[BrowserTask]:
    return [t for t in _tasks.values() if t.active]


def same_window(task: BrowserTask) -> list[BrowserTask]:
    """Другие активные задачи того же окна агента того же устройства."""
    if task.window_id is None:
        return []
    return [t for t in active_tasks() if t is not task
            and t.device_id == task.device_id and t.window_id == task.window_id]


def finish(task: BrowserTask, state: str) -> None:
    """Терминальное состояние: кадры и тексты вопросов отпускаются, файл удаляется."""
    task.state = state
    task.finished_at = time.time()
    task.drop_frames()
    try:
        _path(task.task_id).unlink(missing_ok=True)
    except OSError as e:
        log.warning(f"[browser] {task.task_id}: чекпоинт не удалён ({type(e).__name__})")


def load_all() -> list[BrowserTask]:
    """Поднять активные задачи из чекпоинтов (на старте или в тестах)."""
    loaded = []
    for path in sorted(TASKS_DIR.glob("*.json")) if TASKS_DIR.exists() else ():
        task = get(path.stem)
        if task is not None and task.active:
            loaded.append(task)
    return loaded


def reset() -> None:
    """Для тестов: забыть задачи в памяти."""
    _tasks.clear()
