"""
tests/test_memory_forget.py — «забудь про Х»: подтверждение обязательно,
удаление только после «да»; слово «достижение» = «ачивка».

Run: python3 -m pytest tests/test_memory_forget.py -q
"""
import os
import unittest
from unittest.mock import patch

os.environ.setdefault("MASTER_ID", "123456789")
os.environ.setdefault("TELEGRAM_TOKEN", "test:fake-token")


class TestForgetRouting(unittest.TestCase):

    def test_zabud_routes_to_memory_forget(self):
        from modules.command_router import _hardcoded_match
        r = _hardcoded_match("забудь про мой старый ник")
        self.assertIsNotNone(r)
        self.assertEqual(r["action"], "memory:forget")
        self.assertIn("ник", r["arg"])

    def test_udali_iz_pamyati_routes(self):
        from modules.command_router import _hardcoded_match
        r = _hardcoded_match("удали из памяти мою оценку за фильм")
        self.assertIsNotNone(r)
        self.assertEqual(r["action"], "memory:forget")

    def test_udali_file_does_not_route_to_forget(self):
        """«удали файл» — не про память, не должен уходить в memory:forget."""
        from modules.command_router import _hardcoded_match
        r = _hardcoded_match("удали файл отчёт")
        if r is not None:
            self.assertNotEqual(r["action"], "memory:forget")

    def test_ne_zabud_is_not_forget(self):
        """«не забудь про встречу» — напоминание, не забывание."""
        from modules.command_router import _hardcoded_match
        r = _hardcoded_match("не забудь про встречу завтра")
        if r is not None:
            self.assertNotEqual(r["action"], "memory:forget")


class TestForgetConfirmation(unittest.TestCase):
    """Удаление — только после «да». Без подтверждения ничего не удаляется."""

    def setUp(self):
        import modules.voice_info as vi
        vi._pending_forget = None

    def tearDown(self):
        import modules.voice_info as vi
        vi._pending_forget = None

    def test_forget_requires_confirmation(self):
        """memory_forget показывает найденное и НЕ удаляет."""
        rows = [{"id": 1, "category": "facts", "text": "тестовая запись"},
                {"id": 2, "category": "notes", "text": "вторая запись"}]
        import modules.voice_info as vi
        with patch("memory.db.find_memories", return_value=rows), \
             patch("memory.db.delete_memory") as mock_del:
            text, ok = vi.memory_forget("тестовая")
            # pending создан
            self.assertTrue(vi.pending_forget_active())
            # удаление НЕ вызывалось
            mock_del.assert_not_called()
            self.assertIn("Удалить", text)

    def test_da_deletes(self):
        """«да» после запроса — удаление."""
        import modules.voice_info as vi
        vi._pending_forget = {"ids": [11, 12], "pattern": "тест", "ts": vi._now()}
        with patch("memory.db.delete_memory", return_value=True) as mock_del:
            text, ok = vi.memory_forget_confirm("да")
            self.assertEqual(mock_del.call_count, 2)
            self.assertIn("удалено 2", text)
            # pending сброшен
            self.assertFalse(vi.pending_forget_active())

    def test_net_cancels(self):
        """«нет» — ничего не удаляется."""
        import modules.voice_info as vi
        vi._pending_forget = {"ids": [11], "pattern": "тест", "ts": vi._now()}
        with patch("memory.db.delete_memory") as mock_del:
            text, ok = vi.memory_forget_confirm("нет")
            mock_del.assert_not_called()
            self.assertIn("оставила", text.lower())

    def test_topic_change_cancels(self):
        """Смена темы — отмена подтверждения, реплика идёт обычным путём."""
        import modules.voice_info as vi
        vi._pending_forget = {"ids": [11], "pattern": "тест", "ts": vi._now()}
        result = vi.memory_forget_confirm("какая погода")
        self.assertIsNone(result)
        self.assertFalse(vi.pending_forget_active())

    def test_no_pending_returns_none(self):
        import modules.voice_info as vi
        self.assertIsNone(vi.memory_forget_confirm("да"))


class TestDostizhenieRouting(unittest.TestCase):
    """Слово «достижение» работает как «ачивка»."""

    def _route(self, phrase):
        from modules.command_router import _hardcoded_match
        return _hardcoded_match(phrase)

    def test_dostizheniya(self):
        r = self._route("достижения")
        self.assertEqual(r["action"], "steam:achievements")

    def test_kakie_dostizheniya_poluchil(self):
        r = self._route("какие достижения я получил")
        self.assertEqual(r["action"], "steam:achievements")

    def test_poslednee_dostizhenie_period(self):
        r = self._route("последнее достижение")
        self.assertEqual(r["action"], "steam:achievements")
        self.assertEqual(r["arg"], "последняя")

    def test_za_mesjac(self):
        r = self._route("достижения за месяц")
        self.assertEqual(r["action"], "steam:achievements")
        self.assertEqual(r["arg"], "месяц")

    def test_moi_dostizheniya_v_igre(self):
        r = self._route("мои достижения в игре")
        self.assertEqual(r["action"], "steam:achievements")

    def test_intents_prompt_has_dostizhenie(self):
        from modules.command_router import INTENTS_PROMPT
        self.assertIn("достижени", INTENTS_PROMPT)

    def test_word_boundary(self):
        """«поддостижения»-подобные подстроки не матчатся."""
        from modules.command_router import _hardcoded_match
        r = self._route("недостижения не существует такого слова")
        if r is not None:
            # если вдруг сработало — не через ачивки
            self.assertNotEqual(r.get("action"), "steam:achievements")


if __name__ == "__main__":
    unittest.main()
