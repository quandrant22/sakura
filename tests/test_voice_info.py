"""
Тесты голосовых информационных команд (modules/voice_info.py).

Run: python3 -m pytest tests/test_voice_info.py -q
Без сети; источники данных мокаются на границе модулей.
"""
import os
import sys
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
        self.assertIn("небольшой снег", text)
        self.assertIn("от -6 до -1", text)

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


class TestCapsulesVoice(unittest.TestCase):

    def test_list_capsules(self):
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
