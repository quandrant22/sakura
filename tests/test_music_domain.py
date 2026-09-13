"""Тесты этапа 3: исполнитель и домен музыки.

Run: python -m pytest tests/test_music_domain.py -q
"""

import asyncio
import json

from capabilities import music as cap_music
from sakura_core.bridge import resolve_context
from sakura_core.executor import (
    AgentCommand,
    ExecutionContext,
    Executor,
    get_handler,
    registered,
)
from sakura_core.registry import load


def _run(coro):
    """Запуск корутины тем же паттерном, что и весь репозиторий
    (asyncio.get_event_loop().run_until_complete): asyncio.run() и
    set_event_loop(None) ломают легаси-тесты на закрытом/снятом цикле."""
    return asyncio.get_event_loop().run_until_complete(coro)


def test_all_18_music_actions_registered():
    music_ids = {
        d.id for d in load()
        if d.id.startswith("music.") and not d.id.startswith("music_stats")
    }
    assert len(music_ids) == 18
    missing = music_ids - set(registered())
    assert not missing, f"нет хендлеров: {missing}"
    # все хендлеры отдают каноническую команду агенту
    for aid in music_ids:
        handler = get_handler(aid)
    assert (handler(ExecutionContext()) if callable(handler) else handler) == AgentCommand(aid)


def test_executor_sends_canonical_id_on_wire():
    sent = {}

    class FakeWS:
        async def send(self, raw):
            sent["msg"] = json.loads(raw)

    ids = []

    def register(action, device_id):
        ids.append(action)
        return f"id-{len(ids)}"

    ex = Executor()
    cmd_id = _run(ex.execute(
        "music.next",
        ExecutionContext(device_ws=FakeWS(), device_id="laptop",
                         register_command=register),
    ))
    assert sent["msg"] == {
        "type": "command", "action": "music.next", "id": "id-1",
    }
    assert cmd_id == "id-1"
    assert ids == ["music.next"]


def test_executor_no_handler_raises():
    ex = Executor()
    try:
        _run(ex.execute("no.such.action", ExecutionContext()))
    except RuntimeError as e:
        assert "no.such.action" in str(e)
    else:
        raise AssertionError("ожидался RuntimeError")


def test_duplicate_handler_registration_raises():
    from sakura_core.executor import register_table
    try:
        register_table({"music.next": lambda ctx: AgentCommand("music.next")})
    except RuntimeError:
        pass
    else:
        raise AssertionError("ожидался RuntimeError на дубле")


def test_resolve_context_priority():
    # играющая музыка приоритетнее окна: домен этапа 3 — музыка
    assert resolve_context("Google Chrome", {"title": "трек"}) == "playing:music"
    assert resolve_context("YouTube — канал", None) == "window:youtube"
    assert resolve_context("Google Chrome", None) == "window:browser"
    assert resolve_context("Проводник", None) is None
    assert resolve_context("", None) is None
