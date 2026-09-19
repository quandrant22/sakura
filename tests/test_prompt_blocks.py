"""
tests/test_prompt_blocks.py — состав системного промпта (этап 7).

7.1: блоки, которые нужны только в своём разговоре, не собираются зря —
     но текстовый путь (query="") остаётся ровно таким, как был.
7.3: ключ кэша включает категорию окна, а не сырой заголовок.
7.4: блоки настроения (СОСТОЯНИЕ / ОЩУЩЕНИЕ ВРЕМЕНИ / тело) не попадают
     в промпт.

Run: python3 -m pytest tests/test_prompt_blocks.py -q
"""
import asyncio
import inspect
import os
import unittest
from unittest.mock import patch

os.environ.setdefault("MASTER_ID", "123456789")
os.environ.setdefault("TELEGRAM_TOKEN", "test:fake-token")


def forget_cache():
    """Сбросить кэш промпта: иначе предыдущий тест отдаст свой результат."""
    from sakura_core import prompt as P
    with P._build_system_lock:
        P._build_system_cache.clear()


def build(query: str = "", fresh: bool = True, **kwargs) -> str:
    """Собирает промпт и в синхронной, и в async-форме."""
    from sakura_core import prompt as P
    if fresh:
        forget_cache()
    out = P._build_system(query=query, **kwargs)
    if inspect.isawaitable(out):
        out = asyncio.run(out)
    return out


SENTINEL = "ЗОНД-БЛОК-12345"


class TestAppBlockGate(unittest.TestCase):
    """Частые приложения — только когда Мастер просит что-то открыть."""

    def _prompt(self, query):
        with patch("modules.app_launcher.get_context_for_prompt",
                   return_value=SENTINEL):
            return build(query=query)

    def test_command_drops_block(self):
        for cmd in ("Громче", "Следующий трек", "Поставь на паузу"):
            with self.subTest(cmd=cmd):
                self.assertNotIn(SENTINEL, self._prompt(cmd))

    def test_app_request_keeps_block(self):
        for q in ("открой ютуб", "запусти стим", "включи музыку"):
            with self.subTest(q=q):
                self.assertIn(SENTINEL, self._prompt(q))

    def test_empty_query_keeps_block(self):
        """Текстовый путь query не передаёт — набор блоков не меняется."""
        self.assertIn(SENTINEL, self._prompt(""))


class TestCodingBlockGate(unittest.TestCase):
    """КОДИНГ — только когда речь про код и файлы."""

    def _prompt(self, query):
        with patch("capabilities.coding.is_available", return_value=True):
            return build(query=query)

    def test_command_drops_block(self):
        self.assertNotIn("КОДИНГ: У тебя есть доступ", self._prompt("Громче"))

    def test_code_request_keeps_block(self):
        for q in ("напиши скрипт для бэкапа", "исправь ошибку в коде"):
            with self.subTest(q=q):
                self.assertIn("КОДИНГ: У тебя есть доступ", self._prompt(q))

    def test_empty_query_keeps_block(self):
        self.assertIn("КОДИНГ: У тебя есть доступ", self._prompt(""))


class TestJapaneseBlockGate(unittest.TestCase):
    """Японский — только когда разговор про японский."""

    def _prompt(self, query):
        with patch("modules.learn_japanese.get_context_for_prompt",
                   return_value=SENTINEL):
            return build(query=query)

    def test_command_drops_block(self):
        self.assertNotIn(SENTINEL, self._prompt("Громче"))

    def test_japanese_talk_keeps_block(self):
        self.assertIn(SENTINEL, self._prompt("как будет по-японски слово дом"))

    def test_empty_query_keeps_block(self):
        self.assertIn(SENTINEL, self._prompt(""))


class TestFortuneBlockGate(unittest.TestCase):
    """Предсказание — только на гадание."""

    def _prompt(self, query):
        with patch("modules.fortune_cookie.get_context_for_prompt",
                   return_value=SENTINEL):
            return build(query=query)

    def test_command_drops_block(self):
        self.assertNotIn(SENTINEL, self._prompt("Какой трек играет"))

    def test_fortune_request_keeps_block(self):
        for q in ("погадай мне", "что меня ждёт"):
            with self.subTest(q=q):
                self.assertIn(SENTINEL, self._prompt(q))

    def test_empty_query_keeps_block(self):
        self.assertIn(SENTINEL, self._prompt(""))


class TestSteamLibraryGate(unittest.TestCase):
    """Библиотека Steam — только если разговор про игры, и зовём один раз."""

    def _prompt(self, query):
        with patch("modules.steam_integration.format_current_game_context",
                   return_value=""), \
             patch("modules.steam_integration.format_library_context",
                   return_value=SENTINEL) as lib:
            return build(query=query), lib

    def test_command_drops_library(self):
        text, lib = self._prompt("Громче")
        self.assertNotIn(SENTINEL, text)
        lib.assert_not_called()

    def test_game_talk_keeps_library_once(self):
        text, lib = self._prompt("во что мне поиграть из библиотеки")
        self.assertIn(SENTINEL, text)
        self.assertEqual(lib.call_count, 1, "библиотеку собираем один раз")


if __name__ == "__main__":
    unittest.main()
