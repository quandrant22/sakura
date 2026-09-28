import asyncio

from sakura_core.tasks import _tasks, spawn


def test_spawn_retains_task_and_logs_unhandled_exception(caplog):
    async def _scenario():
        async def _fail():
            raise RuntimeError("background failure")

        task = spawn(_fail(), name="test-background-failure")
        assert task in _tasks
        await asyncio.gather(task, return_exceptions=True)
        await asyncio.sleep(0)
        assert task not in _tasks

    with caplog.at_level("ERROR", logger="sakura.tasks"):
        asyncio.run(_scenario())

    assert "test-background-failure failed" in caplog.text
    assert "background failure" in caplog.text