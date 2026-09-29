import json
import sys
from pathlib import Path

import pytest

AGENT_ROOT = Path(__file__).resolve().parents[1]
if str(AGENT_ROOT) not in sys.path:
    sys.path.insert(0, str(AGENT_ROOT))

from core.commands import CommandRegistry, load_builtin_commands
from core.protocol import (
    Capabilities,
    Command,
    Ping,
    Registered,
    Reply,
    VoiceCommand,
    parse_action,
    parse_event,
    parse_message,
)


def test_protocol_events_serialize_and_parse():
    registration = Registered(
        device_id="test-pc",
        active_window="Chrome",
        system_info={"cpu": 45, "ram": 60},
        capabilities=["voice", "tts", "browser"],
    )
    payload = json.loads(registration.to_json())

    assert payload["type"] == "register"
    assert payload["device_id"] == "test-pc"
    assert payload["system_info"] == {"cpu": 45, "ram": 60}
    assert isinstance(parse_event(payload), Registered)

    ping = parse_message(Ping(device_id="test-pc").to_json())
    assert isinstance(ping, Ping)


@pytest.mark.parametrize(
    ("message", "expected_type"),
    [
        ({"type": "voice_command", "device_id": "test-pc", "text": "открой браузер"}, VoiceCommand),
        ({"type": "command", "target": "volume", "args": "50"}, Command),
        ({"type": "reply", "text": "Привет, Мастер!"}, Reply),
    ],
)
def test_protocol_parses_typed_messages(message, expected_type):
    parsed = parse_message(json.dumps(message, ensure_ascii=False))

    assert isinstance(parsed, expected_type)


def test_protocol_rejects_unknown_messages():
    assert parse_event({"type": "unknown"}) is None
    assert parse_action({"type": "unknown"}) is None
    assert parse_message("not-json") is None
    assert isinstance(Capabilities.detect(), list)


@pytest.fixture
def builtins_registry():
    registry = CommandRegistry()
    load_builtin_commands(registry)
    return registry


@pytest.mark.parametrize(
    ("text", "expected_id"),
    [
        ("открой браузер", "open_browser"),
        ("громче", "volume_up"),
        ("тише", "volume_down"),
        ("скриншот", "screenshot"),
        ("новая вкладка", "browser_tab_new"),
        ("пауза", "music_play_pause"),
        ("следующий трек", "music_next"),
        ("заблокируй", "system_lock"),
        ("спящий режим", "system_sleep"),
    ],
)
def test_builtin_voice_commands_match_expected_ids(builtins_registry, text, expected_id):
    result = builtins_registry.match(text)

    assert result is not None, f"no match for {text!r}"
    assert result.command.id == expected_id
    assert result.confidence > 0