"""
Тесты голосовых информационных команд (modules/voice_info.py).

Run: python3 -m pytest tests/test_voice_info.py -q
Без сети; источники данных мокаются на границе модулей.
"""
import os
import sys
import time
import asyncio
import unittest
from unittest.mock import patch, MagicMock, AsyncMock

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

    def setUp(self):
        import modules.voice_info as vi
        self.vi = vi
        vi._ach_query_cache.clear()   # свежий кэш между тестами

    def _patch_candidates(self, games):
        """Мок _candidate_games → [(appid, name)] + {appid: name}."""
        names = {a: n for a, n in games}
        return patch("modules.voice_info._candidate_games",
                     new=AsyncMock(return_value=(games, names)))

    def test_period_data_formatted_from_api(self):
        """Главный кейс: ачивки за период из Steam API (не из seen-таблицы)."""
        from modules.voice_info import steam_achievements
        games = [(617290, "Remnant: From the Ashes"),
                 (1282100, "Remnant II")]
        now = int(time.time())
        achs617 = [
            {"apiname": "r1_a", "name": "Первый", "achieved": 1,
             "unlocktime": now - 3600},          # 1 час назад — в окне «неделя»
            {"apiname": "r1_b", "name": "Старый", "achieved": 1,
             "unlocktime": now - 90 * 86400},    # 90 дней назад — вне
            {"apiname": "r1_c", "name": "Невыбито", "achieved": 0,
             "unlocktime": 0},
        ]
        achs128 = [{"apiname": "r2_a", "name": "Второй", "achieved": 1,
                    "unlocktime": now - 2 * 3600}]

        async def fake_achs(appid):
            return {617290: (achs617, "ok"), 1282100: (achs128, "ok")}[appid]

        with self._patch_candidates(games), \
             patch("modules.steam_integration._fetch_achievements",
                   side_effect=fake_achs):
            text, ok = _run(steam_achievements("неделя"))

        self.assertTrue(ok)
        self.assertIn("Remnant: From the Ashes", text)
        self.assertIn("«Первый»", text)             # из API, человеческое имя
        self.assertIn("«Второй»", text)
        self.assertNotIn("Старый", text)            # вне периода не попал
        self.assertNotIn("r1_a", text)              # не код, а имя

    def test_period_empty_is_honest(self):
        """Проверка прошла, ачивок не было → ok=True, «достижений нет»."""
        from modules.voice_info import steam_achievements
        with self._patch_candidates([(617290, "Remnant")]), \
             patch("modules.steam_integration._fetch_achievements",
                   new=AsyncMock(return_value=([], "ok"))):
            text, ok = _run(steam_achievements("неделя"))
        self.assertTrue(ok)
        self.assertIn("достижений нет", text)

    def test_no_period_defaults_to_week(self):
        from modules.voice_info import steam_achievements, _default_period_word
        self.assertEqual(_default_period_word(""), "неделя")
        with self._patch_candidates([(5778, "X")]), \
             patch("modules.steam_integration._fetch_achievements",
                   new=AsyncMock(return_value=([], True))):
            text, ok = _run(steam_achievements(""))
        self.assertTrue(ok)

    def test_no_candidates_is_honest_success(self):
        """Кандидатов (не в кого играть) нет → ok=True, не «Steam недоступен»."""
        from modules.voice_info import steam_achievements
        with self._patch_candidates([]), \
             patch("modules.voice_info._seen_unlocked_between", return_value=[]):
            text, ok = _run(steam_achievements("неделя"))
        self.assertTrue(ok)
        self.assertIn("достижений нет", text)

    def test_api_down_fallback_and_honest_fail(self):
        """API недоступен по всем кандидатам и кэша нет → ok=False."""
        from modules.voice_info import steam_achievements
        async def down(appid):
            return None, "steam_down"
        with self._patch_candidates([(617290, "Remnant")]), \
             patch("modules.steam_integration._fetch_achievements",
                   side_effect=down), \
             patch("modules.voice_info._seen_unlocked_between", return_value=[]):
            text, ok = _run(steam_achievements("неделя"))
        self.assertFalse(ok)
        self.assertIn("Steam недоступен", text)

    def test_api_down_uses_local_cache_with_note(self):
        """API недоступен, но seen-таблица есть → отдаём её с пометкой."""
        from modules.voice_info import steam_achievements
        seats = [{"appid": 617290, "apiname": "Кеш-ачивка", "ts": int(time.time())}]
        async def fake(appid):
            return None, "steam_down"
        with self._patch_candidates([(617290, "Remnant")]), \
             patch("modules.steam_integration._fetch_achievements", side_effect=fake), \
             patch("modules.voice_info._seen_unlocked_between", return_value=seats):
            text, ok = _run(steam_achievements("неделя"))
        self.assertTrue(ok)
        self.assertIn("Кеш-ачивка", text)
        self.assertIn("могут быть неполными", text)

    def test_parts_of_speech_formatted(self):
        """Формат времени: «вчера в 22:14», «сегодня в 09:03»."""
        from modules.voice_info import _fmt_unlock_ts
        from datetime import datetime as _dt, timedelta as _td
        now = int(time.time())
        y_ts = int(_dt.fromtimestamp(now).replace(hour=22, minute=14,
                                                  second=0, microsecond=0)
                   .timestamp()) - 86400
        self.assertIn("вчера в 22:14", _fmt_unlock_ts(y_ts))

    def test_all_time_summary(self):
        """«всё время» → сводка из локального журнала без десятков вызовов."""
        from modules.voice_info import steam_achievements
        rows = [{"appid": 617290, "n": 12}, {"appid": 3812600, "n": 10}]
        lib = [{"appid": 617290, "name": "Remnant", "playtime_forever": 100},
               {"appid": 3812600, "name": "ReStory", "playtime_forever": 200}]

        class FakeCursor:
            def fetchall(self):
                return rows

        class FakeConn:
            def execute(self, q, p=None):
                return FakeCursor()

        with patch("modules.voice_info._candidate_games",
                   new=AsyncMock(return_value=([], {}))), \
             patch("memory.db._conn", return_value=FakeConn()), \
             patch("modules.steam_integration.get_library", return_value=lib):
            text, ok = _run(steam_achievements("всё"))
        self.assertTrue(ok)
        self.assertIn("22 достижения", text)
        self.assertIn("Remnant: 12", text)
        self.assertIn("ReStory: 10", text)


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

    def test_achievements_all_time_phrases(self):
        from modules.command_router import _hardcoded_match
        for phrase in ("сколько у меня ачивок всего",
                       "какие ачивки за всё время",
                       "сколько ачивок за все время"):
            r = _hardcoded_match(phrase)
            self.assertEqual(r["action"], "steam:achievements", phrase)
            self.assertEqual(r["arg"], "всё", phrase)

    def test_achievements_week_variants(self):
        from modules.command_router import _hardcoded_match
        for phrase in ("какие ачивки на этой неделе",
                       "ачивки за 7 дней",
                       "какие ачивки за неделю",
                       "какие ачивки я получил"):   # без периода → неделя
            r = _hardcoded_match(phrase)
            self.assertEqual(r["action"], "steam:achievements", phrase)
            self.assertEqual(r["arg"], "неделя", phrase)

    def test_achievements_today_variants(self):
        from modules.command_router import _hardcoded_match
        for phrase in ("какие ачивки сегодня",
                       "ачивки за сегодня",
                       "какие ачивки за день"):
            r = _hardcoded_match(phrase)
            self.assertEqual(r["arg"], "сегодня", phrase)

    def test_achievements_unknown_period_downgrades_to_week(self):
        from modules.command_router import _hardcoded_match
        # «позавчера» не входит в словарь периодов → arg пусто → неделя
        r = _hardcoded_match("ачивки позавчера")
        self.assertEqual(r["action"], "steam:achievements")
        self.assertEqual(r["arg"], "неделя")

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


