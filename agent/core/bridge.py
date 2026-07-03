"""core/bridge.py — Python bridge for Rust audio core.

This module provides a Python interface to the Rust audio core.
It communicates via stdin/stdout JSON protocol.

Usage:
    from core.bridge import RustCore

    core = RustCore()
    core.start()

    # Listen for events
    for event in core.events():
        if event.type == "speech_recognized":
            process_command(event.text)

    # Send commands
    core.send_command("open_app", "firefox")
"""

import asyncio
import json
import logging
import os
import subprocess
import threading
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional, Generator

log = logging.getLogger("sakura.bridge")


@dataclass
class Event:
    """Event from Rust core."""
    type: str
    device_id: str = ""
    timestamp: float = 0.0
    text: str = ""
    action: str = ""
    result: str = ""
    success: bool = True
    screenshot: str = ""
    apps: dict = field(default_factory=dict)
    message: str = ""


@dataclass
class Action:
    """Action to send to Rust core."""
    type: str
    target: str = ""
    args: str = ""
    request_id: str = ""
    audio: str = ""
    text: str = ""
    mood: dict = field(default_factory=dict)
    params: dict = field(default_factory=dict)
    state: str = ""


class RustCore:
    """Interface to Rust audio core."""

    def __init__(self, binary_path: Optional[str] = None):
        self._binary_path = binary_path or self._find_binary()
        self._process: Optional[subprocess.Popen] = None
        self._event_queue: asyncio.Queue = asyncio.Queue()
        self._running = False
        self._thread: Optional[threading.Thread] = None

    def _find_binary(self) -> str:
        """Find the Rust binary."""
        # Check in core-rust/target/release/
        release_path = Path(__file__).parent.parent / "core-rust" / "target" / "release" / "sakura-audio-core"
        if release_path.exists():
            return str(release_path)

        # Check in PATH
        import shutil
        path = shutil.which("sakura-audio-core")
        if path:
            return path

        raise FileNotFoundError(
            "Rust audio core not found. Build with: cd core-rust && cargo build --release"
        )

    def start(self):
        """Start the Rust core process."""
        if self._process is not None:
            log.warning("Rust core already running")
            return

        log.info(f"Starting Rust core: {self._binary_path}")

        self._process = subprocess.Popen(
            [self._binary_path],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=False,
            bufsize=0,
        )

        self._running = True

        # Start reader thread
        self._thread = threading.Thread(target=self._reader_loop, daemon=True)
        self._thread.start()

        # Start stderr reader
        threading.Thread(target=self._stderr_reader, daemon=True).start()

        log.info("Rust core started")

    def stop(self):
        """Stop the Rust core process."""
        self._running = False

        if self._process:
            self._process.terminate()
            try:
                self._process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                self._process.kill()
            self._process = None

        log.info("Rust core stopped")

    def _reader_loop(self):
        """Read events from Rust core stdout."""
        if not self._process or not self._process.stdout:
            return

        while self._running:
            try:
                line = self._process.stdout.readline()
                if not line:
                    break

                # Parse JSON event
                try:
                    data = json.loads(line)
                    event = Event(**{
                        k: v for k, v in data.items()
                        if k in Event.__dataclass_fields__
                    })
                    asyncio.run_coroutine_threadsafe(
                        self._event_queue.put(event),
                        asyncio.get_event_loop(),
                    )
                except json.JSONDecodeError as e:
                    log.warning(f"Failed to parse Rust output: {e}")
                except Exception as e:
                    log.error(f"Failed to process event: {e}")

            except Exception as e:
                if self._running:
                    log.error(f"Reader error: {e}")
                break

    def _stderr_reader(self):
        """Read stderr from Rust core for logging."""
        if not self._process or not self._process.stderr:
            return

        for line in self._process.stderr:
            if line:
                log.debug(f"[rust] {line.decode().strip()}")

    def send_action(self, action: Action):
        """Send an action to Rust core."""
        if not self._process or not self._process.stdin:
            log.warning("Rust core not running")
            return

        data = {
            "type": action.type,
        }
        if action.target:
            data["target"] = action.target
        if action.args:
            data["args"] = action.args
        if action.request_id:
            data["request_id"] = action.request_id
        if action.audio:
            data["audio"] = action.audio
        if action.text:
            data["text"] = action.text
        if action.mood:
            data["mood"] = action.mood
        if action.params:
            data["params"] = action.params
        if action.state:
            data["state"] = action.state

        try:
            line = json.dumps(data) + "\n"
            self._process.stdin.write(line.encode())
            self._process.stdin.flush()
        except Exception as e:
            log.error(f"Failed to send action: {e}")

    def send_command(self, target: str, args: str = "", request_id: str = ""):
        """Send a command to Rust core."""
        self.send_action(Action(
            type="command",
            target=target,
            args=args,
            request_id=request_id,
        ))

    def send_tts_chunk(self, audio_b64: str):
        """Send TTS audio chunk."""
        self.send_action(Action(type="tts_chunk", audio=audio_b64))

    def send_tts_end(self):
        """Signal end of TTS stream."""
        self.send_action(Action(type="tts_end"))

    def send_reply(self, text: str, mood: dict = None):
        """Send text reply."""
        self.send_action(Action(type="reply", text=text, mood=mood or {}))

    def send_mood_update(self, params: dict):
        """Send mood update."""
        self.send_action(Action(type="mood_update", params=params))

    def send_state_update(self, state: str):
        """Send state update."""
        self.send_action(Action(type="state_update", state=state))

    async def events(self):
        """Async generator for events."""
        while self._running:
            try:
                event = await asyncio.wait_for(self._event_queue.get(), timeout=1.0)
                yield event
            except asyncio.TimeoutError:
                continue

    def is_running(self) -> bool:
        """Check if Rust core is running."""
        return self._running and self._process is not None and self._process.poll() is None


# ── Convenience singleton ──────────────────────────────────────────────

_core: Optional[RustCore] = None


def get_core() -> RustCore:
    """Get or create the Rust core instance."""
    global _core
    if _core is None:
        _core = RustCore()
    return _core


def start_core():
    """Start the Rust core."""
    core = get_core()
    core.start()
    return core


def stop_core():
    """Stop the Rust core."""
    global _core
    if _core:
        _core.stop()
        _core = None
