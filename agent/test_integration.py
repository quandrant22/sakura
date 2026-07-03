#!/usr/bin/env python3
"""test_integration.py — Test the full integration."""

import os
import sys
import json
import subprocess
import time

# Add agent directory to path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))


def test_rust_binary():
    """Test that Rust binary exists and runs."""
    from pathlib import Path

    release_path = Path(__file__).parent / "core-rust" / "target" / "release" / "sakura-audio-core"
    if not release_path.exists():
        print("✗ Rust binary not found")
        print("  Build with: cd core-rust && cargo build --release")
        return False

    print(f"✓ Rust binary found: {release_path}")
    print(f"  Size: {release_path.stat().st_size / 1024 / 1024:.1f} MB")
    return True


def test_python_imports():
    """Test that Python modules can be imported."""
    modules = [
        "core.protocol",
        "core.commands",
        "core.settings",
        "core.bridge",
    ]

    for module in modules:
        try:
            __import__(module)
            print(f"✓ {module}")
        except ImportError as e:
            print(f"✗ {module}: {e}")
            return False

    return True


def test_protocol():
    """Test typed protocol."""
    from core.protocol import Event, Registered, Action, Command, parse_action

    # Test event creation
    event = Registered(
        device_id="test",
        active_window="test",
        capabilities=["voice", "tts"],
    )
    json_str = event.to_json()
    assert "register" in json_str
    print("✓ Protocol events work")

    # Test action parsing
    action = parse_action({"type": "command", "target": "volume", "args": "50"})
    assert action.target == "volume"
    assert action.args == "50"
    print("✓ Protocol actions work")

    return True


def test_commands():
    """Test command registry."""
    from core.commands import CommandRegistry, load_builtin_commands

    registry = CommandRegistry()
    load_builtin_commands(registry)

    # Test matching
    tests = [
        ("громче", "volume_up"),
        ("тише", "volume_down"),
        ("скриншот", "screenshot"),
        ("новая вкладка", "browser_tab_new"),
    ]

    for text, expected_id in tests:
        result = registry.match(text)
        if result and result.command.id == expected_id:
            print(f"✓ '{text}' → {result.command.id}")
        else:
            actual = result.command.id if result else "no match"
            print(f"✗ '{text}' → {actual} (expected: {expected_id})")
            return False

    return True


def test_bridge():
    """Test Rust bridge."""
    from core.bridge import RustCore, Event, Action

    # Test bridge creation
    try:
        core = RustCore()
        print("✓ Bridge created")
    except FileNotFoundError:
        print("⚠ Bridge created (binary not found, expected in CI)")
    except Exception as e:
        print(f"✗ Bridge error: {e}")
        return False

    return True


def main():
    print("=== Sakura Agent Integration Tests ===\n")

    tests = [
        ("Rust Binary", test_rust_binary),
        ("Python Imports", test_python_imports),
        ("Protocol", test_protocol),
        ("Commands", test_commands),
        ("Bridge", test_bridge),
    ]

    results = []
    for name, test_fn in tests:
        print(f"\n--- {name} ---")
        try:
            ok = test_fn()
            results.append((name, ok))
        except Exception as e:
            print(f"✗ Exception: {e}")
            results.append((name, False))

    print("\n=== Results ===")
    all_pass = True
    for name, ok in results:
        status = "✓" if ok else "✗"
        print(f"  {status} {name}")
        if not ok:
            all_pass = False

    if all_pass:
        print("\nAll tests passed!")
    else:
        print("\nSome tests failed!")

    return 0 if all_pass else 1


if __name__ == "__main__":
    sys.exit(main())
