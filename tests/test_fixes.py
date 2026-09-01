"""
Regression tests for the bugfix batch (blocks 1-8).

Run:  python3 -m pytest tests/test_fixes.py -q

No network, temp files only.
"""
import os
import sys
import json
import time
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
                args, kwargs = bot.send_message.call_args
                self.assertEqual(args, (123456789, "Привет"))
                self.assertTrue(kwargs["link_preview_options"].is_disabled)


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


# ════════════════════════════════════════════════════════════════════
# БЛОК 7 — TTS: короткие ответы и быстрый старт
# ════════════════════════════════════════════════════════════════════

class TestBlock7_TTSFastStart(unittest.TestCase):

    def test_split_speech(self):
        from modules.tts_server import _split_speech
        self.assertEqual(_split_speech("Готово."),
                         ["Готово."])
        parts = _split_speech("Первое предложение. Второе предложение. Третье!")
        self.assertEqual(parts, ["Первое предложение.", "Второе предложение.", "Третье!"])
        # длинное предложение без точки режется по запятым/пробелам
        long_one = "слово " * 80
        parts = _split_speech(long_one.strip())
        self.assertGreater(len(parts), 1)
        for p in parts:
            self.assertLessEqual(len(p), 200 + 10)

    def test_short_answers_are_spoken(self):
        """7.1: «Готово.» больше не отсекается порогом длины."""
        import modules.tts_server as tts
        synth = AsyncMock(return_value=3)
        ws = MagicMock()
        ws.send = AsyncMock()
        with patch.object(tts, "_synthesize_and_stream", synth), \
             patch.object(tts, "_send_end", new=AsyncMock()):
            _run(tts.stream_tts_to_device("Готово.", ws, "laptop"))
        synth.assert_awaited_once()
        args = synth.await_args.args
        self.assertEqual(args[0], "Готово.")
        self.assertEqual(args[2], "laptop")

    def test_empty_text_still_skipped(self):
        import modules.tts_server as tts
        synth = AsyncMock(return_value=0)
        ws = MagicMock()
        ws.send = AsyncMock()
        with patch.object(tts, "_synthesize_and_stream", synth), \
             patch.object(tts, "_send_end", new=AsyncMock()):
            _run(tts.stream_tts_to_device("  .  ", ws, "laptop"))
        synth.assert_not_awaited()

    def test_two_stage_preserves_order(self):
        """7.2: пакеты второй (мгновенной) сессии не обгоняют первую."""
        import modules.tts_server as tts

        async def fake_synth(text, emotion, on_packet, label=""):
            chunks = {"first": ["F1", "F2"], "rest": ["R1", "R2"]}
            key = "first" if text.startswith("Первое") else "rest"
            if key == "rest":
                # вторая сессия «молниеносна» — раньше ломало порядок
                pass
            else:
                await asyncio.sleep(0.01)  # первая «медленная»
            for c in chunks[key]:
                await on_packet(c.encode())
            return len(chunks[key])

        sent_frames = []
        ws = MagicMock()
        async def fake_send(raw):
            import json as _json
            sent_frames.append(_json.loads(raw)["audio"])
        ws.send = fake_send

        with patch.object(tts, "_live_synthesize", fake_synth):
            sent = _run(tts._stream_two_stage(
                "Первое предложение.", "Второе предложение.",
                ws, "laptop", "спокойная", time.monotonic()))

        self.assertEqual(sent, 4)
        import base64 as b64
        decoded = [b64.b64decode(a).decode() for a in sent_frames]
        self.assertEqual(decoded, ["F1", "F2", "R1", "R2"])

    def test_two_stage_ends_without_timeout_wait(self):
        """Баг: обе стадии завершились, а код ещё ждал пакет до таймаута
        (лишние ~13с в «Готово за 33.9с»). Теперь продюсер ставит в очередь
        sentinel конца потока (в finally) — drain завершается сразу."""
        import modules.tts_server as tts

        async def fake_synth(text, emotion, on_packet, label=""):
            if text.startswith("Первое"):
                await on_packet(b"F1")
                await asyncio.sleep(0.05)
                await on_packet(b"F2")
            else:
                await asyncio.sleep(0.3)   # вторая стадия «молчит» и завершается
            return 2

        ws = MagicMock()
        ws.send = AsyncMock()
        t0 = time.monotonic()
        with patch.object(tts, "_live_synthesize", fake_synth):
            sent = _run(tts._stream_two_stage(
                "Первое предложение.", "Второе предложение.",
                ws, "laptop", "спокойная", t0))
        elapsed = time.monotonic() - t0
        self.assertEqual(sent, 2)
        # Старый код ждал бы SESSION_TIMEOUT=25с после конца потока
        self.assertLess(elapsed, 5, "drain ждал таймаут после конца потока")

    def test_two_stage_does_not_drop_packets_on_silence(self):
        """Баг: выход drain по аварийному таймауту БРОСАЛ остаток очереди
        («синтез за 21.4с | 337 пакетов», а отправлено меньше). Теперь
        таймаут только предупреждает — ждём sentinel, пакеты не теряем."""
        import modules.tts_server as tts

        async def fake_synth(text, emotion, on_packet, label=""):
            key = "first" if text.startswith("Первое") else "rest"
            if key == "first":
                await on_packet(b"F1")
            else:
                await on_packet(b"R1")
                await asyncio.sleep(0.5)   # молчание дольше аварийного таймаута
                await on_packet(b"R2")
                await on_packet(b"R3")
            return 3

        sent_frames = []
        ws = MagicMock()
        async def fake_send(raw):
            import json as _json
            sent_frames.append(_json.loads(raw)["audio"])
        ws.send = fake_send

        with patch.object(tts, "_live_synthesize", fake_synth), \
             patch.object(tts, "SESSION_TIMEOUT", 0.15):
            sent = _run(tts._stream_two_stage(
                "Первое предложение.", "Второе предложение.",
                ws, "laptop", "спокойная", time.monotonic()))

        import base64 as b64
        decoded = [b64.b64decode(a).decode() for a in sent_frames]
        self.assertEqual(decoded, ["F1", "R1", "R2", "R3"])
        self.assertEqual(sent, 4)

    def test_both_paths_share_stream_tts_to_device(self):
        """7.3: оба голосовых пути используют одну функцию озвучки
        (единая обработка [ТОН:], очистки, эмоции)."""
        import main
        import modules.ws_handlers as wh
        self.assertIs(main.stream_tts_to_device, wh.stream_tts_to_device)
        # stream_llm_to_tts внутри тоже вызывает stream_tts_to_device
        import inspect
        src = inspect.getsource(main.tts_server.stream_llm_to_tts)
        self.assertIn("stream_tts_to_device(", src)