class TestRemindersVoice(unittest.TestCase):

    def test_add_parsed_and_confirmed(self):
        from modules.voice_info import reminders_add
        parsed = {"text": "проверить чайник", "delay": 1200, "type": "reminder"}
        entry = {"trigger_at": 1000001200, "type": "reminder",
                 "text": "проверить чайник"}
        with patch("modules.reminders.parse_reminder", return_value=parsed), \
             patch("modules.reminders.add_reminder", return_value=entry) as addm, \
             patch("modules.voice_info._now", return_value=1000000000):
            text, ok = _run(reminders_add("напомни через 20 минут проверить чайник"))
        self.assertTrue(ok)
        addm.assert_called_once_with("проверить чайник", 1200, "reminder")
        self.assertIn("20 мин", text)
        self.assertIn("проверить чайник", text)

    def test_add_unparsed_is_honest(self):
        from modules.voice_info import reminders_add
        with patch("modules.reminders.parse_reminder", return_value=None):
            text, ok = _run(reminders_add("напомни что-нибудь когда-нибудь"))
        self.assertFalse(ok)
        self.assertIn("Не разобрала время", text)

    def test_list_empty(self):
        from modules.voice_info import reminders_list
        with patch("modules.reminders.format_reminders_list",
                   return_value="Нет активных напоминаний."):
            text, ok = _run(reminders_list())
        self.assertTrue(ok)
        self.assertIn("Нет активных напоминаний", text)


class TestTasksVoice(unittest.TestCase):

    def test_list_with_ids(self):
        from modules.voice_info import tasks_list
        due = [{"id": 111, "text": "Купить хлеб", "due_time": "", "due_date": ""}]
        up = [{"id": 222, "text": "Позвонить в сервис", "due_time": "18:00"}]
        with patch("modules.tasks.get_due_tasks", return_value=due), \
             patch("modules.tasks.get_upcoming_tasks", return_value=up):
            text, ok = _run(tasks_list())
        self.assertTrue(ok)
        self.assertIn("[111] Купить хлеб", text)
        self.assertIn("[222] Позвонить в сервис", text)

    def test_list_empty_honest(self):
        from modules.voice_info import tasks_list
        with patch("modules.tasks.get_due_tasks", return_value=[]), \
             patch("modules.tasks.get_upcoming_tasks", return_value=[]):
            text, ok = _run(tasks_list())
        self.assertTrue(ok)
        self.assertIn("Активных задач нет", text)

    def test_add_task(self):
        from modules.voice_info import tasks_add
        created = {"id": 999, "text": "купить хлеб"}
        with patch("modules.tasks.add_task", return_value=created) as addm:
            text, ok = _run(tasks_add("купить хлеб"))
        self.assertTrue(ok)
        addm.assert_called_once_with("купить хлеб")
        self.assertIn("Задача добавлена", text)

    def test_done_marks_completed(self):
        from modules.voice_info import tasks_done
        tasks = [{"id": 111, "text": "Купить хлеб"}]
        with patch("modules.tasks.load_tasks", return_value=tasks), \
             patch("modules.tasks.complete_task") as comp:
            text, ok = _run(tasks_done("выполнил задачу 111"))
        self.assertTrue(ok)
        comp.assert_called_once_with(111)

    def test_done_unknown_id_no_fake_success(self):
        """Несуществующий id — честно говорим, НЕ рапортуем «выполнено»."""
        from modules.voice_info import tasks_done
        with patch("modules.tasks.load_tasks", return_value=[]), \
             patch("modules.tasks.complete_task") as comp:
            text, ok = _run(tasks_done("задачу 555"))
        self.assertTrue(ok)          # ответ корректный...
        comp.assert_not_called()     # ...но ничего не «закрыто»
        self.assertIn("нет", text)


