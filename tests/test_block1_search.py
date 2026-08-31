"""
Регрессионные тесты БЛОКА 1 — поиск через Gemini grounding.

Run:  python3 -m pytest tests/test_block1_search.py -q

Моки: никакого сетевого доступа. Имитируются ответы Gemini и Tavily.
"""
import os
import sys
import asyncio
import unittest
from unittest.mock import patch, MagicMock

os.environ.setdefault("MASTER_ID", "123456789")
os.environ.setdefault("TELEGRAM_TOKEN", "test:fake-token")
os.environ.setdefault("GEMINI_KEY_1", "fake-gemini-key")
os.environ.setdefault("WS_SECRET", "test-secret-minimum-16-chars")
os.environ.setdefault("MASTER_DEVICES", "laptop,pc")
os.environ.setdefault("SEARCH_MODEL", "gemini-2.5-flash")

_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _root not in sys.path:
    sys.path.insert(0, _root)


def _run(coro):
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


# фиктивные объекты API Gemini (grounding)

class _FakeWeb:
    def __init__(self, uri, title="источник"):
        self.uri = uri
        self.title = title


class _FakeChunk:
    def __init__(self, uri):
        self.web = _FakeWeb(uri)
        self.retrieved_context = None


class _FakeGMD:
    def __init__(self, uris):
        self.grounding_chunks = [_FakeChunk(u) for u in uris]
        self.web_search_queries = []


class _FakeCand:
    def __init__(self, text, uris):
        self.text = text
        self.grounding_metadata = _FakeGMD(uris)


class _FakeResp:
    def __init__(self, text, uris):
        self.text = text
        self.candidates = [_FakeCand(text, uris)]


class _FakeModels:
    def __init__(self, resp, exc=None):
        self._resp = resp
        self._exc = exc
        self.calls = 0

    def generate_content(self, *a, **k):
        self.calls += 1
        if self._exc:
            raise self._exc
        return self._resp


class _FakeClient:
    def __init__(self, models):
        self.models = models


class _FakeTavilyClient:
    def __init__(self, results):
        self._results = results
        self.calls = 0

    async def search(self, *a, **k):
        self.calls += 1
        return {"results": self._results}


class Test1_SearchTriggered(unittest.TestCase):
    """1.1: needs_search — границы слов, нет ложных срабатываний."""

    def test_greetings_and_commands_not_search(self):
        from modules.web_search import needs_search
        for t in ("привет", "пока", "спасибо", "как дела", "открой браузер",
                  "как ты", "объясни мне", "переведи на английский",
                  "напиши код", "расскажи историю"):
            self.assertFalse(needs_search(t), f"не должно искать: {t!r}")

    def test_hard_and_soft_triggers_search(self):
        from modules.web_search import needs_search
        for t in ("сколько стоит биткоин", "найди в интернете погода",
                  "что такое биткоин", "кто такой Иван Грозный",
                  "как работает блокчейн"):
            self.assertTrue(needs_search(t), f"должно искать: {t!r}")

    def test_short_factual_question_searches(self):
        from modules.web_search import needs_search
        self.assertTrue(needs_search("кто президент Франции"))
        self.assertTrue(needs_search("кто сейчас президент Франции"))

    def test_question_word_plus_proper_noun(self):
        from modules.web_search import needs_search
        self.assertTrue(needs_search("кто президент Франции"))
        # кто такой — мягкий триггер целиком — тоже поиск
        self.assertTrue(needs_search("кто такой"))
        # приветствие имеет приоритет: STOP подавляет даже вопрос
        self.assertFalse(needs_search("привет кто президент Франции"))

    def test_time_markers_search(self):
        from modules.web_search import needs_search
        self.assertTrue(needs_search("какая погода сегодня"))
        self.assertTrue(needs_search("кто сейчас президент Франции"))

    def test_substring_no_false_positive(self):
        from modules.web_search import needs_search
        self.assertFalse(needs_search("перенайди мне песню"))
        self.assertFalse(needs_search("громко сказала"))

    def test_short_direct_request_searches(self):
        """Короткая прямая просьба: глагол поиска в начале + продолжение."""
        from modules.web_search import needs_search
        for t in ("найди рецепт борща", "поищи погоду",
                  "найди информацию о Марсе", "погугли что такое MCP",
                  "загугли курс биткоина", "найдите рецепт борща",
                  "поищи в интернете погода", "найди"):
            self.assertTrue(needs_search(t), f"должно искать: {t!r}")

    def test_leading_verb_word_boundary(self):
        """Глагол поиска ловится только с начала и по границам слов."""
        from modules.web_search import needs_search
        # «перенайди» начинается не с «найди» — не поиск
        self.assertFalse(needs_search("перенайди мне песню"))
        # «найдись» — другой глагол, не прямая просьба искать
        self.assertFalse(needs_search("найдись в моём плейлисте"))
        # приветствие важнее глагола: STOP подавляет ведущий глагол
        self.assertFalse(needs_search("привет найди борщ"))

    def test_word_boundary_no_false_positive(self):
        from modules.web_search import needs_search
        self.assertFalse(needs_search("гром"))
        self.assertFalse(needs_search("громче"))


