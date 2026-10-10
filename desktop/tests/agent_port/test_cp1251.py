import builtins
import locale
import sys
from pathlib import Path

AGENT_DIR = Path(__file__).resolve().parents[2]
if str(AGENT_DIR) not in sys.path:
    sys.path.insert(0, str(AGENT_DIR))

from desktop.core.commands import CommandRegistry, load_builtin_commands


def test_load_builtin_commands_with_cp1251_default_encoding(monkeypatch):
    """Windows ANSI locale must not break built-in command TOML parsing."""
    real_open = builtins.open

    def fake_open(*args, **kwargs):
        mode = "r"
        if args:
            mode = str(args[1]) if len(args) > 1 else mode
        if "b" not in mode and "encoding" not in kwargs:
            kwargs["encoding"] = "cp1251"
        return real_open(*args, **kwargs)

    monkeypatch.setattr(locale, "getpreferredencoding", lambda do_setlocale=True: "cp1251")
    monkeypatch.setattr(builtins, "open", fake_open)

    registry = CommandRegistry()
    load_builtin_commands(registry)

    assert registry._commands
    assert any(cmd.id == "remember_app" for cmd in registry._commands)
