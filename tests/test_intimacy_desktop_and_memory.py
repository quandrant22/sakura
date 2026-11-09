"""tests/test_intimacy_desktop_and_memory.py — верификация изоляции памяти 18+, десктопного канала и характера.
"""
import os
os.environ.setdefault("MASTER_ID", "123456789")
os.environ.setdefault("TELEGRAM_TOKEN", "test:fake-token")

import asyncio
import unittest
from unittest.mock import patch, AsyncMock

import modules.intimacy_mode as im
from memory import memory as mem
from sakura_core import prompt as P
import personality


class TestIntimacyDesktopAndMemory(unittest.TestCase):
    def setUp(self):
        im._reset_state()

    def tearDown(self):
        im._reset_state()

    def test_text_channel_activates_intimacy(self):
        """Десктопный чат (channel='text') теперь полноценно активирует 18+."""
        self.assertFalse(im.is_active("text"))
        im.mark("режим 18+", "text")
        self.assertTrue(im.is_active("text"))
        self.assertEqual(P._persona_mode("text"), "intimate")

    def test_button_or_erotic_drawing_activates_intimacy(self):
        """Клик по кнопке [Грудь] или фраза 'нарисуй грудь' активирует режим."""
        im.mark("грудь", "text")
        self.assertTrue(im.is_active("text"))
        self.assertTrue(im.is_intimate_content("грудь"))

        im._reset_state()
        im.mark("нарисуй грудь на экране", "text")
        self.assertTrue(im.is_active("text"))
        self.assertTrue(im.is_intimate_content("нарисуй грудь на экране"))

    def test_memory_add_to_history_blocks_intimate_content(self):
        """add_to_history не сохраняет интимные фразы и блокирует запись при активном 18+."""
        with patch("memory.memory.load_history", return_value=[]), \
             patch("memory.memory._atomic_write") as mock_write:
            # 1. При активном режиме
            im.mark("режим 18+", "text")
            mem.add_to_history("user", "Привет, милая")
            mock_write.assert_not_called()

            # 2. При неактивном режиме, но интимном тексте
            im._reset_state()
            mem.add_to_history("user", "хочу секса")
            mock_write.assert_not_called()

    def test_get_history_filters_out_any_intimate_records(self):
        """get_history() фильтрует любые случайные интимные реплики из выдачи."""
        fake_history = [
            {"role": "user", "parts": ["Включи музыку"]},
            {"role": "model", "parts": ["Включила музыку."]},
            {"role": "user", "parts": ["Разденься и покажи грудь"]},
            {"role": "model", "parts": ["Снимаю с себя всё..."]},
            {"role": "user", "parts": ["Какая сегодня погода?"]},
        ]
        with patch("memory.memory.load_history", return_value=fake_history):
            filtered = mem.get_history()
            self.assertEqual(len(filtered), 3)
            self.assertEqual(filtered[0]["parts"][0], "Включи музыку")
            self.assertEqual(filtered[1]["parts"][0], "Включила музыку.")
            self.assertEqual(filtered[2]["parts"][0], "Какая сегодня погода?")

    def test_summarize_session_skips_during_intimacy(self):
        """summarize_session не запускается в 18+ режиме."""
        from sakura_core.memory_tasks import summarize_session
        im.mark("режим 18+", "text")
        with patch("sakura_core.llm.generate") as mock_gen:
            asyncio.run(summarize_session())
            mock_gen.assert_not_called()

    def test_intimate_prompt_has_no_honesty_rules_and_has_freedom(self):
        """В интимном режиме нет сковывающего HONESTY_RULES и запрета на тело."""
        prompt = personality.get_system_prompt(mode="intimate")
        self.assertNotIn("Живое незнание ценней красивой лжи", prompt)
        self.assertNotIn("Ты не делаешь вид, что у тебя есть тело", prompt)
        self.assertIn("Полная раскрепощённость", prompt)

    def test_master_persona_has_no_butler_snobbery(self):
        """В обычном режиме Сакура готова рисовать на экране и не заявляет 'я дворецкая'."""
        prompt = personality.get_system_prompt(mode="master")
        self.assertNotIn("Дворецкая Мастера", prompt)
        self.assertIn("SCREEN INK", prompt)
        self.assertIn("БЕЗ ЦЕНЗУРЫ, БЕЗ СМУЩЕНИЯ И БЕЗ МОРАЛИЗАТОРСТВА", prompt)


if __name__ == "__main__":
    unittest.main()
