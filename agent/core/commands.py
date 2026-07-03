"""core/commands.py — TOML-based command registry.

Replaces if/else parsing with declarative command definitions.
Commands are defined in TOML files and loaded at startup.

Usage:
    from core.commands import CommandRegistry

    registry = CommandRegistry()
    registry.load_from_dir("commands/")

    # Match a voice command to an action:
    result = registry.match("открой браузер")
    if result:
        execute(result.action, result.args)
"""

from __future__ import annotations

import os
import re
import json
import logging
import threading
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional, Callable, Any

log = logging.getLogger("sakura.commands")

try:
    import toml
except ImportError:
    toml = None


@dataclass
class SlotDef:
    """Definition of a parameter slot in a command."""
    entity: str = ""          # GLiNER entity label
    context: list[str] = field(default_factory=list)  # context words
    regex: str = ""           # fallback regex pattern
    required: bool = True


@dataclass
class CommandDef:
    """A single command definition from TOML."""
    id: str
    type: str  # "action", "lua", "regex", "chain"

    # Matching
    phrases: dict[str, list[str]] = field(default_factory=dict)  # lang → phrases
    patterns: list[str] = field(default_factory=list)  # regex patterns
    keywords: list[str] = field(default_factory=list)  # keyword triggers

    # Execution
    action: str = ""  # target action (e.g. "open_app", "volume")
    args_template: str = ""  # template with {slot} placeholders
    script: str = ""  # for lua type

    # Slots
    slots: dict[str, SlotDef] = field(default_factory=dict)

    # Metadata
    description: str = ""
    priority: int = 0  # higher = checked first
    sandbox: str = "standard"
    timeout: int = 10000

    # Sound feedback
    sounds: dict[str, list[str]] = field(default_factory=dict)

    def get_phrases(self, lang: str = "ru") -> list[str]:
        """Get phrases for a language with fallback."""
        if lang in self.phrases:
            return self.phrases[lang]
        if "en" in self.phrases:
            return self.phrases["en"]
        # Return first available
        for v in self.phrases.values():
            return v
        return []


@dataclass
class MatchResult:
    """Result of matching a voice command."""
    command: CommandDef
    action: str
    args: str
    slots: dict[str, Any] = field(default_factory=dict)
    confidence: float = 1.0