class TestRouterReminderTaskHardcode(unittest.TestCase):

    def test_reminder_add_catches_word(self):
        from modules.command_router import _hardcoded_match
        r = _hardcoded_match("напомни через 20 минут полить цветы")
        self.assertEqual(r["action"], "reminder:add")

    def test_reminder_list_vs_add(self):
        from modules.command_router import _hardcoded_match
        r = _hardcoded_match("какие у меня напоминания")
        self.assertEqual(r["action"], "reminder:list")

    def test_task_add_extracts_text(self):
        from modules.command_router import _hardcoded_match
        r = _hardcoded_match("добавь задачу купить хлеб")
        self.assertEqual(r["action"], "task:add")
        self.assertEqual(r["arg"], "купить хлеб")

    def test_task_done_extracts_number(self):
        from modules.command_router import _hardcoded_match
        r = _hardcoded_match("я выполнил задачу 5")
        self.assertEqual(r["action"], "task:done")
        self.assertEqual(r["arg"], "5")

    def test_task_list(self):
        from modules.command_router import _hardcoded_match
        r = _hardcoded_match("какие у меня задачи?")
        self.assertEqual(r["action"], "task:list")


class TestWeatherVoice(unittest.TestCase):

    def test_weather_facts(self):
        from modules.voice_info import weather_now
        w = {"temp": -3.4, "desc": "небольшой снег", "category": "snow",
             "wind": 4.2, "daily": [{"t_min": -6, "t_max": -1}]}
        with patch("modules.weather.get_weather", new=AsyncMock(return_value=w)):
                    text, ok = _run(weather_now())
        self.assertTrue(ok)
        self.assertIn("-3.4°C", text)


class TestMusicDispatch(unittest.TestCase):
    """Проверка таблицы music_action в core/browser.py (блок 6)."""

    def setUp(self):
        import agent.core.browser as browser
        self._browser = browser

    def test_shuffle_dispatches(self):
        with patch.object(self._browser, "music_shuffle",
                          MagicMock(return_value="перемешать")) as m:
            r = self._browser.music_action("music:shuffle")
            m.assert_called_once()
            self.assertTrue(r["ok"])
            self.assertEqual(r["detail"], "перемешать")

    def test_podcasts_dispatches(self):
        with patch.object(self._browser, "music_podcasts",
                          MagicMock(return_value="открыла подкасты")) as m:
            r = self._browser.music_action("music:podcasts")
            m.assert_called_once()
            self.assertEqual(r["detail"], "открыла подкасты")

    def test_repeat_dispatches(self):
        with patch.object(self._browser, "music_repeat",
                          MagicMock(return_value="повтор")) as m:
            r = self._browser.music_action("music:repeat")
            m.assert_called_once()
            self.assertEqual(r["detail"], "повтор")

    def test_unknown_action_returns_false(self):
        r = self._browser.music_action("music:nonexistent")
        self.assertFalse(r["ok"])
        self.assertIn("неизвестная", r["detail"])

    def test_intents_prompt_has_music_commands(self):
        """INTENTS_PROMPT в command_router должен содержать все music-* команды."""
        from modules.command_router import INTENTS_PROMPT
        for action in ("music:shuffle", "music:repeat", "music:seek_forward",
                       "music:seek_back", "music:podcasts", "music:mute",
                       "music:volume_up", "music:volume_down"):
            self.assertIn(action, INTENTS_PROMPT, f"INTENTS_PROMPT missing {action}")

    def test_weather_service_down_is_honest(self):
        from modules.voice_info import weather_now
        with patch("modules.weather.get_weather",
                   new=AsyncMock(return_value=None)):
            text, ok = _run(weather_now())
        self.assertFalse(ok)
        self.assertIn("не «данных нет»", text)

    def test_router_weather(self):
        from modules.command_router import _hardcoded_match
        r = _hardcoded_match("какая погода?")
        self.assertEqual(r["action"], "weather:now")


class TestMusicStatsVoice(unittest.TestCase):

    def test_recent_with_period(self):
        from modules.voice_info import music_recent
        with patch("modules.music_memory.format_recent",
                   return_value="• 14:02 — Кино — Группа крови") as fm:
            text, ok = _run(music_recent("вчера"))
        self.assertTrue(ok)
        fm.assert_called_once_with(hours=48)
        self.assertIn("За вчера", text)

    def test_recent_empty_honest(self):
        from modules.voice_info import music_recent
        with patch("modules.music_memory.format_recent",
                   return_value="Нет данных о прослушиваниях."):
            text, ok = _run(music_recent("сегодня"))
        self.assertTrue(ok)
        self.assertIn("прослушиваний нет", text.lower())

    def test_top(self):
        from modules.voice_info import music_top
        with patch("modules.music_memory.format_top",
                   return_value="За 7 дн.: 40 прослушиваний") as ft:
            text, ok = _run(music_top("неделя"))
        self.assertTrue(ok)
        ft.assert_called_once_with(days=7)
        self.assertIn("40 прослушиваний", text)

    def test_router_music(self):
        from modules.command_router import _hardcoded_match
        r = _hardcoded_match("что я слушал вчера")
        self.assertEqual(r["action"], "music_stats:recent")
        self.assertEqual(r["arg"], "вчера")
        r = _hardcoded_match("кого я слушаю чаще всего")
        self.assertEqual(r["action"], "music_stats:top")

    def test_router_music_extra_phrasings(self):
        """Формулировки из голосового пути (_music_queries в ws_handlers.py) —
        должны узнаваться и в текстовом (ТГ) роутере, не только «что я слушал»."""
        from modules.command_router import _hardcoded_match
        for phrase in ("что мы слушали вчера", "что слушали сегодня",
                       "последние треки", "какие треки", "история музыки",
                       "что играло", "что было в плейлисте"):
            r = _hardcoded_match(phrase)
            self.assertEqual(r["action"], "music_stats:recent", phrase)
        for phrase in ("топ исполнителей", "топ треков"):
            r = _hardcoded_match(phrase)
            self.assertEqual(r["action"], "music_stats:top", phrase)


