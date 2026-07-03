#!/usr/bin/env python3
"""launch.py — Launch Sakura agent with Rust audio core.

This script starts both the Rust audio core and the Python agent.
The Rust core handles audio processing, while the Python agent
handles Windows API integration.

Usage:
    python launch.py                  # Start with Rust core
    python launch.py --python-only    # Start with Python audio only
    python launch.py --rust-only      # Start Rust core only
"""

import argparse
import logging
import os
import signal
import sys
import threading
import time

# Add agent directory to path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))


def setup_logging():
    """Setup logging configuration."""
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s  %(message)s",
        datefmt="%H:%M:%S",
    )


def check_rust_binary():
    """Check if Rust binary exists."""
    from pathlib import Path

    release_path = Path(__file__).parent / "core-rust" / "target" / "release" / "sakura-audio-core"
    if release_path.exists():
        return str(release_path)

    # Check PATH
    import shutil
    path = shutil.which("sakura-audio-core")
    if path:
        return path

    return None


def build_rust_core():
    """Build Rust core if not exists."""
    rust_dir = os.path.join(os.path.dirname(__file__), "core-rust")
    if not os.path.exists(rust_dir):
        print("Rust core directory not found")
        return False

    print("Building Rust audio core...")
    ret = os.system(f"cd {rust_dir} && cargo build --release")
    return ret == 0


def run_python_agent():
    """Run the Python agent with Rust core bridge."""
    from core.bridge import start_core, stop_core, RustCore
    from core.agent import Agent
    from core.events import EventBus
    import asyncio

    # Check for Rust binary
    rust_binary = check_rust_binary()
    if not rust_binary:
        print("Rust binary not found. Building...")
        if not build_rust_core():
            print("Failed to build Rust core")
            print("Falling back to Python audio...")
            return run_python_agent_legacy()

    # Create event bus
    bus = EventBus()

    # Create Rust core bridge
    rust_core = RustCore(rust_binary)

    # Create agent
    agent = Agent(bus)

    # Start Rust core
    print("Starting Rust audio core...")
    rust_core.start()

    # Start agent in background
    agent_thread = threading.Thread(
        target=lambda: asyncio.run(agent.run()),
        daemon=True,
    )
    agent_thread.start()

    # Start Qt UI
    try:
        from PyQt6.QtWidgets import QApplication
        from PyQt6.QtCore import QSharedMemory
        from ui.app import UiBridge, build_tray
        from ui.overlay import Overlay

        app = QApplication(sys.argv)
        app.setApplicationName("Сакура")
        app.setQuitOnLastWindowClosed(False)

        guard = QSharedMemory("sakura-agent-singleton")
        if not guard.create(1):
            print("Сакура уже запущена.")
            return

        bridge = UiBridge(bus)
        overlay = Overlay()

        bridge.stateChanged.connect(overlay.set_state)
        bridge.userText.connect(overlay.add_user_message)
        bridge.sakuraText.connect(overlay.add_sakura_message)
        bridge.connectionChanged.connect(overlay.set_connected)
        bridge.moodUpdate.connect(overlay.set_mood)
        bridge.gameMode.connect(overlay.set_game_mode)
        bridge.micLevel.connect(overlay.hud.set_audio_level)
        bridge.orbArrival.connect(overlay.animate_arrival)
        bridge.orbDeparture.connect(overlay.animate_departure)
        overlay.submit.connect(agent.submit_user_text)

        app.tray = build_tray(app, overlay)

        print("Сакура запущена с Rust audio core")
        overlay.show()
        sys.exit(app.exec())

    except ImportError as e:
        print(f"UI not available: {e}")
        print("Running in headless mode...")

        # Keep running
        try:
            while True:
                time.sleep(1)
        except KeyboardInterrupt:
            pass
    finally:
        stop_core()


def run_python_agent_legacy():
    """Run the Python agent with legacy audio (no Rust)."""
    print("Running with Python audio pipeline...")

    from sakura import main
    main()


def main():
    parser = argparse.ArgumentParser(description="Sakura Agent Launcher")
    parser.add_argument("--python-only", action="store_true",
                        help="Run with Python audio only")
    parser.add_argument("--rust-only", action="store_true",
                        help="Run Rust core only")
    parser.add_argument("--build", action="store_true",
                        help="Build Rust core and exit")
    parser.add_argument("--headless", action="store_true",
                        help="Run without UI")

    args = parser.parse_args()

    setup_logging()

    if args.build:
        if build_rust_core():
            print("Build successful!")
        else:
            print("Build failed!")
        return

    if args.rust_only:
        from core.bridge import RustCore
        core = RustCore()
        core.start()
        try:
            while core.is_running():
                time.sleep(1)
        except KeyboardInterrupt:
            core.stop()
        return

    if args.python_only:
        run_python_agent_legacy()
        return

    # Default: run with Rust core
    run_python_agent()


if __name__ == "__main__":
    main()
