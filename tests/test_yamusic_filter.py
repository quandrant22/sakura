"""
Тесты фикса SMTC-фильтра Яндекс Музыки (agent/core/yamusic_app.py)
и проверки зависимостей при старте (agent/core/dep_check.py).

Реальный кейс с машины Мастера:
    'opera.exe'         | ютуб-ролик
    'Яндекс Музыка.exe' | Miku and Friends - Bad Apple!!
AUMID кириллицей → фильтр 'yandex'/'music' латиницей не срабатывал.

Run: python3 -m pytest tests/test_yamusic_filter.py -q
"""
import os
import sys
import unittest
from unittest.mock import MagicMock, patch

_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _root not in sys.path:
    sys.path.insert(0, _root)


class TestYandexMusicAumidMatcher(unittest.TestCase):
    """is_yandex_music_aumid(): кириллица, латиница, транслит, браузеры."""

    def _matcher(self):
        from agent.core.yamusic_app import is_yandex_music_aumid
        return is_yandex_music_aumid

    def test_real_master_aumid_cyrillic(self):
        """Реальный AUMID 'Яндекс Музыка.exe' (кириллица) — совпадает."""
        self.assertTrue(self._matcher()("Яндекс Музыка.exe"))

    def test_latin_variants(self):
        m = self._matcher()
        self.assertTrue(m("Yandex.Music"))
        self.assertTrue(m("yandexmusic.exe"))
        self.assertTrue(m("YANDEX MUSIC.EXE"))  # регистронезависимо

    def test_translit_variants(self):
        """Транслит: 'яндекс'→'yandeks' (кс→x), 'музыка'→'muzyka'."""
        m = self._matcher()
        self.assertTrue(m("yandeks muzyka.exe"))
        self.assertTrue(m("YANDEKS-MUZYKA"))

    def test_browsers_not_matched(self):
        """Браузеры НЕ матчим — пауза не должна уходить в ютуб."""
        m = self._matcher()
        for aumid in ("opera.exe", "Opera.exe", "chrome.exe",
                      "msedge.exe", "firefox.exe", "Яндекс Браузер.exe"):
            self.assertFalse(m(aumid), aumid)

    def test_other_apps_not_matched(self):
        m = self._matcher()
        self.assertFalse(m(""))
        self.assertFalse(m(None))
        self.assertFalse(m("Spotify.exe"))
        self.assertFalse(m("explorer.exe"))

    def test_generic_music_token_matches(self):
        """Вариант 'music' из ТЗ тоже матчится (после yandex-токенов)."""
        self.assertTrue(self._matcher()("Music.Player.exe"))


class TestSessionMatcher(unittest.TestCase):
    """_match_yamusic_session(): выбор среди нескольких SMTC-сессий."""

    def _make_session(self, aumid):
        s = MagicMock()
        s.source_app_user_model_id = aumid
        return s

    def test_picks_yamusic_not_opera(self):
        """Из сессий [opera.exe, Яндекс Музыка.exe] выбирается Яндекс Музыка."""
        from agent.core.yamusic_app import _match_yamusic_session
        opera = self._make_session("opera.exe")
        yamusic = self._make_session("Яндекс Музыка.exe")
        picked = _match_yamusic_session([opera, yamusic])
        self.assertIs(picked, yamusic)

    def test_opera_only_returns_none(self):
        from agent.core.yamusic_app import _match_yamusic_session
        self.assertIsNone(_match_yamusic_session([self._make_session("opera.exe")]))

    def test_session_without_aumid_skipped(self):
        from agent.core.yamusic_app import _match_yamusic_session
        broken = MagicMock(spec=[])  # нет source_app_user_model_id
        good = self._make_session("Yandex.Music")
        self.assertIs(_match_yamusic_session([broken, good]), good)





class TestDepCheck(unittest.TestCase):
    """check_critical_packages(): явные [agent]-предупреждения."""

    def test_missing_package_logged_as_agent_warning(self):
        """Отсутствующий пакет → '[agent] winsdk не установлен — ...'."""
        from agent.core import dep_check
        # winsdk на Linux отсутствует всегда — но промокаем для детерминизма
        with patch("agent.core.dep_check.importlib.import_module",
                   side_effect=lambda name: (_ for _ in ()).throw(
                       ImportError(name))) as imp:
            with self.assertLogs("sakura.agent", level="WARNING") as cm:
                missing = dep_check.check_critical_packages(force=True)
        self.assertIn("winsdk", missing)
        joined = "\n".join(cm.output)
        self.assertIn("[agent] winsdk не установлен — управление музыкой недоступно",
                      joined)
        imp.assert_any_call("winsdk")

    def test_all_present_no_warnings(self):
        from agent.core import dep_check
        with patch("agent.core.dep_check.importlib.import_module",
                   return_value=MagicMock()):
            with self.assertNoLogs("sakura.agent", level="WARNING"):
                missing = dep_check.check_critical_packages(force=True)
        self.assertEqual(missing, [])


if __name__ == "__main__":
    unittest.main()
