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


# ════════════════════════════════════════════════════════════════════
# БЛОК 2 — сценарии: потеря данных
# ════════════════════════════════════════════════════════════════════

class TestBlock2_UserCommands(unittest.TestCase):
    """Сценарии переживают уборку, счётчик — перезапуск, план — валидацию."""

    def setUp(self):
        import modules.user_commands as uc
        self.uc = uc
        self._tmpdir = tempfile.mkdtemp(prefix="sakura_fix_ucmd_")
        self._cmd_file = os.path.join(self._tmpdir, "user_commands.json")
        self._patcher = patch.object(uc, "COMMANDS_FILE", self._cmd_file)
        self._patcher.start()
        uc._pending_data = None
        uc._last_flush = 0.0

    def tearDown(self):
        self._patcher.stop()
        shutil.rmtree(self._tmpdir, ignore_errors=True)

    def _read(self):
        if not os.path.exists(self._cmd_file):
            return {}
        with open(self._cmd_file, encoding="utf-8") as f:
            return json.load(f)

    def _write(self, data):
        with open(self._cmd_file, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False)

    def test_scenario_survives_cleanup_auto(self):
        """2.2 + 2.3: осознанный сценарий с created_at не удаляется уборкой."""
        from datetime import datetime, timedelta
        self.assertTrue(self.uc.add("заводи мотор",
                                    {"action": "ext:start_motor"}, source="user"))
        self.uc.cleanup_auto(min_uses=2, older_days=0)
        data = self._read()
        self.assertIn("заводи мотор", data)
        # created_at проставлен автоматически и в ISO-формате
        created = data["заводи мотор"]["created_at"]
        datetime.fromisoformat(created)  # не бросит исключение = валидный ISO
        # старая auto-запись при этом удаляется
        old = (datetime.now() - timedelta(days=40)).isoformat()
        data["мотор"] = {"action": "x", "source": "auto", "uses": 1,
                         "created_at": old}
        self._write(data)
        removed = self.uc.cleanup_auto(min_uses=2, older_days=30)
        self.assertEqual(removed, 1)
        self.assertNotIn("мотор", self._read())
        self.assertIn("заводи мотор", self._read())

    def test_legacy_manual_survives_cleanup_auto(self):
        self.uc.add("старая команда", {"action": "a"}, source="manual")
        self.uc.cleanup_auto(min_uses=99, older_days=0)
        self.assertIn("старая команда", self._read())

    def test_uses_survive_reload(self):
        """2.1: счётчик uses переживает перезапуск (перезагрузку с диска)."""
        from datetime import datetime
        self._write({"мотор": {"action": "a", "source": "plan", "uses": 1,
                               "created_at": datetime.now().isoformat()}})
        self.assertIsNotNone(self.uc.match("мотор"))
        self.uc.flush_pending()          # как atexit при завершении процесса
        self.assertEqual(self._read()["мотор"]["uses"], 2)
        # второй матч после сброса буфера — снова +1
        self.assertIsNotNone(self.uc.match("мотор"))
        self.uc.flush_pending()
        self.assertEqual(self._read()["мотор"]["uses"], 3)

    def test_longest_trigger_wins(self):
        """2.4: «ну давай заводи мотор уже» → «заводи мотор», а не «мотор»."""
        self.uc.add("мотор", {"action": "short"})
        self.uc.add("заводи мотор", {"action": "long"})
        res = self.uc.match("ну давай заводи мотор уже")
        self.assertEqual(res["action"], "long")
        # точное совпадение по-прежнему приоритетнее частичного
        self.assertEqual(self.uc.match("мотор")["action"], "short")

    def test_invalid_plan_not_saved(self):
        """2.5: несуществующий примитив → команда не сохраняется."""
        ok = self.uc.add("сломанное", {
            "action": "run_plan",
            "plan": {"steps": [{"action": "несуществующий_примитив", "arg": ""}]},
        })
        self.assertFalse(ok)
        self.assertNotIn("сломанное", self._read())

    def test_too_many_steps_not_saved(self):
        steps = [{"action": "wait", "arg": "1"} for _ in range(10)]
        self.assertFalse(self.uc.add(
            "длинное", {"action": "run_plan", "plan": {"steps": steps}}))
        self.assertNotIn("длинное", self._read())

    def test_valid_plan_saved_with_risky_flag(self):
        self.assertTrue(self.uc.add("опасное", {
            "action": "run_plan",
            "plan": {"steps": [{"action": "powershell", "arg": "dir"}],
                     "summary": "каталог"},
        }, source="user"))
        entry = self._read()["опасное"]
        self.assertTrue(entry.get("risky"))
        self.assertEqual(entry.get("source"), "user")