class CommandRegistry:
    """Registry of all available commands."""

    def __init__(self):
        self._commands: list[CommandDef] = []
        self._by_id: dict[str, CommandDef] = {}
        self._lock = threading.Lock()
        self._hash: str = ""

    def load_from_dir(self, dir_path: str):
        """Load all command.toml files from a directory."""
        if toml is None:
            log.warning("toml library not installed: pip install toml")
            return

        dir_path = Path(dir_path)
        if not dir_path.exists():
            log.warning(f"Commands directory not found: {dir_path}")
            return

        count = 0
        for entry in dir_path.iterdir():
            if not entry.is_dir():
                continue
            toml_file = entry / "command.toml"
            if not toml_file.exists():
                continue

            try:
                self._load_toml(toml_file, entry)
                count += 1
            except Exception as e:
                log.error(f"Failed to load {toml_file}: {e}")

        log.info(f"Loaded {count} command pack(s), {len(self._commands)} commands total")
        self._compute_hash()

    def _load_toml(self, toml_path: Path, cmd_dir: Path):
        """Load a single command.toml file."""
        with open(toml_path, "r", encoding="utf-8") as f:
            data = toml.load(f)

        for cmd_data in data.get("commands", []):
            cmd = self._parse_command(cmd_data, cmd_dir)
            if cmd:
                self._commands.append(cmd)
                self._by_id[cmd.id] = cmd

    def _parse_command(self, data: dict, cmd_dir: Path) -> Optional[CommandDef]:
        """Parse a single command from TOML data."""
        cmd_id = data.get("id", "")
        cmd_type = data.get("type", "action")

        if not cmd_id:
            return None

        # Parse slots
        slots = {}
        for slot_name, slot_data in data.get("slots", {}).items():
            if isinstance(slot_data, dict):
                slots[slot_name] = SlotDef(
                    entity=slot_data.get("entity", ""),
                    context=slot_data.get("context", []),
                    regex=slot_data.get("regex", ""),
                    required=slot_data.get("required", True),
                )

        # Parse phrases (handle both list and dict formats)
        phrases = data.get("phrases", {})
        if isinstance(phrases, list):
            # Single-language list → assume current lang
            phrases = {"ru": phrases}

        return CommandDef(
            id=cmd_id,
            type=cmd_type,
            phrases=phrases,
            patterns=data.get("patterns", []),
            keywords=data.get("keywords", []),
            action=data.get("action", ""),
            args_template=data.get("args", ""),
            script=data.get("script", ""),
            slots=slots,
            description=data.get("description", ""),
            priority=data.get("priority", 0),
            sandbox=data.get("sandbox", "standard"),
            timeout=data.get("timeout", 10000),
            sounds=data.get("sounds", {}),
        )

    def match(self, text: str, lang: str = "ru") -> Optional[MatchResult]:
        """Match a voice command against all registered commands.

        Returns MatchResult with the best match, or None.
        """
        if not text:
            return None

        text_lower = text.lower().strip()
        best_match: Optional[MatchResult] = None
        best_score = 0.0

        with self._lock:
            # Sort by priority (higher first)
            sorted_cmds = sorted(self._commands, key=lambda c: -c.priority)

            for cmd in sorted_cmds:
                result = self._match_command(cmd, text_lower, lang)
                if result and result.confidence > best_score:
                    best_match = result
                    best_score = result.confidence
                    # Perfect match → return immediately
                    if best_score >= 0.99:
                        return best_match

        return best_match

    def _match_command(self, cmd: CommandDef, text: str, lang: str) -> Optional[MatchResult]:
        """Try to match a single command against text."""
        # 1. Exact phrase match
        for phrase in cmd.get_phrases(lang):
            phrase_lower = phrase.lower().strip()
            if text == phrase_lower:
                return MatchResult(
                    command=cmd,
                    action=cmd.action,
                    args=self._fill_args(cmd.args_template, {}),
                    confidence=1.0,
                )

        # 2. Substring match
        for phrase in cmd.get_phrases(lang):
            phrase_lower = phrase.lower().strip()
            if phrase_lower in text:
                # Try to extract slots from the surrounding text
                slots = self._extract_slots_simple(cmd, text, phrase_lower)
                return MatchResult(
                    command=cmd,
                    action=cmd.action,
                    args=self._fill_args(cmd.args_template, slots),
                    slots=slots,
                    confidence=0.9,
                )

        # 3. Keyword match
        if cmd.keywords:
            text_lower = text.lower()
            # Check for exact keyword match (entire keyword must be in text)
            for kw in cmd.keywords:
                kw_lower = kw.lower()
                if kw_lower == text_lower:
                    return MatchResult(
                        command=cmd,
                        action=cmd.action,
                        args=self._fill_args(cmd.args_template, {}),
                        confidence=0.95,
                    )
            # Check if any keyword is contained in the text
            for kw in cmd.keywords:
                kw_lower = kw.lower()
                if kw_lower in text_lower:
                    return MatchResult(
                        command=cmd,
                        action=cmd.action,
                        args=self._fill_args(cmd.args_template, {}),
                        confidence=0.8,
                    )

        # 4. Regex match
        for pattern in cmd.patterns:
            try:
                m = re.search(pattern, text, re.IGNORECASE)
                if m:
                    slots = {}
                    for name, value in m.groupdict().items():
                        if value:
                            slots[name] = value
                    return MatchResult(
                        command=cmd,
                        action=cmd.action,
                        args=self._fill_args(cmd.args_template, slots),
                        slots=slots,
                        confidence=0.85,
                    )
            except re.error:
                pass

        # 5. Fuzzy match (simple word overlap)
        for phrase in cmd.get_phrases(lang):
            phrase_words = set(phrase.lower().split())
            text_words = set(text.split())
            overlap = phrase_words & text_words
            if len(overlap) >= 2:
                score = len(overlap) / max(len(phrase_words), len(text_words))
                if score >= 0.5:
                    return MatchResult(
                        command=cmd,
                        action=cmd.action,
                        args=self._fill_args(cmd.args_template, {}),
                        confidence=score * 0.7,
                    )

        return None

    def _extract_slots_simple(self, cmd: CommandDef, text: str, phrase: str) -> dict[str, Any]:
        """Simple slot extraction by removing the phrase from text."""
        slots = {}
        remaining = text.replace(phrase, "").strip()
        if remaining and cmd.slots:
            # Assign remaining text to the first slot
            first_slot = next(iter(cmd.slots))
            slots[first_slot] = remaining
        return slots

    def _fill_args(self, template: str, slots: dict[str, Any]) -> str:
        """Fill argument template with slot values."""
        if not template:
            return ""
        result = template
        for name, value in slots.items():
            result = result.replace(f"{{{name}}}", str(value))
        return result

    def get_command(self, cmd_id: str) -> Optional[CommandDef]:
        """Get a command by ID."""
        return self._by_id.get(cmd_id)

    def list_commands(self) -> list[CommandDef]:
        """List all registered commands."""
        with self._lock:
            return list(self._commands)

    def _compute_hash(self):
        """Compute hash of all commands for cache invalidation."""
        import hashlib
        h = hashlib.sha256()
        for cmd in sorted(self._commands, key=lambda c: c.id):
            h.update(cmd.id.encode())
            for phrase in sorted(cmd.get_phrases()):
                h.update(phrase.encode())
        self._hash = h.hexdigest()

    @property
    def hash(self) -> str:
        return self._hash


