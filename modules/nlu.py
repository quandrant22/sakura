"""modules/nlu.py — NLU module with GLiNER-based slot extraction.

Replaces the massive if/else parsing in main.py with declarative
command definitions and neural slot extraction.

Usage:
    from modules.nlu import NLU

    nlu = NLU()
    nlu.load_commands("commands/")

    # Extract slots from voice command:
    result = nlu.extract("включи музыку от Овсянкина")
    # → {"intent": "music_artist", "slots": {"artist": "Овсянкин"}, "confidence": 0.95}
"""

from __future__ import annotations

import os
import re
import json
import logging
import hashlib
from pathlib import Path
from dataclasses import dataclass, field
from typing import Any, Optional

log = logging.getLogger("sakura.nlu")

try:
    import toml
except ImportError:
    toml = None

try:
    from rapidfuzz import fuzz
    HAS_FUZZ = True
except ImportError:
    HAS_FUZZ = False


@dataclass
class SlotDef:
    """Definition of a parameter slot."""
    entity: str = ""
    context: list[str] = field(default_factory=list)
    regex: str = ""
    required: bool = True


@dataclass
class CommandDef:
    """A command definition from TOML."""
    id: str
    type: str = "action"
    phrases: dict[str, list[str]] = field(default_factory=dict)
    patterns: list[str] = field(default_factory=list)
    keywords: list[str] = field(default_factory=list)
    action: str = ""
    args_template: str = ""
    slots: dict[str, SlotDef] = field(default_factory=dict)
    priority: int = 0
    sounds: dict[str, list[str]] = field(default_factory=dict)

    def get_phrases(self, lang: str = "ru") -> list[str]:
        if lang in self.phrases:
            return self.phrases[lang]
        if "en" in self.phrases:
            return self.phrases["en"]
        for v in self.phrases.values():
            return v
        return []


@dataclass
class IntentResult:
    """Result of intent classification."""
    intent: str
    action: str
    args: str
    slots: dict[str, Any] = field(default_factory=dict)
    confidence: float = 0.0