class TestMusicAppRouter(unittest.TestCase):
    """Роутер → app-dispatch music-команды (блок 6, deep trigger)."""

    def test_now_playing(self):
        from modules.command_router import _hardcoded_match
        r = _hardcoded_match("что играет")
        self.assertEqual(r["action"], "music:now_playing")
        r = _hardcoded_match("какой трек сейчас")
        self.assertEqual(r["action"], "music:now_playing")

    def test_like_dislike(self):
        from modules.command_router import _hardcoded_match
        self.assertEqual(_hardcoded_match("лайкни трек")["action"], "music:like")
        self.assertEqual(_hardcoded_match("поставь лайк")["action"], "music:like")
        self.assertEqual(_hardcoded_match("дизлайкни")["action"], "music:dislike")
        self.assertEqual(_hardcoded_match("не нравится")["action"], "music:dislike")

    def test_next_prev(self):
        from modules.command_router import _hardcoded_match
        self.assertEqual(_hardcoded_match("следующий трек")["action"], "music:next")
        self.assertEqual(_hardcoded_match("следующую")["action"], "music:next")
        self.assertEqual(_hardcoded_match("предыдущий трек")["action"], "music:prev")
        self.assertEqual(_hardcoded_match("предыдущий")["action"], "music:prev")
        # «переведи на следующий» — не хардкод, LLM разбирает

    def test_shuffle_repeat(self):
        from modules.command_router import _hardcoded_match
        self.assertEqual(_hardcoded_match("перемешай")["action"], "music:shuffle")
        self.assertEqual(_hardcoded_match("повтори трек")["action"], "music:repeat")

    def test_wave(self):
        from modules.command_router import _hardcoded_match
        self.assertEqual(_hardcoded_match("включи мою волну")["action"], "music:wave")

    def test_volume_system_vs_music(self):
        from modules.command_router import _hardcoded_match
        self.assertEqual(_hardcoded_match("сделай громче")["action"], "volume_up:20")
        self.assertEqual(_hardcoded_match("сделай музыку громче")["action"], "music:volume_up")
        self.assertEqual(_hardcoded_match("тише")["action"], "volume_down:20")
        self.assertEqual(_hardcoded_match("сделай музыку тише")["action"], "music:volume_down")


class TestCapsulesVoice(unittest.TestCase):

    def test_list_capsules(self):
        pass

