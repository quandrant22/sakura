"""WS entrypoint regression: real registry dispatch, mocked external effects."""
import asyncio
import json
from unittest.mock import AsyncMock

import pytest

import adapters.ws as ws
import modules.acks as acks
import modules.calendar_module as calendar
import sakura_core.bridge as bridge
from sakura_core.router import Router


@pytest.mark.parametrize("text, expected", [
    ("покажи ближайшие события", "calendar"),
    ("открой файл README.md", "file"),
])
def test_ws_registry_dispatch(monkeypatch, text, expected):
    device = AsyncMock()
    speak = AsyncMock()
    voice = AsyncMock()
    monkeypatch.setattr(acks, "_pending", {})
    monkeypatch.setattr(acks, "_armed_at", {})
    monkeypatch.setattr(bridge, "_router", Router())
    monkeypatch.setattr(bridge, "_executor", None)
    monkeypatch.setattr(ws.st, "connected_devices", {"test": device})
    monkeypatch.setattr(ws.st, "_current_track", None)
    monkeypatch.setattr(ws, "_im_mark", lambda _: None)
    monkeypatch.setattr(ws, "pending_forget_active", lambda: False)
    monkeypatch.setattr(ws, "stream_tts_to_device", speak)
    monkeypatch.setattr(calendar, "get_upcoming_events", lambda _: [
        {"summary": "Встреча", "date": "17.09", "time": "10:00"},
    ])
    ctx = {
        "ask_gemini": AsyncMock(), "ask_gemini_voice": voice,
        "send_safe": AsyncMock(), "_find_vip_by_name": lambda _: None,
        "_translate_en": AsyncMock(), "_clean_slate": AsyncMock(),
        "_execute_plan": AsyncMock(), "_register_command": lambda *_: "cmd",
        "_get_active_ws": lambda: (device, "test"), "bot": AsyncMock(),
    }
    asyncio.run(ws.handle_voice_command(
        device, {"text": text, "device_id": "test"}, ctx))
    voice.assert_not_awaited()
    sent = [json.loads(c.args[0]) for c in device.send.await_args_list]
    if expected == "calendar":
        # ход закрыт одним tts_end (озвучка замокана — его добирает finally)
        assert sent[-1] == {"type": "tts_end", "device_id": "test"}
        assert [m for m in sent if m.get("type") != "tts_end"] == []
        assert "Встреча" in speak.await_args.args[0]
    else:
        # команда агенту с followup=ack: ход закроет tts_end фразы
        # подтверждения по command_result (modules/acks), не обработчик
        assert sent == [{
            "type": "command", "action": "open_file:README.md", "id": "cmd",
        }]
        assert "cmd" in acks._pending


def test_retired_routers_have_no_production_imports():
    import ast
    from pathlib import Path

    root = Path(__file__).resolve().parents[1]
    retired = {"modules.ws_handlers", "modules.command_router", "modules.intent_classifier"}
    paths = [root / "main.py"]
    for directory in ("adapters", "capabilities", "conversation", "modules", "sakura_core"):
        paths.extend((root / directory).rglob("*.py"))
    for path in paths:
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
            if isinstance(node, ast.ImportFrom):
                assert node.module not in retired, path
                if node.module == "modules":
                    assert not retired.intersection("modules." + a.name for a in node.names), path
            elif isinstance(node, ast.Import):
                assert not retired.intersection(a.name for a in node.names), path
    for module in retired:
        assert not (root / (module.replace(".", "/") + ".py")).exists()

