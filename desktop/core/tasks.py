"""Lifecycle-safe helper for detached agent asyncio tasks."""

import asyncio
import logging
from collections.abc import Coroutine
from typing import Any

log = logging.getLogger("sakura.agent.tasks")
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
    task = asyncio.create_task(coro, name=name)
    _tasks.add(task)
    task.add_done_callback(_task_done)
    return task
