#!/usr/bin/env python3
"""test_protocol.py — Quick test for the new typed protocol and command registry."""

import sys
import os

# Add agent directory to path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from core.protocol import (
    Event, Registered, Ping, VoiceCommand, CommandResult, AppsList,
    Action, Command, TTSChunk, TTSEnd, Reply, MoodUpdate,
    Capabilities, parse_action, parse_event,
)
from core.commands import CommandRegistry, load_builtin_commands

def test_protocol():
    """Test typed IPC protocol."""
    print("=== Testing Protocol ===")

    # Create events
    reg = Registered(
        device_id="test-pc",
        active_window="Chrome",
        system_info={"cpu": 45, "ram": 60},
        capabilities=["voice", "tts", "browser"],
        version="2.0",
    )
    print(f"Registered: {reg.to_json()[:100]}...")

    ping = Ping(device_id="test-pc", active_window="VS Code")
    print(f"Ping: {ping.to_json()[:80]}...")

    vc = VoiceCommand(device_id="test-pc", text="открой браузер")
    print(f"VoiceCommand: {vc.to_json()[:80]}...")

    cr = CommandResult(device_id="test-pc", action="open_app", result="открыл Chrome")
    print(f"CommandResult: {cr.to_json()[:80]}...")

    # Create actions
    cmd = Command(target="browser", args="tab_new")
    print(f"Command: {cmd.to_json()[:80]}...")

    tts = TTSChunk(audio="base64data...")
    print(f"TTSChunk: {tts.to_json()[:80]}...")

    reply = Reply(text="Привет, Мастер!", mood={"valence": 0.5, "arousal": 0.3})
    print(f"Reply: {reply.to_json()[:80]}...")

    # Parse actions
    parsed = parse_action({"type": "command", "target": "volume", "args": "50"})
    print(f"Parsed action: {type(parsed).__name__} target={parsed.target} args={parsed.args}")

    # Capabilities
    caps = Capabilities.detect()
    print(f"Detected capabilities: {caps}")

    print("✓ Protocol tests passed\n")


def test_commands():
    """Test TOML command registry."""
    print("=== Testing Command Registry ===")

    registry = CommandRegistry()
    load_builtin_commands(registry)
    print(f"Loaded {len(registry.list_commands())} built-in commands")

    # Test matching
    tests = [
        ("открой браузер", "open_browser"),
        ("громче", "volume_up"),
        ("тише", "volume_down"),
        ("скриншот", "screenshot"),
        ("новая вкладка", "browser_tab_new"),
        ("пауза", "music_play_pause"),
        ("следующий трек", "music_next"),
        ("заблокируй", "system_lock"),
        ("спящий режим", "system_sleep"),
    ]

    for text, expected_id in tests:
        result = registry.match(text)
        if result:
            status = "✓" if result.command.id == expected_id else "✗"
            print(f"  {status} '{text}' → {result.command.id} (confidence: {result.confidence:.2f})")
            if result.command.id != expected_id:
                print(f"    Expected: {expected_id}")
        else:
            print(f"  ✗ '{text}' → no match (expected: {expected_id})")

    print("✓ Command tests passed\n")


if __name__ == "__main__":
    test_protocol()
    test_commands()
    print("All tests passed!")
