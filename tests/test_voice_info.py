"""
Тесты голосовых информационных команд (modules/voice_info.py).

Run: python3 -m pytest tests/test_voice_info.py -q
Без сети; источники данных мокаются на границе модулей.
"""
import os
import sys
import asyncio
import unittest
from unittest.mock import patch, AsyncMock

os.environ.setdefault("MASTER_ID", "123456789")
os.environ.setdefault("TELEGRAM_TOKEN", "test:fake-token")
os.environ.setdefault("GEMINI_KEY_1", "fake-gemini-key")
os.environ.setdefault("WS_SECRET", "test-secret-minimum-16-chars")

_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _root not in sys.path:
    sys.path.insert(0, _root)


def _run(coro):
    return asyncio.get_event_loop().run_until_complete(coro)


class TestParsePeriod(unittest.TestCase):

    def test_known_periods(self):
        from datetime import date, timedelta
        from modules.voice_info import parse_period
        today = date.today()

        p = parse_period("вчера")
        self.assertEqual(p[0], today - timedelta(days=1))
        self.assertEqual(p[1], today)

        p = parse_period("сегодня")
        self.assertEqual(p[0], today)

        p = parse_period("на этой неделе")
        self.assertEqual(p[0], today - timedelta(days=today.weekday()))

        p = parse_period("за месяц")
        self.assertEqual((today - p[0]).days, 30)

    def test_unknown_period(self):
        from modules.voice_info import parse_period
        self.assertIsNone(parse_period("когда-нибудь потом"))


class TestSteamAchievements(unittest.TestCase):

    def test_period_data_formatted(self):
        """Главный кейс Мастера: «какие ачивки я получил вчера»."""
        from modules.voice_info import steam_achievements
        rows = [
            {"appid": 111, "apiname": "ach_first_blood", "ts": 1700000000},
            {"appid": 111, "apiname": "ach_explorer", "ts": 1700000100},
            {"appid": 222, "apiname": "ach_racer", "ts": 1700000200},
        ]
        lib = [{"appid": 111, "name": "Palworld"},
               {"appid": 222, "name": "Forza"}]
        achs111 = [{"apiname": "ach_first_blood", "name": "Первая кровь"},
                   {"apiname": "ach_explorer", "name": "Исследователь"}]
        achs222 = [{"apiname": "ach_racer", "name": "Гонщик"}]

        async def fake_achs(appid):
            return {111: achs111, 222: achs222}[appid]

        with patch("modules.voice_info._seen_unlocked_between", return_value=rows), \
             patch("modules.steam_integration.get_library", return_value=lib), \
             patch("modules.steam_integration.get_achievements", side_effect=fake_achs):
            text, ok = _run(steam_achievements("вчера"))

        self.assertTrue(ok)
        self.assertIn("Palworld", text)
        self.assertIn("Forza", text)
        self.assertIn("Первая кровь", text)   # человеческое имя из API
        self.assertNotIn("ach_first_blood", text)

    def test_period_empty_is_honest(self):
        from modules.voice_info import steam_achievements
        with patch("modules.voice_info._seen_unlocked_between", return_value=[]):
            text, ok = _run(steam_achievements("вчера"))
        self.assertTrue(ok)
        self.assertIn("новых ачивок нет", text.lower())

    def test_bad_unlocktime_skipped(self):
        """unlocked_at хранится строкой: пустое/мусор не превращаем в дату."""
        from modules.voice_info import _seen_unlocked_between
        rows = [
            {"appid": 1, "apiname": "a", "unlocked_at": ""},
            {"appid": 1, "apiname": "b", "unlocked_at": "не число"},
            {"appid": 1, "apiname": "c", "unlocked_at": "1700000000"},   # внутри
            {"appid": 1, "apiname": "d", "unlocked_at": "1600000000"},   # вне
        ]

        class FakeCursor:
            def fetchall(self):
                return rows

        class FakeConn:
            def execute(self, q, p=None):
                return FakeCursor()

        with patch("memory.db._conn", return_value=FakeConn()):
            out = _seen_unlocked_between(1650000000, 1750000000)
        self.assertEqual(len(out), 1)
        self.assertEqual(out[0]["apiname"], "c")

    def test_api_down_marks_honestly(self):
        """Steam API недоступен → коды остаются, но честно помечаем."""
        from modules.voice_info import steam_achievements
        rows = [{"appid": 111, "apiname": "ach_x", "ts": 1700000000}]

        async def fake_achs(appid):
            return []

        with patch("modules.voice_info._seen_unlocked_between", return_value=rows), \
             patch("modules.steam_integration.get_library",
                   return_value=[{"appid": 111, "name": "Palworld"}]), \
             patch("modules.steam_integration.get_achievements", side_effect=fake_achs):
            text, ok = _run(steam_achievements("сегодня"))
        self.assertIn("Palworld", text)
        self.assertIn("API ответил не полностью", text)


