"""
tests/test_intimacy_memory_filter.py — второй барьер: фильтрация интимного контента при извлечении фактов.

Даже если intimacy_mode не активен, факты с интимным содержимым
Не должны попадать в master_memory.

Run: python3 -m pytest tests/test_intimacy_memory_filter.py -q
"""
import os, sys
import unittest
from unittest.mock import patch

os.environ.setdefault("MASTER_ID", "123456789")
os.environ.setdefault("TELEGRAM_TOKEN", "test:fake-token")


class TestIntimacyMemoryFilter(unittest.TestCase):
    def test_intimate_fact_detected(self):
        from modules.intimacy_mode import is_intimate_content
        self.assertTrue(is_intimate_content("он любит секс по утрам"))
        self.assertTrue(is_intimate_content("она без одежды"))
        self.assertFalse(is_intimate_content("он любит кофе"))
        self.assertFalse(is_intimate_content("работает в Яндексе"))

    def test_guarded_add_blocks_intimate(self):
        from main import _guarded_add
        with patch("main.db_add_to_category") as mock_db:
            result = _guarded_add("preferences", "любит секс в постели")
            self.assertFalse(result)
            mock_db.assert_not_called()

    def test_guarded_add_saves_normal(self):
        from main import _guarded_add
        with patch("main.db_add_to_category", return_value=True) as mock_db:
            result = _guarded_add("preferences", "любит кофе по утрам")
            self.assertTrue(result)
            mock_db.assert_called_once_with("preferences", "любит кофе по утрам")

    def test_guarded_add_consume_check(self):
        from main import _guarded_add
        import modules.intimacy_mode as im
        im._reset_state()
        im.mark("секс")
        with patch("main.db_add_to_category") as mock_db:
            result = _guarded_add("preferences", "любит кофе")
            self.assertFalse(result)
            mock_db.assert_not_called()
        im._reset_state()


if __name__ == "__main__":
    unittest.main()
