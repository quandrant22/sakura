"""
Тесты проактива — закрытый список фактических поводов (решение Мастера).

Run:  python3 -m pytest tests/test_proactive_facts.py -q

Проактив: только факты (ачивка/диск/память/нагрузка/устройство/сессия),
без LLM-размышлений, без поиска, без голоса. Состояние пишется во
временный файл (не трогаем memory/proactive.json).
"""
import asyncio
import inspect
import os
import sys
import tempfile
import unittest
from datetime import datetime, timedelta
from unittest.mock import patch

os.environ.setdefault("MASTER_ID", "123456789")
os.environ.setdefault("TELEGRAM_TOKEN", "test:fake-token")
os.environ.setdefault("GEMINI_KEY_1", "fake-gemini-key")
os.environ.setdefault("WS_SECRET", "test-secret-minimum-16-chars")
os.environ.setdefault("MASTER_DEVICES", "laptop,pc")

_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _root not in sys.path:
    sys.path.insert(0, _root)


def _run(coro):
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


class _TmpState:
    """Подменяет файл состояния проактива на временный."""

    def __init__(self):
        self._tmp = tempfile.NamedTemporaryFile(suffix=".json", delete=False)
        self._tmp.close()

    def __enter__(self):
        import modules.proactive as pr
        self._pr = pr
        self._patcher = patch.object(pr, "PROACTIVE_FILE", self._tmp.name)
        self._patcher.start()
        return pr

    def __exit__(self, *exc):
        self._patcher.stop()
        os.unlink(self._tmp.name)


class TestFactTriggers(unittest.TestCase):

    def test_disk_over_90_fires_once_until_changed(self):
        with _TmpState() as pr:
            with patch("modules.vps_monitor.get_metrics", return_value={"disk": 95.4}):
                topic, crit, text = pr.get_fact_trigger({})
                self.assertEqual(topic, "monitor_disk")
                self.assertTrue(crit)
                self.assertEqual(text, "Диск сервера заполнен на 95%.")
                topic2, _, text2 = pr.get_fact_trigger({})
                self.assertIsNone(topic2), "дедуп: то же состояние — тишина"
                self.assertEqual(text2, "")
            with patch("modules.vps_monitor.get_metrics", return_value={"disk": 94.2}):
                topic3, _, text3 = pr.get_fact_trigger({})
                self.assertEqual(topic3, "monitor_disk")
                self.assertEqual(text3, "Диск сервера заполнен на 94%.")
            with patch("modules.vps_monitor.get_metrics", return_value={"disk": 50.0}):
                pr.get_fact_trigger({})
            state = pr.load_state()
            self.assertNotIn("disk_sent", state.get("monitor_state", {}))

    def test_memory_needs_10_minutes_sustained(self):
        with _TmpState() as pr:
            with patch("modules.vps_monitor.get_metrics", return_value={"ram": 95.0}):
                topic, _, _ = pr.get_fact_trigger({})
                self.assertIsNone(topic), "первый тик только фиксирует начало"
                state = pr.load_state()
                state["monitor_state"]["mem_high_since"] = str(
                    datetime.now() - timedelta(minutes=11))
                pr.save_state(state)
                topic2, crit2, text2 = pr.get_fact_trigger({})
                self.assertEqual(topic2, "monitor_mem")
                self.assertTrue(crit2)
                self.assertEqual(text2, "Память сервера: 95%.")

    def test_load_needs_10_minutes_and_cores_multiplier(self):
        with _TmpState() as pr:
            import os as _os
            cores = _os.cpu_count() or 1
            with patch("modules.vps_monitor.get_metrics",
                       return_value={"load1": cores * 2 + 0.5}):
                topic, _, _ = pr.get_fact_trigger({})
                self.assertIsNone(topic)
                state = pr.load_state()
                state["monitor_state"]["load_high_since"] = str(
                    datetime.now() - timedelta(minutes=12))
                pr.save_state(state)
                topic2, crit2, text2 = pr.get_fact_trigger({})
                self.assertEqual(topic2, "monitor_load")
                self.assertTrue(crit2)
                self.assertIn("Нагрузка на сервер высокая", text2)

    def test_device_offline_over_30_min(self):
        with _TmpState() as pr:
            old = (datetime.now() - timedelta(minutes=40)).isoformat()
            devices = {"laptop": {"online": False, "last_seen": old}}
            topic, crit, text = pr.get_fact_trigger(devices)
            self.assertEqual(topic, "monitor_device")
            self.assertTrue(crit)
            self.assertTrue(text.startswith("Устройство laptop недоступно с "))
            topic2, _, _ = pr.get_fact_trigger(devices)
            self.assertIsNone(topic2), "дедуп offline-уведомления"
            pr.get_fact_trigger({"laptop": {"online": True, "last_seen": old}})
            state = pr.load_state()
            self.assertNotIn("laptop", state["monitor_state"]["offline_notified"])
            topic3, _, _ = pr.get_fact_trigger(devices)
            self.assertEqual(topic3, "monitor_device")

    def test_device_recently_offline_is_silent(self):
        with _TmpState() as pr:
            fresh = (datetime.now() - timedelta(minutes=5)).isoformat()
            topic, _, _ = pr.get_fact_trigger(
                {"laptop": {"online": False, "last_seen": fresh}})
            self.assertIsNone(topic)

    def test_long_session_fires_once_per_session(self):
        with _TmpState() as pr:
            sess = {"name": "Palworld", "minutes": 200}
            with patch("modules.steam_integration.get_current_session", return_value=sess), \
                 patch("modules.proactive.random.random", return_value=0.0):
                topic, crit, text = pr.get_fact_trigger({})
                self.assertEqual(topic, "long_session")
                self.assertEqual(text, "В игре Palworld три часа.")
                # один раз за сессию: дальше — тишина при той же сессии
                topic2, _, _ = pr.get_fact_trigger({})
                self.assertIsNone(topic2)

    def test_long_session_skips_by_probability(self):
        with _TmpState() as pr:
            sess = {"name": "Palworld", "minutes": 200}
            with patch("modules.steam_integration.get_current_session",
                       return_value=sess), \
                 patch("modules.proactive.random.random", return_value=0.99):
                topic, _, _ = pr.get_fact_trigger({})
                self.assertIsNone(topic), "пропуск 50% разрешает промолчать"


class TestProactiveRestrictions(unittest.TestCase):
    """Проактив без размышлений, без поиска, без голоса."""

    def test_no_freeform_prompts_left(self):
        import main
        self.assertFalse(hasattr(main, "_PROACTIVE_PROMPTS"))
        self.assertFalse(hasattr(main, "_proactive_prompt_idx"))

    def test_proactive_loop_never_searches(self):
        import main
        src = inspect.getsource(main.proactive_loop)
        for banned in ("needs_search", "search_grounded", "parallel_search",
                       "smart_search"):
            self.assertNotIn(banned, src)

    def test_proactive_loop_never_speaks_voice(self):
        import main
        src = inspect.getsource(main.proactive_loop)
        self.assertNotIn("stream_tts_to_device", src)
        self.assertNotIn("stream_llm_to_tts", src)
        self.assertIn("send_telegram_text", src), "проактив — только Telegram"

    def test_achievement_cb_is_fact_format(self):
        import main
        src = inspect.getsource(main.main)
        self.assertIn("Выбито достижение: {ach_name} ({game_name}).", src)
        self.assertNotIn("Отреагируй живо", src)


if __name__ == "__main__":
    unittest.main()