class TestSteamOtherCommands(unittest.TestCase):

    def test_current_no_game(self):
        import modules.steam_integration as si
        from modules.voice_info import steam_current
        with patch.object(si, "get_session_context", return_value=""), \
             patch.object(si, "_current_game", None):
            text, ok = _run(steam_current())
        self.assertTrue(ok)
        self.assertIn("не вижу запущенной игры", text.lower())

    def test_playtime_distinguishes_forever_and_2weeks(self):
        from modules.voice_info import steam_playtime
        game = {"appid": 1, "name": "Palworld",
                "playtime_forever": 3000, "playtime_2weeks": 120}
        with patch("modules.steam_integration.search_game", return_value=game):
            text, ok = _run(steam_playtime("palworld"))
        self.assertTrue(ok)
        self.assertIn("всего 50 ч", text)
        self.assertIn("за две недели — 2 ч", text)

    def test_playtime_zero_recent(self):
        from modules.voice_info import steam_playtime
        game = {"appid": 1, "name": "Hollow Knight",
                "playtime_forever": 600, "playtime_2weeks": 0}
        with patch("modules.steam_integration.search_game", return_value=game):
            text, ok = _run(steam_playtime("холлоу найт"))
        self.assertIn("всего 10 ч", text)
        self.assertIn("не играл(а)", text)

    def test_playtime_not_found(self):
        from modules.voice_info import steam_playtime
        with patch("modules.steam_integration.search_game", return_value=None):
            text, ok = _run(steam_playtime("несуществующая"))
        self.assertTrue(ok)
        self.assertIn("не нашла", text.lower())

    def test_progress_stats(self):
        from modules.voice_info import steam_progress
        game = {"appid": 7, "name": "Elden Ring"}
        stats = {"total": 42, "unlocked": 13, "percent": 31}
        with patch("modules.steam_integration.search_game", return_value=game), \
             patch("modules.steam_integration.get_achievement_stats",
                   new=AsyncMock(return_value=stats)):
            text, ok = _run(steam_progress("элден"))
        self.assertTrue(ok)
        self.assertIn("13 из 42", text)
        self.assertIn("31%", text)

    def test_progress_api_down_is_not_fake_empty(self):
        """Ключевое правило: API недоступен ≠ «данных нет»."""
        from modules.voice_info import steam_progress
        game = {"appid": 7, "name": "Elden Ring"}
        with patch("modules.steam_integration.search_game", return_value=game), \
             patch("modules.steam_integration.get_achievement_stats",
                   new=AsyncMock(return_value={})):
            text, ok = _run(steam_progress("элден"))
        self.assertFalse(ok)
        self.assertIn("не значит, что прогресса нет", text)

    def test_recent(self):
        from modules.voice_info import steam_recent
        games = [{"name": "Palworld", "playtime_2weeks": 300},
                 {"name": "Hades", "playtime_2weeks": 0}]
        with patch("modules.steam_integration.get_recently_played",
                   new=AsyncMock(return_value=games)):
            text, ok = _run(steam_recent())
        self.assertTrue(ok)
        self.assertIn("Palworld — 5 ч за две недели", text)
        self.assertIn("Hades", text)


class TestRouterInfoHardcode(unittest.TestCase):
    """Хардкод-матч информационных вопросов — без LLM, границы слов."""

    def test_achievements_yesterday(self):
        from modules.command_router import _hardcoded_match
        r = _hardcoded_match("какие ачивки я получил вчера?")
        self.assertIsNotNone(r)
        self.assertEqual(r["action"], "steam:achievements")
        self.assertEqual(r["arg"], "вчера")

    def test_achievements_month(self):
        from modules.command_router import _hardcoded_match
        r = _hardcoded_match("есть ачивки за месяц?")
        self.assertEqual(r["action"], "steam:achievements")
        self.assertEqual(r["arg"], "месяц")

    def test_achievements_word_boundary_negative(self):
        from modules.command_router import _hardcoded_match
        # «пачивки» содержит «ачивк» НЕ с начала слова — не матчим
        self.assertIsNone(_hardcoded_match("закажи пачивки чая"))

    def test_current_game(self):
        from modules.command_router import _hardcoded_match
        r = _hardcoded_match("во что я сейчас играю")
        self.assertEqual(r["action"], "steam:current")

    def test_recent_games(self):
        from modules.command_router import _hardcoded_match
        r = _hardcoded_match("во что я играл недавно")
        self.assertEqual(r["action"], "steam:recent")

    def test_playtime_with_game(self):
        from modules.command_router import _hardcoded_match
        r = _hardcoded_match("сколько я наиграл в палворлд")
        self.assertEqual(r["action"], "steam:playtime")
        self.assertEqual(r["arg"], "палворлд")

    def test_smalltalk_still_null(self):
        from modules.command_router import _hardcoded_match
        self.assertIsNone(_hardcoded_match("как дела"))
        self.assertIsNone(_hardcoded_match("привет"))


class TestVpsVoice(unittest.TestCase):

    def test_status_with_metrics(self):
        from modules.voice_info import vps_status
        m = {"cpu": 23.4, "ram": 61.0, "disk": 48.2, "disk_free": 21, "uptime": "3 дня"}
        with patch("modules.vps_monitor.get_metrics", return_value=m):
            text, ok = _run(vps_status())
        self.assertTrue(ok)
        self.assertIn("CPU 23%", text)
        self.assertIn("RAM 61%", text)
        self.assertIn("свободно 21 ГБ", text)

    def test_status_no_metrics_yet_is_honest(self):
        from modules.voice_info import vps_status
        with patch("modules.vps_monitor.get_metrics", return_value={}):
            text, ok = _run(vps_status())
        self.assertFalse(ok)
        self.assertIn("ещё не собрал", text)

    def test_feeling_normal_is_calm_answer(self):
        from modules.voice_info import vps_feeling
        with patch("modules.vps_monitor.get_body_feeling", return_value=""):
            text, ok = _run(vps_feeling())
        self.assertTrue(ok)
        self.assertIn("спокойно", text)

    def test_router_server_status(self):
        from modules.command_router import _hardcoded_match
        r = _hardcoded_match("как сервер?")
        self.assertEqual(r["action"], "vps:status")
        r = _hardcoded_match("какая сейчас нагрузка на систему")
        self.assertEqual(r["action"], "vps:status")
        r = _hardcoded_match("как твоё самочувствие")
        self.assertEqual(r["action"], "vps:feeling")