class TestYamusicApp(unittest.TestCase):
    """Тесты для agent/core/yamusic_app.py — управление десктопным приложением.

    На Linux winsdk/win32gui недоступны → модуль работает в fallback-режиме
    (_SMTC_OK=False, _HAS_WIN32=False). Тесты покрывают оба пути:
    graceful fallback + мокированный Windows-путь.
    """

    def test_now_playing_no_smtc_returns_empty(self):
        """На Linux без winsdk now_playing() → пустой dict, без исключений."""
        from agent.core import yamusic_app as ym
        self.assertEqual(ym.now_playing(), {})

    def test_play_pause_no_smtc_returns_false(self):
        """На Linux play_pause/next/prev → False, без исключений."""
        from agent.core import yamusic_app as ym
        self.assertFalse(ym.play_pause())
        self.assertFalse(ym.next_track())
        self.assertFalse(ym.prev_track())

    def test_music_target_no_smtc_returns_browser(self):
        """Без SMTC-сессии music_target() → 'browser' (fallback)."""
        from agent.core import yamusic_app as ym
        self.assertEqual(ym.music_target(), "browser")

    def test_deep_links_no_startfile_returns_false(self):
        """На Linux os.startfile недоступен → deep links → False без crash."""
        from agent.core import yamusic_app as ym
        self.assertFalse(ym.open_wave())
        self.assertFalse(ym.open_playlist("123"))
        self.assertFalse(ym.open_album("456"))
        self.assertFalse(ym.open_artist("789"))

    def test_like_dislike_no_window_returns_false(self):
        """Без окна Яндекс Музыки like/dislike → False."""
        from agent.core import yamusic_app as ym
        self.assertFalse(ym.like())
        self.assertFalse(ym.dislike())

    def test_smtc_control_unknown_method_returns_false(self):
        """_smtc_control с неизвестным методом → False (AttributeError подавлен)."""
        from agent.core.yamusic_app import _smtc_control
        # подменим сессию без такого методa
        with patch("agent.core.yamusic_app._yandex_smtc_session",
                   return_value=MagicMock(spec=[])):
            self.assertFalse(_smtc_control("NonExistentAsync"))

    # ── Мокированный Windows-путь ──────────────────────────────────────

    def _mock_session(self, title="Песня", artist="Артист", album="Альбом",
                      status=4, pb_return=True):
        """Создаёт мок SMTC-сессии Яндекс Музыки.

        status — код WinRT GlobalSystemMediaTransportControlsSessionPlaybackStatus
        (0=Closed, 1=Opened, 2=Changed, 3=Stopped, 4=Playing, 5=Paused).

        try_get_media_properties_async() возвращает объект с .get(),
        возвращающим props (имитация async-результа).
        """
        props = MagicMock()
        props.title = title
        props.artist = artist
        props.album_title = album

        pb = MagicMock()
        pb.playback_status = status

        # async-подобный результат: .get() → props
        async_result = MagicMock()
        async_result.get = MagicMock(return_value=props)

        session = MagicMock()
        session.source_app_user_model_id = "Yandex.Music"
        session.try_get_media_properties_async = MagicMock(return_value=async_result)
        session.get_playback_info = MagicMock(return_value=pb)
        session.TryTogglePlayPauseAsync = MagicMock(return_value=pb_return)
        session.TrySkipNextAsync = MagicMock(return_value=pb_return)
        session.TrySkipPreviousAsync = MagicMock(return_value=pb_return)
        return session

    def test_now_playing_with_smtc_session(self):
        """При наличии SMTC-сессии now_playing() возвращает трек.

        Регрессия на баг «статус 'закрыт' при играющей музыке»:
        играющий трек — код 4 (Playing), а НЕ 1.
        """
        session = self._mock_session(title="My Song", artist="Artist",
                                     status=4)
        with patch("agent.core.yamusic_app._yandex_smtc_session",
                   return_value=session):
            from agent.core import yamusic_app as ym
            info = ym.now_playing()
        self.assertEqual(info["title"], "My Song")
        self.assertEqual(info["artist"], "Artist")
        self.assertEqual(info["album"], "Альбом")
        self.assertEqual(info["status"], "играет")

    def test_now_playing_status_map(self):
        """Карта статусов SMTC соответствует WinRT enum.

        Прежняя карта ({1:'играет', 4:'закрыт'}) была сдвинута на 3 позиции:
        играющий трек (4) помечался 'закрыт', пауза (5) — дефолт 'играет'.
        """
        with patch("agent.core.yamusic_app._yandex_smtc_session",
                   return_value=self._mock_session(status=5)):
            from agent.core import yamusic_app as ym
            self.assertEqual(ym.now_playing()["status"], "пауза")
        with patch("agent.core.yamusic_app._yandex_smtc_session",
                   return_value=self._mock_session(status=3)):
            from agent.core import yamusic_app as ym
            self.assertEqual(ym.now_playing()["status"], "остановлен")
        with patch("agent.core.yamusic_app._yandex_smtc_session",
                   return_value=self._mock_session(status=0)):
            from agent.core import yamusic_app as ym
            self.assertEqual(ym.now_playing()["status"], "закрыт")

    def test_music_target_with_smtc_returns_app(self):
        """При наличии SMTC-сессии music_target() → 'app'."""
        session = self._mock_session()
        with patch("agent.core.yamusic_app._yandex_smtc_session",
                   return_value=session):
            from agent.core import yamusic_app as ym
            self.assertEqual(ym.music_target(), "app")

    def test_play_pause_with_smtc_returns_true(self):
        """При наличии SMTC-сессии play_pause → True."""
        session = self._mock_session(pb_return=True)
        with patch("agent.core.yamusic_app._yandex_smtc_session",
                   return_value=session), \
             patch("agent.core.yamusic_app._smtc_control",
                   return_value=True):
            from agent.core import yamusic_app as ym
            self.assertTrue(ym.play_pause())

    def test_open_wave_calls_startfile(self):
        """open_wave() вызывает os.startfile с правильным deep link."""
        with patch("agent.core.yamusic_app._HAS_WIN32", True), \
             patch("agent.core.yamusic_app.os.startfile", create=True) as mf:
            from agent.core import yamusic_app as ym
            self.assertTrue(ym.open_wave())
            mf.assert_called_once_with("yandexmusic://radio/user/onyourwave")

    def test_open_playlist_calls_startfile(self):
        """open_playlist() формирует правильный deep link с ID."""
        with patch("agent.core.yamusic_app.os.startfile", create=True) as mf:
            from agent.core import yamusic_app as ym
            self.assertTrue(ym.open_playlist("playlist123"))
            mf.assert_called_once_with("yandexmusic://playlist/playlist123")

        from modules.voice_info import capsules_list
        caps = [
            {"id": 1, "text": "Письмо себе", "open_date": "2027-01-01"},
            {"id": 2, "text": "Секретик", "open_date": "2026-12-31"},
        ]
        with patch("modules.capsules.get_all_capsules", return_value=caps) as gm:
            text, ok = _run(capsules_list())
        gm.assert_called_once_with(include_opened=False)
        self.assertTrue(ok)
        self.assertIn("Ждут вскрытия 2", text)
        self.assertIn("2027-01-01: Письмо себе", text)

    def test_list_empty(self):
        from modules.voice_info import capsules_list
        with patch("modules.capsules.get_all_capsules", return_value=[]):
            text, ok = _run(capsules_list())
        self.assertTrue(ok)
        self.assertIn("нет", text.lower())

    def test_router_does_not_hijack_creation(self):
        """Вопрос о капсулах матчится, а фразы создания — НЕТ."""
        from modules.command_router import _hardcoded_match
        r = _hardcoded_match("какие у меня капсулы ждут")
        self.assertEqual(r["action"], "capsule:list")
        self.assertIsNone(_hardcoded_match("спрячь капсулу до мая"))
        self.assertIsNone(_hardcoded_match("открой капсулу которая ждёт"))

    def test_briefing_in_catalog(self):
        """briefing:now присутствует в каталоге интентов."""
        from modules.command_router import INTENTS_PROMPT
        self.assertIn('"briefing:now"', INTENTS_PROMPT)


