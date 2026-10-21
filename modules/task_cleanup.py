"""Очистка задач и нитей разговора с резервной копией (scripts/cleanup_tasks.py,
Telegram /забудь_задачи). Пути относительные — от корня проекта (cwd)."""

import json
import os
import shutil
import time

from modules import tasks as tasks_mod

BACKUP_ROOT = "memory/backup"
SNIP = 40


def _threads_rows(open_only: bool = False) -> list[dict]:
    from memory.db import _conn
    from modules import threads
    threads._ensure_table()
    sql = "SELECT * FROM conversation_threads" + (" WHERE closed = 0" if open_only else "")
    return [dict(r) for r in _conn().execute(sql).fetchall()]


def preview() -> dict:
    """Что будет удалено: {tasks: [текст…], threads: [тема…]} — первые 40 символов."""
    tasks = [str(t.get("text", ""))[:SNIP] for t in tasks_mod.load_tasks()]
    threads = [str(r.get("topic", ""))[:SNIP] for r in _threads_rows(open_only=True)]
    return {"tasks": tasks, "threads": threads}


def backup(root: str | None = None) -> str:
    """Копия tasks.json и таблицы conversation_threads в <root>/<дата>/."""
    root = root or BACKUP_ROOT
    day = time.strftime("%Y-%m-%d")
    path = os.path.join(root, day)
    if os.path.exists(path):
        path = os.path.join(root, time.strftime("%Y-%m-%d_%H%M%S"))
    os.makedirs(path, exist_ok=True)
    if os.path.exists(tasks_mod.TASKS_FILE):
        shutil.copy2(tasks_mod.TASKS_FILE, os.path.join(path, "tasks.json"))
    else:
        with open(os.path.join(path, "tasks.json"), "w", encoding="utf-8") as f:
            f.write("[]")
    with open(os.path.join(path, "conversation_threads.json"), "w", encoding="utf-8") as f:
        json.dump(_threads_rows(), f, ensure_ascii=False, indent=2)
    return path


def run(root: str | None = None) -> dict:
    """Резервная копия → очистка tasks.json → закрытие всех открытых нитей."""
    n_tasks = len(tasks_mod.load_tasks())
    n_threads = len(_threads_rows(open_only=True))
    path = backup(root)                      # копия ДО удаления
    tasks_mod.save_tasks([])
    from memory.db import _conn
    conn = _conn()
    conn.execute("UPDATE conversation_threads SET closed = 1 WHERE closed = 0")
    conn.commit()
    return {"tasks": n_tasks, "threads": n_threads, "backup": path}
