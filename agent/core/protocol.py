"""core/protocol.py — typed IPC protocol for agent ↔ VPS communication.

Replaces raw dict passing with validated dataclasses.
Both sides (agent and VPS) can use these types for type-safe communication.

Usage:
    from core.protocol import Event, Action, parse_event, parse_action

    # Sending an event to VPS:
    event = Registered(device_id="pc", active_window="Chrome", ...)
    ws.send(event.to_json())

    # Receiving an action from VPS:
    action = parse_action(raw_json)
    if isinstance(action, Command):
        execute(action.target, action.args)
"""

from __future__ import annotations

import json
import time
from dataclasses import dataclass, field, asdict
from enum import Enum
from typing import Any, Optional, Union


# ── Enums ──────────────────────────────────────────────────────────────

class DeviceType(str, Enum):
    PC = "pc"
    LAPTOP = "laptop"
    PHONE = "phone"


class ConnectionState(str, Enum):
    DISCONNECTED = "disconnected"
    CONNECTING = "connecting"
    CONNECTED = "connected"


class AgentState(str, Enum):
    IDLE = "idle"
    LISTENING = "listening"
    THINKING = "thinking"
    SPEAKING = "speaking"


# ── Base classes ───────────────────────────────────────────────────────

@dataclass
class IPCMessage:
    """Base class for all IPC messages."""

    def to_json(self) -> str:
        return json.dumps(asdict(self), ensure_ascii=False)

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class Event(IPCMessage):
    """Base class for all events sent from agent to VPS."""

    type: str = ""
    device_id: str = ""
    timestamp: float = field(default_factory=time.time)


@dataclass
class Action(IPCMessage):
    """Base class for all actions sent from VPS to agent."""

    type: str = ""


# ── Events (agent → VPS) ──────────────────────────────────────────────

@dataclass
class Registered(Event):
    """Agent registered with VPS."""
    type: str = "register"
    active_window: str = ""
    system_info: dict = field(default_factory=dict)
    capabilities: list[str] = field(default_factory=list)
    version: str = "2.0"


@dataclass
class Ping(Event):
    """Heartbeat ping."""
    type: str = "ping"
    active_window: str = ""
    system_info: dict = field(default_factory=dict)


@dataclass
class VoiceCommand(Event):
    """Recognized voice command from user."""
    type: str = "voice_command"
    text: str = ""
    active_window: str = ""
    context: list[str] = field(default_factory=list)
    prosody: dict = field(default_factory=dict)


@dataclass
class CommandResult(Event):
    """Result of a command executed by agent."""
    type: str = "command_result"
    action: str = ""
    result: str = ""
    success: bool = True
    screenshot: str = ""  # base64 encoded
    metadata: dict = field(default_factory=dict)


@dataclass
class AppsList(Event):
    """Scanned applications list."""
    type: str = "apps_list"
    apps: dict = field(default_factory=dict)


@dataclass
class TextMessage(Event):
    """Text message to forward to Telegram."""
    type: str = "tg_message"
    text: str = ""


# ── Actions (VPS → agent) ─────────────────────────────────────────────

@dataclass
class Command(Action):
    """Execute a command on the agent."""
    type: str = "command"
    target: str = ""  # e.g. "open_app", "volume", "browser"
    args: str = ""    # e.g. "firefox", "50", "tab_new"
    request_id: str = ""  # for matching results


@dataclass
class TTSChunk(Action):
    """Text-to-speech audio chunk."""
    type: str = "tts_chunk"
    audio: str = ""  # base64 encoded PCM


@dataclass
class TTSEnd(Action):
    """End of TTS stream."""
    type: str = "tts_end"


@dataclass
class Reply(Action):
    """Text reply from Sakura."""
    type: str = "reply"
    text: str = ""
    mood: dict = field(default_factory=dict)


@dataclass
class MoodUpdate(Action):
    """Mood update from VPS."""
    type: str = "mood_update"
    params: dict = field(default_factory=dict)


@dataclass
class StateUpdate(Action):
    """Agent state update request."""
    type: str = "state_update"
    state: str = "idle"


# ── Parsing ────────────────────────────────────────────────────────────

_EVENT_TYPES: dict[str, type[Event]] = {
    "register": Registered,
    "ping": Ping,
    "voice_command": VoiceCommand,
    "command_result": CommandResult,
    "apps_list": AppsList,
    "tg_message": TextMessage,
}

_ACTION_TYPES: dict[str, type[Action]] = {
    "command": Command,
    "tts_chunk": TTSChunk,
    "tts_end": TTSEnd,
    "reply": Reply,
    "mood_update": MoodUpdate,
    "state_update": StateUpdate,
}


def parse_event(data: dict) -> Optional[Event]:
    """Parse a raw dict into a typed Event."""
    msg_type = data.get("type", "")
    cls = _EVENT_TYPES.get(msg_type)
    if cls is None:
        return None
    try:
        # Filter out fields not in the dataclass
        import dataclasses
        valid_fields = {f.name for f in dataclasses.fields(cls)}
        filtered = {k: v for k, v in data.items() if k in valid_fields}
        return cls(**filtered)
    except Exception:
        return None


def parse_action(data: dict) -> Optional[Action]:
    """Parse a raw dict into a typed Action."""
    msg_type = data.get("type", "")
    cls = _ACTION_TYPES.get(msg_type)
    if cls is None:
        return None
    try:
        import dataclasses
        valid_fields = {f.name for f in dataclasses.fields(cls)}
        filtered = {k: v for k, v in data.items() if k in valid_fields}
        return cls(**filtered)
    except Exception:
        return None


def parse_message(raw: str) -> Union[Event, Action, None]:
    """Parse a raw JSON string into either an Event or Action."""
    try:
        data = json.loads(raw)
    except Exception:
        return None

    msg_type = data.get("type", "")

    # Try event first
    event = parse_event(data)
    if event is not None:
        return event

    # Then action
    action = parse_action(data)
    if action is not None:
        return action

    return None


# ── Capability negotiation ─────────────────────────────────────────────

class Capabilities:
    """What this agent can do. Sent on registration."""

    VOICE = "voice"           # Has microphone + STT
    TTS = "tts"               # Can play TTS audio
    SCREENSHOT = "screenshot"  # Can take screenshots
    APPS = "apps"             # Can launch applications
    BROWSER = "browser"       # Can control browser
    MUSIC = "music"           # Can control music player
    KETTLE = "kettle"         # Can control smart kettle
    DICTATE = "dictate"       # Can dictate text via clipboard
    SYSTEM = "system"         # Can lock/shutdown/sleep

    @staticmethod
    def detect() -> list[str]:
        """Auto-detect available capabilities."""
        caps = []

        try:
            import sounddevice
            caps.append(Capabilities.VOICE)
        except ImportError:
            pass

        try:
            import sounddevice
            caps.append(Capabilities.TTS)
        except ImportError:
            pass

        try:
            from PIL import ImageGrab
            caps.append(Capabilities.SCREENSHOT)
        except ImportError:
            pass

        # Windows-specific
        import sys
        if sys.platform == "win32":
            caps.extend([
                Capabilities.APPS,
                Capabilities.BROWSER,
                Capabilities.MUSIC,
                Capabilities.DICTATE,
                Capabilities.SYSTEM,
            ])

        try:
            from bleak import BleakClient
            caps.append(Capabilities.KETTLE)
        except ImportError:
            pass

        return caps