# ════════════════════════════════════════════════════════════════════
# ЧЕСТНОСТЬ: «данных нет» ≠ «не умею проверить»
# ════════════════════════════════════════════════════════════════════

class TestHonestyRule(unittest.TestCase):

    def test_honesty_rule_in_system_prompt(self):
        """Правило различия добавлено в личность (раздел ПАМЯТЬ И ЧЕСТНОСТЬ)."""
        from personality import get_system_prompt
        prompt = get_system_prompt()
        low = prompt.lower()
        self.assertIn("не умею это проверить", low)
        self.assertIn("такой команды у меня нет", low)

    def test_search_nonexistence_rule_in_system_prompt(self):
        """Третий случай: «не нашла» ≠ «этого не существует» (пустая выдача)."""
        from personality import get_system_prompt
        prompt = get_system_prompt()
        self.assertIn("Различай «не нашла» и «этого не существует»", prompt)
        self.assertIn("НЕ доказывает", prompt)
        self.assertIn("дезинформация", prompt)


# ════════════════════════════════════════════════════════════════════
# БАГ 1: информационные команды в Telegram (main.handle_message)
# ════════════════════════════════════════════════════════════════════

class TestTelegramInfoPath(unittest.TestCase):
    """Инфо-команда из Telegram идёт через voice_info (как голос), а не в LLM."""

    def _make_msg(self, text):
        from config import MASTER_ID
        msg = MagicMock()
        msg.chat.id = MASTER_ID
        msg.from_user.id = MASTER_ID
        msg.from_user.full_name = "Мастер"
        msg.text = text
        msg.reply_to_message = None
        return msg

    def test_achievements_query_routes_to_voice_info(self):
        """«какие ачивки я выбил за эту неделю» → voice_info('steam:achievements','неделя')."""
        with patch("aiogram.Bot"):
            import main

        msg = self._make_msg("какие ачивки я выбил за эту неделю")
        routed = {"action": "steam:achievements", "arg": "неделя",
                  "confidence": 1.0, "alt": None}

        with patch.object(main, "get_role", return_value="master"), \
             patch.object(main, "update_master_status"), \
             patch.object(main, "route_command",
                          new=AsyncMock(return_value=routed)), \
             patch.object(main, "answer_voice_info",
                          new=AsyncMock()) as av, \
             patch.object(main, "ask_gemini", new=AsyncMock()) as ag:
            _run(main.handle_message(msg))

        # Обращение к voice_info произошло, LLM-разговор — НЕТ
        av.assert_awaited_once()
        call_args = av.await_args.args
        self.assertEqual(call_args[0], "steam:achievements")
        self.assertEqual(call_args[1], "неделя")
        self.assertEqual(call_args[3], None)      # ws_dev — нет устройства
        self.assertEqual(call_args[4], None)      # device_id — нет устройства
        self.assertEqual(call_args[5], ag)        # в answer_voice_info ушёл ask_gemini
        ag.assert_not_awaited()   # ответ не выдуман разговорным LLM

    def test_conversation_reply_not_routed(self):
        """Reply на сообщение (продолжение разговора) не гоняем через роутер."""
        with patch("aiogram.Bot"):
            import main

        msg = self._make_msg("какие ачивки?")
        msg.reply_to_message = MagicMock()   # это reply на обсуждение

        bot = MagicMock()
        bot.send_chat_action = AsyncMock()
        bot.send_message = AsyncMock()

        with patch.object(main, "get_role", return_value="master"), \
             patch.object(main, "update_master_status"), \
             patch.object(main, "route_command",
                          new=AsyncMock(return_value=None)) as rc, \
             patch.object(main, "answer_voice_info", new=AsyncMock()) as av, \
             patch.object(main, "bot", bot), \
             patch.object(main, "ask_gemini",
                          new=AsyncMock(return_value="ответ")), \
             patch.object(main, "send_as_conversation",
                          new=AsyncMock()):
            _run(main.handle_message(msg))

        rc.assert_not_awaited()
        av.assert_not_awaited()

    def test_unknown_phrase_falls_through_to_llm(self):
        """Не-инфо реплика НЕ перехватывается: доходит до обычного разговора."""
        with patch("aiogram.Bot"):
            import main

        msg = self._make_msg("что ты думаешь про закат?")
        bot = MagicMock()
        bot.send_chat_action = AsyncMock()
        bot.send_message = AsyncMock()

        with patch.object(main, "get_role", return_value="master"), \
             patch.object(main, "update_master_status"), \
             patch.object(main, "route_command",
                          new=AsyncMock(return_value=None)) as rc, \
             patch.object(main, "answer_voice_info", new=AsyncMock()) as av, \
             patch.object(main, "bot", bot), \
             patch.object(main, "ask_gemini",
                          new=AsyncMock(return_value="ответ")), \
             patch.object(main, "send_as_conversation",
                          new=AsyncMock()) as sc:
            _run(main.handle_message(msg))

        rc.assert_awaited_once()      # роутер спросили...
        av.assert_not_awaited()       # ...но это не инфо-команда
        sc.assert_awaited_once()      # и ответил обычный LLM-путь

    def test_ok_false_speaks_literal_without_llm(self):
        """ok=False → честный literal-ответ, LLM-стилизация НЕ вызывается."""
        import modules.ws_handlers as wh
        ag = AsyncMock(return_value="выдумка LLM")
        bot = MagicMock()
        bot.send_message = AsyncMock()
        with patch("modules.voice_info.handle",
                   new=AsyncMock(return_value=("Источник недоступен.", False))):
            _run(wh.answer_voice_info(
                "steam:progress", "x", "прогресс",
                None, "laptop", ag, bot))
        ag.assert_not_awaited()          # LLM молчит — не выдумывает
        sent = bot.send_message.await_args.args[1]
        self.assertEqual(sent, "Источник недоступен.")

    def test_ok_true_styled_but_facts_first(self):
        import modules.ws_handlers as wh
        ag = AsyncMock(return_value="Стилизованный ответ.")
        bot = MagicMock()
        bot.send_message = AsyncMock()
        with patch("modules.voice_info.handle",
                   new=AsyncMock(return_value=("Факт: 13 из 42.", True))):
            _run(wh.answer_voice_info(
                "steam:progress", "x", "прогресс",
                None, "laptop", ag, bot))
        ag.assert_awaited_once()         # факты стилизуются...
        sent = bot.send_message.await_args.args[1]
        self.assertEqual(sent, "Стилизованный ответ.")

    def test_tone_tag_stripped_when_sent_as_telegram_text(self):
        """[ТОН: ...] управляет голосом TTS, а не текстом — в ТГ его не видно."""
        import modules.ws_handlers as wh
        ag = AsyncMock(return_value="[ТОН: спокойно] Стилизованный ответ.")
        bot = MagicMock()
        bot.send_message = AsyncMock()
        with patch("modules.voice_info.handle",
                   new=AsyncMock(return_value=("Факт: 13 из 42.", True))):
            _run(wh.answer_voice_info(
                "steam:progress", "x", "прогресс",
                None, "laptop", ag, bot))
        sent = bot.send_message.await_args.args[1]
        self.assertEqual(sent, "Стилизованный ответ.")
        self.assertNotIn("[ТОН:", sent)

    def test_no_device_sends_to_telegram(self):
        """Инфо-команды работают без устройства — ответ уходит в ТГ."""
        import modules.ws_handlers as wh
        ag = AsyncMock(return_value="")
        bot = MagicMock()
        bot.send_message = AsyncMock()
        with patch("modules.voice_info.handle",
                   new=AsyncMock(return_value=("Активных задач нет.", True))), \
             patch.object(wh, "stream_tts_to_device", new=AsyncMock()) as tts:
            _run(wh.answer_voice_info(
                "task:list", "", "какие задачи",
                None, "laptop", ag, bot))
        bot.send_message.assert_awaited_once()
        self.assertIn("Активных задач нет", bot.send_message.await_args.args[1])
        tts.assert_not_awaited()