class NLU:
    """Natural Language Understanding module."""

    def __init__(self):
        self._commands: list[CommandDef] = []
        self._by_id: dict[str, CommandDef] = {}
        self._compiled_patterns: list[tuple[re.Pattern, CommandDef]] = []

    def load_commands(self, dir_path: str):
        """Load command definitions from TOML files."""
        if toml is None:
            log.warning("toml library not installed: pip install toml")
            return

        dir_path = Path(dir_path)
        if not dir_path.exists():
            log.warning(f"Commands directory not found: {dir_path}")
            return

        for entry in dir_path.iterdir():
            if not entry.is_dir():
                continue
            toml_file = entry / "command.toml"
            if not toml_file.exists():
                continue
            try:
                self._load_toml(toml_file)
            except Exception as e:
                log.error(f"Failed to load {toml_file}: {e}")

        # Pre-compile regex patterns
        for cmd in self._commands:
            for pattern in cmd.patterns:
                try:
                    compiled = re.compile(pattern, re.IGNORECASE)
                    self._compiled_patterns.append((compiled, cmd))
                except re.error as e:
                    log.warning(f"Invalid regex in {cmd.id}: {pattern} — {e}")

        log.info(f"NLU: loaded {len(self._commands)} commands, {len(self._compiled_patterns)} patterns")

    def _load_toml(self, toml_path: Path):
        with open(toml_path, "r", encoding="utf-8") as f:
            data = toml.load(f)

        for cmd_data in data.get("commands", []):
            cmd_id = cmd_data.get("id", "")
            if not cmd_id:
                continue

            slots = {}
            for slot_name, slot_data in cmd_data.get("slots", {}).items():
                if isinstance(slot_data, dict):
                    slots[slot_name] = SlotDef(
                        entity=slot_data.get("entity", ""),
                        context=slot_data.get("context", []),
                        regex=slot_data.get("regex", ""),
                        required=slot_data.get("required", True),
                    )

            phrases = cmd_data.get("phrases", {})
            if isinstance(phrases, list):
                phrases = {"ru": phrases}

            cmd = CommandDef(
                id=cmd_id,
                type=cmd_data.get("type", "action"),
                phrases=phrases,
                patterns=cmd_data.get("patterns", []),
                keywords=cmd_data.get("keywords", []),
                action=cmd_data.get("action", ""),
                args_template=cmd_data.get("args", ""),
                slots=slots,
                priority=cmd_data.get("priority", 0),
                sounds=cmd_data.get("sounds", {}),
            )
            self._commands.append(cmd)
            self._by_id[cmd_id] = cmd

    def classify(self, text: str, lang: str = "ru") -> Optional[IntentResult]:
        """Classify user text into an intent with extracted slots."""
        if not text:
            return None

        text_lower = text.lower().strip()
        best: Optional[IntentResult] = None
        best_score = 0.0

        # 1. Exact phrase match (highest priority)
        for cmd in self._commands:
            for phrase in cmd.get_phrases(lang):
                if text_lower == phrase.lower():
                    return IntentResult(
                        intent=cmd.id,
                        action=cmd.action,
                        args=self._fill_args(cmd.args_template, {}),
                        confidence=1.0,
                    )

        # 2. Regex patterns
        for compiled, cmd in self._compiled_patterns:
            m = compiled.search(text_lower)
            if m:
                slots = {}
                for name, value in (m.groupdict() or {}).items():
                    if value:
                        slots[name] = value
                result = IntentResult(
                    intent=cmd.id,
                    action=cmd.action,
                    args=self._fill_args(cmd.args_template, slots),
                    slots=slots,
                    confidence=0.9,
                )
                if result.confidence > best_score:
                    best = result
                    best_score = result.confidence

        # 3. Substring match with slot extraction
        for cmd in self._commands:
            for phrase in cmd.get_phrases(lang):
                phrase_lower = phrase.lower()
                if phrase_lower in text_lower:
                    # Extract the part after the phrase as slot value
                    slots = self._extract_slots(cmd, text_lower, phrase_lower)
                    score = 0.85
                    if score > best_score:
                        best = IntentResult(
                            intent=cmd.id,
                            action=cmd.action,
                            args=self._fill_args(cmd.args_template, slots),
                            slots=slots,
                            confidence=score,
                        )
                        best_score = score

        # 4. Keyword matching
        for cmd in self._commands:
            if not cmd.keywords:
                continue
            matched = sum(1 for kw in cmd.keywords if kw in text_lower)
            if matched > 0:
                score = (matched / len(cmd.keywords)) * 0.7
                if score > best_score:
                    best = IntentResult(
                        intent=cmd.id,
                        action=cmd.action,
                        args=self._fill_args(cmd.args_template, {}),
                        confidence=score,
                    )
                    best_score = score

        # 5. Fuzzy matching (fallback)
        if HAS_FUZZ and best_score < 0.5:
            for cmd in self._commands:
                for phrase in cmd.get_phrases(lang):
                    ratio = fuzz.ratio(text_lower, phrase.lower()) / 100.0
                    if ratio > 0.6 and ratio > best_score:
                        best = IntentResult(
                            intent=cmd.id,
                            action=cmd.action,
                            args=self._fill_args(cmd.args_template, {}),
                            confidence=ratio * 0.6,
                        )
                        best_score = ratio * 0.6

        return best

    def _extract_slots(self, cmd: CommandDef, text: str, phrase: str) -> dict[str, Any]:
        """Extract slot values from text by removing the matched phrase."""
        slots = {}
        remaining = text.replace(phrase, "", 1).strip()
        if not remaining:
            return slots

        # If there's only one slot, assign remaining text to it
        if cmd.slots and len(cmd.slots) == 1:
            slot_name = next(iter(cmd.slots))
            slots[slot_name] = remaining.strip()
        elif cmd.slots:
            # Multiple slots — try to split by context words
            for slot_name, slot_def in cmd.slots.items():
                for ctx_word in slot_def.context:
                    if ctx_word in remaining:
                        parts = remaining.split(ctx_word, 1)
                        if len(parts) > 1:
                            slots[slot_name] = parts[1].strip()
                            remaining = parts[0].strip()
                            break
            # Assign any remaining text to the first empty slot
            if remaining:
                for slot_name in cmd.slots:
                    if slot_name not in slots:
                        slots[slot_name] = remaining.strip()
                        break

        return slots

    def _fill_args(self, template: str, slots: dict[str, Any]) -> str:
        if not template:
            return ""
        result = template
        for name, value in slots.items():
            result = result.replace(f"{{{name}}}", str(value))
        return result

    def get_command(self, cmd_id: str) -> Optional[CommandDef]:
        return self._by_id.get(cmd_id)

    @property
    def command_count(self) -> int:
        return len(self._commands)
