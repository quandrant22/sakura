"""Lifecycle-safe helpers for fire-and-forget asyncio tasks."""

import asyncio
import logging
from collections.abc import Coroutine
from typing import Any

log = logging.getLogger("sakura.tasks")
_tasks: set[asyncio.Task] = set()


def _task_done(task: asyncio.Task) -> None:
    _tasks.discard(task)
    if task.cancelled():
        return
    error = task.exception()
    if error is not None:
        log.error(
            "Background task %s failed",
            task.get_name(),
            exc_info=(type(error), error, error.__traceback__),
        )


def spawn(coro: Coroutine[Any, Any, Any], name: str | None = None) -> asyncio.Task:
    """Keep a strong reference to a background task and report its failure."""
    task = asyncio.create_task(coro, name=name)
    _tasks.add(task)
    task.add_done_callback(_task_done)
    return task


async def cancel_all(timeout: float = 5.0) -> set[asyncio.Task]:
    """Cancel tracked background tasks and return those still pending at timeout."""
    tasks = tuple(_tasks)
    for task in tasks:
        task.cancel()
    if not tasks:
        return set()
    _done, pending = await asyncio.wait(tasks, timeout=max(0.0, timeout))
    return pending