# ════════════════════════════════════════════════════════════════════
# БАГ 3: literal-механики голоса, подключённые к Telegram
# (переводчик, страхи, игра в слова, калькулятор, печенье)
# ════════════════════════════════════════════════════════════════════

class TestTelegramLiteralMechanics(unittest.TestCase):
    """Механики, которые работали только голосом, отвечают и в Telegram."""

    def _make_msg(self, text):
        from config import MASTER_ID
        msg = MagicMock()
        msg.chat.id = MASTER_ID
        msg.from_user.id = MASTER_ID
        msg.from_user.full_name = "Мастер"
        msg.text = text
        msg.reply_to_message = None
        return msg

    def _run(self, text):
        with patch("aiogram.Bot"):
            import main
        bot = MagicMock()
        bot.send_chat_action = AsyncMock()
        bot.send_message = AsyncMock()
        with patch.object(main, "get_role", return_value="master"), \
             patch.object(main, "update_master_status"), \
             patch.object(main, "bot", bot), \
             patch.object(main, "send_as_conversation",
                          new=AsyncMock()) as sc, \
             patch.object(main, "route_command",
                          new=AsyncMock(return_value=None)), \
             patch.object(main, "answer_voice_info", new=AsyncMock()), \
             patch.object(main, "ask_gemini",
                          new=AsyncMock(return_value="болтовня")) as ag:
            _run(main.handle_message(self._make_msg(text)))
        return sc, ag

    def test_fear_via_telegram(self):
        """«началась гроза» в TG → страх-ответ, а не LLM-болтовня."""
        sc, ag = self._run("началась гроза, слышу гром")
        sc.assert_awaited_once()
        ag.assert_not_awaited()

    def test_calculator_via_telegram(self):
        """«сколько будет 12 умножить на 8» в TG → калькулятор без LLM."""
        sc, ag = self._run("сколько будет 12 умножить на 8")
        sc.assert_awaited_once()
        self.assertIn("12 умножить на 8 = 96", sc.await_args.args[1])
        ag.assert_not_awaited()

    def test_fortune_via_telegram(self):
        """«дай печенье» в TG → предсказание, LLM не дёргается."""
        with patch("aiogram.Bot"):
            import main
        with patch.object(main, "get_role", return_value="master"), \
             patch.object(main, "update_master_status"), \
             patch.object(main, "send_as_conversation",
                          new=AsyncMock()) as sc, \
             patch.object(main, "ask_gemini",
                          new=AsyncMock(return_value="болтовня")) as ag, \
             patch.object(main, "get_fortune",
                          return_value={"period": "день"}), \
             patch.object(main, "format_fortune",
                          side_effect=lambda f: "ТЕСТ-ПРЕДСКАЗАНИЕ"):
            _run(main.handle_message(self._make_msg("дай печенье")))
        sc.assert_awaited_once()
        self.assertEqual(sc.await_args.args[1], "ТЕСТ-ПРЕДСКАЗАНИЕ")
        ag.assert_not_awaited()

    def test_word_game_teach_via_telegram(self):
        """«придумай слово» в TG → японское слово без LLM."""
        sc, ag = self._run("придумай слово")
        sc.assert_awaited_once()
        ag.assert_not_awaited()

