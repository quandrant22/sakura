"""
Regression tests for the bugfix batch (blocks 1-8).

Run:  python3 -m pytest tests/test_fixes.py -q

No network, temp files only.
"""
import os
import sys
import json
import asyncio
import tempfile
import shutil
import unittest
from unittest.mock import patch, MagicMock, AsyncMock

# ── Env stubs (must be set before any project imports) ──────────────
os.environ.setdefault("MASTER_ID", "123456789")
os.environ.setdefault("TELEGRAM_TOKEN", "test:fake-token")
os.environ.setdefault("GEMINI_KEY_1", "fake-gemini-key")
os.environ.setdefault("WS_SECRET", "test-secret-minimum-16-chars")
os.environ.setdefault("MASTER_DEVICES", "laptop,pc")

_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _root not in sys.path:
    sys.path.insert(0, _root)


def _run(coro):
    return asyncio.get_event_loop().run_until_complete(coro)


# ════════════════════════════════════════════════════════════════════
# БЛОК 1 — боевые падения
# ════════════════════════════════════════════════════════════════════

class TestBlock1_NoNameErrors(unittest.TestCase):
    """1.1: send_telegram_text не падает для не-Мастера."""

    def test_send_telegram_text_non_master(self):
        with patch("aiogram.Bot"):
            import main
            with patch.object(main, "bot", MagicMock()) as bot:
                _run(main.send_telegram_text(999, "[ТОН: мягко] Привет, гость"))
                bot.send_message.assert_called_once_with(999, "Привет, гость")

    def test_send_telegram_text_master(self):
        with patch("aiogram.Bot"):
            import main
            with patch.object(main, "bot", MagicMock()) as bot:
                _run(main.send_telegram_text(123456789, "[ТОН: мягко] Привет"))
                bot.send_message.assert_called_once_with(123456789, "Привет")


class TestBlock1_GameContext(unittest.TestCase):
    """1.2: игровой контекст попадает в промпт (раньше NameError)."""

    def test_ask_gemini_includes_game_context(self):
        import main
        hit = {"appid": 111, "name": "Palworld", "playtime_forever": 300}
        gen_mock = AsyncMock(return_value=MagicMock(text="ок"))

        with patch("main.search_game", return_value=hit), \
             patch("modules.steam_integration._current_game",
                   {"appid": 222, "name": "Другая игра"}), \
             patch("main.get_active_key", return_value="fake-key"), \
             patch("main._gemini_generate", gen_mock), \
             patch("main.maybe_fetch_web", new=AsyncMock(return_value=None)), \
             patch("main.maybe_read_url", new=AsyncMock(return_value=None)), \
             patch("main._build_system", return_value="SYS"):
            reply = _run(main.ask_gemini("как дела в Palworld?", save_history=False))

        self.assertTrue(reply)
        # full_system передаётся вторым позиционным аргументом _gemini_generate
        args, kwargs = gen_mock.call_args
        full_system = args[3] if len(args) >= 4 else kwargs.get("full_system")
        self.assertIn("ИГРА ИЗ БИБЛИОТЕКИ МАСТЕРА", full_system)
        self.assertIn("Palworld", full_system)

    def test_ask_gemini_skips_current_game(self):
        """Если спрошенная игра уже запущена — контекст библиотеки не добавляется."""
        import main
        hit = {"appid": 111, "name": "Palworld", "playtime_forever": 300}
        gen_mock = AsyncMock(return_value=MagicMock(text="ок"))

        with patch("main.search_game", return_value=hit), \
             patch("modules.steam_integration._current_game",
                   {"appid": 111, "name": "Palworld"}), \
             patch("main.get_active_key", return_value="fake-key"), \
             patch("main._gemini_generate", gen_mock), \
             patch("main.maybe_fetch_web", new=AsyncMock(return_value=None)), \
             patch("main.maybe_read_url", new=AsyncMock(return_value=None)), \
             patch("main._build_system", return_value="SYS"):
            _run(main.ask_gemini("как дела в Palworld?", save_history=False))

        args, kwargs = gen_mock.call_args
        full_system = args[3] if len(args) >= 4 else kwargs.get("full_system")
        self.assertNotIn("ИГРА ИЗ БИБЛИОТЕКИ МАСТЕРА", full_system)