# ── Built-in command definitions ───────────────────────────────────────

BUILTIN_COMMANDS = """
[[commands]]
id = "open_app"
type = "action"
action = "open_app"
args = "{app_name}"
priority = 10
description = "Open an application by name"

phrases.ru = [
    "открой {app_name}",
    "запусти {app_name}",
    "включи {app_name}",
]

[commands.slots.app_name]
entity = "application name"
context = ["открой", "запусти", "включи"]

[[commands]]
id = "open_browser"
type = "action"
action = "open_app"
args = "browser"
priority = 15
description = "Open browser"

phrases.ru = [
    "открой браузер",
    "запусти браузер",
    "включи браузер",
]

keywords = ["браузер"]

[[commands]]
id = "close_window"
type = "action"
action = "close_window"
args = "{window_name}"
priority = 10
description = "Close a window"

phrases.ru = [
    "закрой {window_name}",
]

[commands.slots.window_name]
entity = "window name"
context = ["закрой"]

[[commands]]
id = "volume_set"
type = "action"
action = "volume"
args = "{level}"
priority = 20
patterns = []

[commands.slots.level]
entity = "number"

[[commands]]
id = "volume_up"
type = "action"
action = "volume_up"
args = "{delta}"
priority = 15
keywords = ["громче", "прибавь", "увеличь"]

[commands.slots.delta]
entity = "number"
required = false

[[commands]]
id = "volume_down"
type = "action"
action = "volume_down"
args = "{delta}"
priority = 15
keywords = ["тише", "убавь", "уменьши"]

[commands.slots.delta]
entity = "number"
required = false

[[commands]]
id = "mute"
type = "action"
action = "volume"
args = "0"
priority = 25
keywords = ["выключи звук", "без звука", "тихо"]

[[commands]]
id = "browser_tab_new"
type = "action"
action = "browser"
args = "tab_new"
priority = 10
keywords = ["новая вкладка", "открой вкладку"]

[[commands]]
id = "browser_tab_close"
type = "action"
action = "browser"
args = "tab_close"
priority = 10
keywords = ["закрой вкладку", "закрой таб"]

[[commands]]
id = "browser_next"
type = "action"
action = "browser"
args = "tab_next"
priority = 10
keywords = ["следующая вкладка", "таб вперёд"]

[[commands]]
id = "browser_prev"
type = "action"
action = "browser"
args = "tab_prev"
priority = 10
keywords = ["предыдущая вкладка", "таб назад"]

[[commands]]
id = "browser_back"
type = "action"
action = "browser"
args = "back"
priority = 10
keywords = ["назад в браузере", "вернись назад"]

[[commands]]
id = "browser_forward"
type = "action"
action = "browser"
args = "forward"
priority = 10
keywords = ["вперёд в браузере"]

[[commands]]
id = "browser_reload"
type = "action"
action = "browser"
args = "reload"
priority = 10
keywords = ["обнови страницу", "перезагрузи"]

[[commands]]
id = "browser_scroll_down"
type = "action"
action = "browser"
args = "scroll_down"
priority = 10
keywords = ["прокрути вниз", "листай вниз"]

[[commands]]
id = "browser_scroll_up"
type = "action"
action = "browser"
args = "scroll_up"
priority = 10
keywords = ["прокрути вверх", "листай вверх"]

[[commands]]
id = "browser_search"
type = "action"
action = "browser"
args = "search:{query}"
priority = 15
keywords = ["найди в браузере", "загугли", "найди в интернете"]

[commands.slots.query]
entity = "search query"

[[commands]]
id = "browser_url"
type = "action"
action = "browser"
args = "url:{url}"
priority = 20
patterns = []

[commands.slots.url]
entity = "url"

[[commands]]
id = "screenshot"
type = "action"
action = "screenshot"
args = ""
priority = 30
keywords = ["скриншот", "снимок экрана", "сделай снимок"]

[[commands]]
id = "dictate"
type = "action"
action = "dictate"
args = "{text}"
priority = 20
keywords = ["диктуй", "вставь текст"]

[commands.slots.text]
entity = "dictated text"

[[commands]]
id = "system_lock"
type = "action"
action = "system"
args = "lock"
priority = 30
keywords = ["заблокируй", "блокировка"]

[[commands]]
id = "system_shutdown"
type = "action"
action = "system"
args = "shutdown"
priority = 30
keywords = ["выключи комп", "shutdown"]

[[commands]]
id = "system_sleep"
type = "action"
action = "system"
args = "sleep"
priority = 30
keywords = ["спящий режим", "в сон"]

[[commands]]
id = "music_play_pause"
type = "action"
action = "music"
args = "play_pause"
priority = 15
keywords = ["пауза", "останови музыку", "продолжи"]

[[commands]]
id = "music_next"
type = "action"
action = "music"
args = "next"
priority = 15
keywords = ["следующий трек", "скип"]

[[commands]]
id = "music_prev"
type = "action"
action = "music"
args = "prev"
priority = 15
keywords = ["предыдущий трек", "назад"]

[[commands]]
id = "music_like"
type = "action"
action = "music"
args = "like"
priority = 20
keywords = ["лайкни", "залайкай", "поставь лайк"]

[[commands]]
id = "music_dislike"
type = "action"
action = "music"
args = "dislike"
priority = 20
keywords = ["дизлайкни", "плохой трек"]

[[commands]]
id = "music_open"
type = "action"
action = "music"
args = "open"
priority = 10
keywords = ["открой музыку", "включи музыку"]

[[commands]]
id = "music_wave"
type = "action"
action = "music"
args = "wave"
priority = 10
keywords = ["моя волна", "волна"]

[[commands]]
id = "music_track"
type = "action"
action = "music"
args = "track:{query}"
priority = 15
keywords = ["включи трек", "поставь трек"]

[commands.slots.query]
entity = "track name"

[[commands]]
id = "music_artist"
type = "action"
action = "music"
args = "artist:{query}"
priority = 15
keywords = ["включи исполнителя", "музыку от"]

[commands.slots.query]
entity = "artist name"

[[commands]]
id = "kettle_boil"
type = "action"
action = "kettle"
args = "boil"
priority = 20
keywords = ["вскипяти", "кипяти", "чайник"]

[[commands]]
id = "kettle_off"
type = "action"
action = "kettle"
args = "off"
priority = 25
keywords = ["выключи чайник", "останови чайник"]

[[commands]]
id = "kettle_status"
type = "action"
action = "kettle"
args = "status"
priority = 20
keywords = ["статус чайника", "температура чайника"]

[[commands]]
id = "remember_app"
type = "action"
action = "remember_app"
args = "{pair}"
priority = 30
patterns = []

[commands.slots.pair]
entity = "key=value pair"
"""


def load_builtin_commands(registry: CommandRegistry):
    """Load built-in command definitions."""
    if toml is None:
        log.warning("toml library not installed, skipping built-in commands")
        return

    import tempfile
    with tempfile.NamedTemporaryFile(mode="w", suffix=".toml", delete=False) as f:
        f.write(BUILTIN_COMMANDS)
        tmp_path = f.name

    try:
        data = toml.load(tmp_path)
        for cmd_data in data.get("commands", []):
            cmd = registry._parse_command(cmd_data, Path("."))
            if cmd:
                registry._commands.append(cmd)
                registry._by_id[cmd.id] = cmd
    finally:
        os.unlink(tmp_path)

    log.info(f"Loaded {len(registry._commands)} built-in commands")
