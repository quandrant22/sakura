"""Гвардия против «потерянных при переносе» ссылок.

Класс бага повторился трижды: символ переезжает в другой модуль, а ссылка
на него остаётся указывать на старое место. Компилятор и ruff такое не
ловят — обращение по атрибуту разрешается только в рантайме.

  - modules/voice_info.py: is_master_device потерян при переносе
                           (определение живёт в modules/ws_auth.py)
  - modules/voice_info.py: steam_achievements_read вызывался как
                           _vi.steam_achievements_read из adapters/voice.py
                           (f753ee8) — определения в репозитории не было
  - adapters/commands.py:  main._START — константа переехала в
                           adapters/telegram.py (этап 7D-2)

Инвариант после сведения main.py к точке входа: main.py ничего не
ре-экспортирует, поэтому ``import main`` в коде проекта — висячая ссылка
(а ``main.<attr>`` разрешится только в рантайме, если ре-экспорт вернут).
"""

import os
import unittest
from unittest.mock import patch

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_SKIP_DIRS = {"venv", ".venv", ".git", "__pycache__", "node_modules", "docs"}


def _iter_sources():
    for dirpath, dirnames, filenames in os.walk(_ROOT):
        dirnames[:] = [d for d in dirnames if d not in _SKIP_DIRS]
        for name in filenames:
            if name.endswith(".py"):
                yield os.path.join(dirpath, name)


class TestMainIsEntryPointOnly(unittest.TestCase):
    """main.py — точка входа: его никто не импортирует."""

    def test_no_module_imports_main(self):
        offenders = []
        for path in _iter_sources():
            with open(path, encoding="utf-8") as fh:
                for lineno, line in enumerate(fh, 1):
                    stripped = line.strip()
                    # учитываем только реальные импорты, не упоминания в тексте
                    if (stripped.startswith("import main")
                            or stripped.startswith("from main import")):
                        rel = os.path.relpath(path, _ROOT)
                        offenders.append(f"{rel}:{lineno} {stripped}")
        self.assertEqual(
            offenders, [],
            "main.py сведён к точке входа и ничего не ре-экспортирует; "
            "импортируй реальный модуль:\n" + "\n".join(offenders))


class TestCrossModuleSymbols(unittest.TestCase):
    """Символы, однажды потерянные при переносе, должны резолвиться."""

    def test_steam_achievements_read_defined(self):
        import modules.voice_info as vi
        self.assertTrue(callable(vi.steam_achievements_read))

    def test_is_master_device_defined(self):
        import modules.ws_auth as auth
        self.assertTrue(callable(auth.is_master_device))

    def test_get_start_time_resolves_to_telegram(self):
        with patch("aiogram.Bot"):
            import adapters.commands as cmd
            from adapters import telegram as tg
        cmd._start_time = None          # сбросить кэш
        self.assertEqual(cmd._get_start_time(), tg._START)


if __name__ == "__main__":
    unittest.main()


class TestCrossModuleSymbols(unittest.TestCase):
    """Символы, однажды потерянные при переносе, должны резолвиться."""

    def test_steam_achievements_read_defined(self):
        import modules.voice_info as vi
        self.assertTrue(callable(vi.steam_achievements_read))

    def test_is_master_device_defined(self):
        import modules.ws_auth as auth
        self.assertTrue(callable(auth.is_master_device))

    def test_get_start_time_resolves_to_telegram(self):
        with patch("aiogram.Bot"):
            import adapters.commands as cmd
            from adapters import telegram as tg
        cmd._start_time = None          # сбросить кэш
        self.assertEqual(cmd._get_start_time(), tg._START)


if __name__ == "__main__":
    unittest.main()