class Test1_GroundingPath(unittest.TestCase):
    """1.2: search_grounded — успешный grounding — ответ + источники."""

    def test_grounding_returns_answer_and_sources(self):
        import modules.web_search as ws
        ws._clear_search_cache()
        resp = _FakeResp("Эммануил Макрон — президент Франции.", ["https://ru.wikipedia.org/wiki/Франция"])
        models = _FakeModels(resp)
        with patch("google.genai.Client", lambda **kw: _FakeClient(models)), patch.object(ws, "get_active_key", return_value="fake-key"), patch.object(ws, "mark_key_used", return_value=None):
            answer, sources, ok = _run(ws.search_grounded("кто сейчас президент Франции"))
        self.assertTrue(ok)
        self.assertIn("Макрон", answer)
        self.assertIn("https://ru.wikipedia.org/wiki/Франция", sources)
        self.assertEqual(models.calls, 1)

    def test_grounding_cached_no_repeat_call(self):
        import modules.web_search as ws
        ws._clear_search_cache()
        resp = _FakeResp("ответ", ["https://x.ru"])
        models = _FakeModels(resp)
        with patch("google.genai.Client", lambda **kw: _FakeClient(models)), patch.object(ws, "get_active_key", return_value="fake-key"), patch.object(ws, "mark_key_used", return_value=None):
            _run(ws.search_grounded("кто президент Франции"))
            _run(ws.search_grounded("КТО ПРЕЗИДЕНТ ФРАНЦИИ"))
        self.assertEqual(models.calls, 1), "повторный запрос не должен тратить квоту"

    def test_no_key_returns_not_ok(self):
        import modules.web_search as ws
        ws._clear_search_cache()
        # герметично: отключаем Tavily fallback через env
        with patch.dict(os.environ, {"TAVILY_API_KEY": ""}), patch("google.genai.Client", lambda **kw: _FakeClient(_FakeModels(None))), patch.object(ws, "get_active_key", return_value=None):
            answer, sources, ok = _run(ws.search_grounded("кто президент Франции"))
        self.assertFalse(ok)
        self.assertEqual(answer, "")


class Test1_TavilyFallback(unittest.TestCase):
    """1.3: если grounding упал — fallback на Tavily."""

    def test_tavily_fallback_on_grounding_error(self):
        import modules.web_search as ws
        ws._clear_search_cache()
        os.environ["TAVILY_API_KEY"] = "fake-tavily"
        models = _FakeModels(None, exc=RuntimeError("grounding disabled"))
        tavily = _FakeTavilyClient([
            {"content": "Биткоин стоит около 80 млн рублей.", "url": "https://t.co/bitcoin"},
            {"content": "Цена биткоина в реальном времени.", "url": "https://t.co/price"},
        ])
        with patch("google.genai.Client", lambda **kw: _FakeClient(models)), patch.object(ws, "get_active_key", return_value="fake-key"), patch.object(ws, "mark_key_used", return_value=None), patch("tavily.AsyncTavilyClient", lambda **kw: tavily):
            answer, sources, ok = _run(ws.search_grounded("сколько стоит биткоин"))
        self.assertTrue(ok)
        self.assertIn("биткоин", answer.lower())
        self.assertIn("https://t.co/bitcoin", sources)
        self.assertEqual(tavily.calls, 1)


class Test1_SourceExclusion(unittest.TestCase):
    def test_extract_sources_dedupes(self):
        import modules.web_search as ws
        resp = _FakeResp("x", ["https://a", "https://a", "https://b"])
        self.assertEqual(ws._extract_sources(resp), ["https://a", "https://b"])

    def test_extract_sources_no_chunks(self):
        import modules.web_search as ws

        class _Empty:
            candidates = [MagicMock(grounding_metadata=None)]
        self.assertEqual(ws._extract_sources(_Empty()), [])


if __name__ == "__main__":
    unittest.main()