# ════════════════════════════════════════════════════════════════════
# БЛОК 4 — подстрочные матчи: ложные срабатывания
# ════════════════════════════════════════════════════════════════════

class TestBlock4_WordBoundaries(unittest.TestCase):

    def test_volume_commands_do_not_trigger_fears(self):
        """4.1: «сделай громче»/«убавь громкость» не будят страхи."""
        from modules.fears import detect_fear_trigger
        self.assertIsNone(detect_fear_trigger("сделай громче"))
        self.assertIsNone(detect_fear_trigger("убавь громкость"))
        self.assertIsNone(detect_fear_trigger("сделай тише"))
        self.assertIsNone(detect_fear_trigger("следующий трек"))
        self.assertIsNone(detect_fear_trigger("выключи компьютер"))

    def test_storm_words_do_trigger_fears(self):
        from modules.fears import detect_fear_trigger
        hit = detect_fear_trigger("началась гроза")
        self.assertIsNotNone(hit)
        self.assertEqual(hit["fear"], "thunder")
        hit = detect_fear_trigger("слышу гром")
        self.assertIsNotNone(hit)
        self.assertEqual(hit["fear"], "thunder")

    def test_find_trigger_boundaries(self):
        from modules.fuzzy import find_trigger, has_trigger
        self.assertIsNone(find_trigger("гром", "сделай громче"))
        self.assertIsNone(find_trigger("громко", "убавь громкость"))
        self.assertIsNotNone(find_trigger("гром", "слышу гром над крышей"))
        # короткий триггер — только целым словом
        self.assertIsNotNone(find_trigger("ого", "ого, круто!"))
        self.assertIsNone(find_trigger("ого", "магого"))
        self.assertFalse(has_trigger("", "что угодно"))

    def test_reactions_word_boundary(self):
        """4.2: реакции — триггеры только целыми словами."""
        from modules.reactions import detect_reaction
        # «круто» есть, а «крутить»/«закрутить» не должны матчиться
        self.assertIsNone(detect_reaction("закрути гайку", 0.5, 0.5))
        hit = detect_reaction("вау, вот это да!", 0.5, 0.5)
        self.assertIsNotNone(hit)

    def test_rules_word_boundary(self):
        from modules.rules import detect_rule
        rule = detect_rule("зови меня Влад")
        self.assertIsNotNone(rule)
        self.assertEqual(rule["type"], "address")
        self.assertEqual(rule["value"], "влад")
        style = detect_rule("отвечай короче пожалуйста")
        self.assertIsNotNone(style)
        self.assertEqual(style["type"], "style")

    def test_capsules_month_word_boundary(self):
        from modules.capsules import parse_open_date
        # «май» как слово — дата; внутри другого слова — нет
        self.assertIsNotNone(parse_open_date("открой в мае"))
        self.assertIsNone(parse_open_date("расскажи про майнкрафт"))

    def test_router_kettle_word_boundary(self):
        from modules.command_router import route_critical
        self.assertEqual(route_critical("нагрей воду в чайнике до 80 градусов"),
                         "kettle:heat:80")
        self.assertIsNone(route_critical("нагрей до 80 градусов в чайничке самовара"))
