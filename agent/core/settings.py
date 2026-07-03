"""core/settings.py — persistent key-value settings manager.

Replaces config.py with auto-saving settings that survive restarts.
Settings are stored in a JSON file and can be updated at runtime.

Usage:
    from core.settings import Settings

    settings = Settings("settings.json")
    settings.set("device_id", "pc")
    settings.set("tts_rate", 24000)

    device_id = settings.get("device_id", "unknown")
    tts_rate = settings.get_int("tts_rate", 16000)
"""

from __future__ import annotations

import json
import os
import threading
import logging
from pathlib import Path
from typing import Any, Optional

log = logging.getLogger("sakura.settings")


class Settings:
    """Persistent key-value settings with auto-save."""

    def __init__(self, path: str = "settings.json"):
        self._path = Path(path)
        self._data: dict[str, Any] = {}
        self._lock = threading.Lock()
        self._dirty = False
        self._auto_save_interval = 5.0  # seconds

        # Load existing settings
        self._load()

        # Start auto-save thread
        self._start_auto_save()

    def _load(self):
        """Load settings from disk."""
        if not self._path.exists():
            log.info(f"No settings file found at {self._path}, using defaults")
            return

        try:
            with open(self._path, "r", encoding="utf-8") as f:
                self._data = json.load(f)
            log.info(f"Loaded {len(self._data)} settings from {self._path}")
        except Exception as e:
            log.error(f"Failed to load settings: {e}")
            self._data = {}

    def _save(self):
        """Save settings to disk."""
        try:
            # Ensure parent directory exists
            self._path.parent.mkdir(parents=True, exist_ok=True)

            # Write atomically
            tmp_path = self._path.with_suffix(".tmp")
            with open(tmp_path, "w", encoding="utf-8") as f:
                json.dump(self._data, f, ensure_ascii=False, indent=2)
            tmp_path.replace(self._path)

            self._dirty = False
        except Exception as e:
            log.error(f"Failed to save settings: {e}")

    def _start_auto_save(self):
        """Start background auto-save thread."""
        def _auto_save_loop():
            while True:
                import time
                time.sleep(self._auto_save_interval)
                with self._lock:
                    if self._dirty:
                        self._save()

        thread = threading.Thread(target=_auto_save_loop, daemon=True)
        thread.start()

    def get(self, key: str, default: Any = None) -> Any:
        """Get a setting value."""
        with self._lock:
            return self._data.get(key, default)

    def get_str(self, key: str, default: str = "") -> str:
        """Get a string setting."""
        val = self.get(key, default)
        return str(val) if val is not None else default

    def get_int(self, key: str, default: int = 0) -> int:
        """Get an integer setting."""
        val = self.get(key, default)
        try:
            return int(val)
        except (TypeError, ValueError):
            return default

    def get_float(self, key: str, default: float = 0.0) -> float:
        """Get a float setting."""
        val = self.get(key, default)
        try:
            return float(val)
        except (TypeError, ValueError):
            return default

    def get_bool(self, key: str, default: bool = False) -> bool:
        """Get a boolean setting."""
        val = self.get(key, default)
        if isinstance(val, bool):
            return val
        if isinstance(val, str):
            return val.lower() in ("true", "1", "yes", "on")
        return bool(val) if val is not None else default

    def get_list(self, key: str, default: list | None = None) -> list:
        """Get a list setting."""
        val = self.get(key, default or [])
        return val if isinstance(val, list) else default or []

    def set(self, key: str, value: Any):
        """Set a setting value. Auto-saves to disk."""
        with self._lock:
            self._data[key] = value
            self._dirty = True

    def set_many(self, pairs: dict[str, Any]):
        """Set multiple settings at once."""
        with self._lock:
            self._data.update(pairs)
            self._dirty = True

    def delete(self, key: str):
        """Delete a setting."""
        with self._lock:
            if key in self._data:
                del self._data[key]
                self._dirty = True

    def has(self, key: str) -> bool:
        """Check if a setting exists."""
        with self._lock:
            return key in self._data

    def keys(self) -> list[str]:
        """List all setting keys."""
        with self._lock:
            return list(self._data.keys())

    def items(self) -> dict[str, Any]:
        """Get all settings as a dict."""
        with self._lock:
            return dict(self._data)

    def save(self):
        """Force save to disk."""
        with self._lock:
            self._save()

    def reset(self):
        """Reset all settings to empty."""
        with self._lock:
            self._data = {}
            self._dirty = True

    def dump(self) -> str:
        """Dump all settings as JSON string."""
        with self._lock:
            return json.dumps(self._data, ensure_ascii=False, indent=2)


# ── Convenience singleton ──────────────────────────────────────────────

_global_settings: Optional[Settings] = None


def init_settings(path: str = "settings.json") -> Settings:
    """Initialize global settings."""
    global _global_settings
    _global_settings = Settings(path)
    return _global_settings


def get_settings() -> Settings:
    """Get global settings instance."""
    global _global_settings
    if _global_settings is None:
        _global_settings = Settings("settings.json")
    return _global_settings