# ════════════════════════════════════════════════════════════════════
# БЛОК 3 — TTS: отсебятина, язык, junk-фильтр, тег [ТОН:]
# ════════════════════════════════════════════════════════════════════

class TestBlock3_TTS(unittest.TestCase):

    def test_tone_tag_mid_text_and_lowercase(self):
        """3.4: тег в середине и в нижнем регистре вырезается."""
        from modules.tts_server import strip_tone
        emotion, clean = strip_tone("ну [тон: тихо] и что ты скажешь")
        self.assertEqual(emotion, "тихо")
        self.assertEqual(clean, "ну и что ты скажешь")
        self.assertNotIn("[ТОН", clean.upper())

    def test_tone_tag_multiple_occurrences(self):
        from modules.tts_server import strip_tone
        emotion, clean = strip_tone("[ТОН: насмешливо] Ну конечно [ТОН: тихо] господин")
        self.assertEqual(emotion, "насмешливо")
        self.assertEqual(clean, "Ну конечно господин")

    def test_tone_tag_start_kept_compatible(self):
        from modules.tts_server import _extract_tone_tag
        tone, text = _extract_tone_tag("[ТОН: мягко] Привет")
        self.assertEqual(tone, "мягко")
        self.assertEqual(text, "Привет")

    def test_main_strip_tone_removes_anywhere(self):
        import main
        self.assertEqual(main._strip_tone("текст [тон: хм] середина"), "текст середина")

    def test_junk_filter_keeps_meaningful_words(self):
        """3.3: «Google», «извините», «я не могу» в середине реплики не вырезаются."""
        from modules.tts_server import _clean_tts_text
        self.assertIn("Google", _clean_tts_text("Сейчас поищу в Google ответ"))
        self.assertIn("я не могу открыть", _clean_tts_text("К сожалению я не могу открыть гараж"))
        self.assertIn("извините", _clean_tts_text("Вы сказали извините дважды"))

    def test_junk_filter_strips_leading_leak_sentence(self):
        from modules.tts_server import _clean_tts_text
        result = _clean_tts_text("Извините, я не могу найти файл. Вот путь к нему.")
        self.assertNotIn("Извините", result)
        self.assertNotIn("не могу", result)
        self.assertIn("Вот путь", result)

    def test_junk_filter_identity_leak_everywhere(self):
        from modules.tts_server import _clean_tts_text
        result = _clean_tts_text("Привет, я Gemini и я помогу")
        self.assertNotIn("Gemini", result)

    def test_prefix_is_not_roleplay(self):
        """3.1: промпт — чистая инструкция озвучки без ролевой игры."""
        from modules.tts_server import _tts_prefix
        p = _tts_prefix("радостная")
        self.assertNotIn("актриса", p)
        self.assertNotIn("Сакуру", p)
        self.assertIn("Озвучь текст ниже", p)
        self.assertIn("радостная", p)

    def test_live_config_pins_language(self):
        """3.2: language_code зафиксирован."""
        from modules.tts_server import _live_config
        cfg = _live_config()
        sc = cfg.speech_config
        lang = getattr(sc, "language_code", None) or (sc.get("language_code") if isinstance(sc, dict) else None)
        self.assertEqual(lang, "ru-RU")