class TestSteamAchievementsGame(unittest.TestCase):
    """Ачивки по КОНКРЕТНОЙ игре: steam:achievements:game.<НАЗВАНИЕ>.

    Резолв названия — через search_game() (неточные названия, кириллица).
    Период может сочетаться: «достижения в Remnant за месяц».
    Честность: игра не найдена в библиотеке ≠ «игра не существует».
    """

    # ── Роутинг ────────────────────────────────────────────────────────

    def _route(self, phrase):
        from modules.command_router import _hardcoded_match
        return _hardcoded_match(phrase)

    def test_router_game_variants(self):
        cases = {
            "какие достижения в Remnant": "remnant",
            "мои ачивки в Palworld": "palworld",
            "достижения по Fallout Shelter": "fallout shelter",
            "сколько достижений в Hollow Knight": "hollow knight",
            "достижения в Remnant за месяц": "remnant",   # период не съедает игру
            "какие ачивки по игре Remnant": "remnant",
        }
        for phrase, game in cases.items():
            r = self._route(phrase)
            self.assertIsNotNone(r, phrase)
            self.assertEqual(r["action"], "steam:achievements:game", phrase)
            self.assertEqual(r["arg"], game, phrase)

    def test_router_period_without_game_stays_periodic(self):
        # «в игре» без названия — общий вопрос по периоду, прежнее поведение
        r = self._route("мои достижения в игре")
        self.assertEqual(r["action"], "steam:achievements")
        r = self._route("какие ачивки я получил вчера")
        self.assertEqual(r["action"], "steam:achievements")
        self.assertEqual(r["arg"], "вчера")

    # ── Обработчик (источники мокаются на границе модулей) ─────────────

    def _run_handler(self, name, text="", game=None, achievements=None):
        from modules.voice_info import steam_achievements_game
        with patch("modules.steam_integration.search_game", return_value=game), \
             patch("modules.steam_integration.load_library", new=AsyncMock()), \
             patch("modules.steam_integration.get_achievements",
                   new=AsyncMock(return_value=achievements or [])):
            return _run(steam_achievements_game(name, text))

    def test_counts_and_last_achievements(self):
        game = {"appid": 1245620, "name": "ELDEN RING"}
        now = int(time.time())
        achievements = [
            {"name": "Первый шаг", "apiname": "ACH_1",
             "achieved": 1, "unlocktime": now - 3600},
            {"name": "Второй шаг", "apiname": "ACH_2",
             "achieved": 1, "unlocktime": now},
            {"name": "Дальний", "apiname": "ACH_3",
             "achieved": 0, "unlocktime": 0},
        ]
        text, ok = self._run_handler("ELDEN RING",
                                     game=game, achievements=achievements)
        self.assertTrue(ok)
        self.assertIn("выбито 2 из 3", text)
        self.assertIn("Второй шаг", text)
        self.assertIn("Первый шаг", text)
        self.assertIn("сегодня", text)

    def test_game_not_found_is_honest(self):
        """Не нашли в библиотеке — честно говорим это, НЕ утверждая,
        что игра не существует (правило честности)."""
        text, ok = self._run_handler("Несуществующая 12345", game=None)
        self.assertTrue(ok)
        self.assertIn("в библиотеке не нашла", text)
        self.assertNotIn("не существует", text)

    def test_period_filters_unlocktime(self):
        from datetime import datetime, timedelta
        game = {"appid": 1, "name": "Remnant"}
        old_ts = int((datetime.now() - timedelta(days=90)).timestamp())
        new_ts = int(time.time()) - 3600
        achievements = [
            {"name": "Старая", "achieved": 1, "unlocktime": old_ts},
            {"name": "Свежая", "achieved": 1, "unlocktime": new_ts},
        ]
        text, ok = self._run_handler(
            "Remnant", text="достижения в Remnant за месяц",
            game=game, achievements=achievements)
        self.assertTrue(ok)
        self.assertIn("выбито 1 из 2", text)
        self.assertIn("Свежая", text)
        self.assertNotIn("Старая", text)

    def test_many_shows_five_and_total(self):
        game = {"appid": 2, "name": "Palworld"}
        now = int(time.time())
        achievements = [{"name": f"A{i}", "achieved": 1,
                         "unlocktime": now - i * 3600} for i in range(8)]
        text, ok = self._run_handler("Palworld",
                                     game=game, achievements=achievements)
        self.assertTrue(ok)
        self.assertIn("выбито 8 из 8", text)
        self.assertIn("И ещё 3 более ранних", text)
        shown = sum(1 for i in range(8) if f"«A{i}»" in text)
        self.assertEqual(shown, 5)

    def test_steam_api_no_answer_not_masked(self):
        """Steam не ответил → ok=False, честно, не маскируем под «достижений нет»."""
        text, ok = self._run_handler("Palworld",
                                     game={"appid": 3, "name": "Palworld"})
        self.assertFalse(ok)
        self.assertIn("не ответил", text)


if __name__ == "__main__":
    unittest.main()

