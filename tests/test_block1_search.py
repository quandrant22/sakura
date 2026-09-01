"""
Регрессионные тесты БЛОКА 1 — поиск через Parallel Search MCP.

Run:  python3 -m pytest tests/test_block1_search.py -q

Моки: никакого сетевого доступа. Имитируются ответы MCP-сервера Parallel
(реальный формат tools/call web_search: structuredContent + content.text).
При сбое поиска ожидается честный отказ (ok=False).
"""
import os
import sys
import asyncio
import json
import unittest
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


# ── фиктивный источник поиска (Parallel MCP) ────────────────────────────

def _mcp_result(items, is_error=False, structured=True):
    """MCP-ответ tools/call web_search в реальном формате Parallel.

    items: [(url, title, [excerpts]), ...]
    structured=True → structuredContent; False → тот же JSON в content[0].text.
    """
    results = [
        {"url": u, "title": t, "publish_date": None, "excerpts": e}
        for (u, t, e) in items
    ]
    payload = {"search_id": "search_test", "results": results,
               "warnings": [], "session_id": "test-session"}
    if structured:
        return {"isError": is_error, "structuredContent": payload, "content": []}
    return {"isError": is_error, "structuredContent": {},
            "content": [{"type": "text",
                         "text": json.dumps(payload, ensure_ascii=False)}]}


class _FakeParallel:
    """Подменяет modules.parallel_search.parallel_search (импорт внутри вызова)."""

    def __init__(self, result):
        self._result = result
        self.calls = 0
        self.last_query = None

    async def __call__(self, query, max_results=5):
        self.calls += 1
        self.last_query = query
        if isinstance(self._result, Exception):
            raise self._result
        return self._result


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


class Test1_ParallelPath(unittest.TestCase):
    """1.2: search_grounded → Parallel MCP: ответ + источники + кэш."""

    def test_search_returns_answer_and_sources(self):
        import modules.parallel_search as ps
        import modules.web_search as ws
        ws._clear_search_cache()
        fake = _FakeParallel((
            "Макрон — действующий президент Франции с 2017 года.",
            ["https://ru.wikipedia.org/wiki/Франция"],
            True,
        ))
        with patch.object(ps, "parallel_search", fake):
            answer, sources, ok = _run(ws.search_grounded("кто сейчас президент Франции"))
        self.assertTrue(ok)
        self.assertIn("Макрон", answer)
        self.assertEqual(sources, ["https://ru.wikipedia.org/wiki/Франция"])
        self.assertEqual(fake.calls, 1)
        self.assertEqual(fake.last_query, "кто сейчас президент Франции")

    def test_sources_deduped_by_domain_and_capped(self):
        import modules.parallel_search as ps
        import modules.web_search as ws
        ws._clear_search_cache()
        urls = [
            "https://ru.wikipedia.org/wiki/Франция",
            "https://ru.wikipedia.org/wiki/Макрон",
            "https://www.lenta.ru/news/1",
            "https://lenta.ru/news/2",
            "https://a.example/1",
            "https://b.example/1",
            "https://c.example/1",
        ]
        fake = _FakeParallel(("факты", urls, True))
        with patch.object(ps, "parallel_search", fake):
            _, sources, ok = _run(ws.search_grounded("кто президент Франции"))
        self.assertTrue(ok)
        # ru.wikipedia/Макрон и www.lenta/news/2 дедупнуты по домену; кап 5
        self.assertEqual(
            sources,
            ["https://ru.wikipedia.org/wiki/Франция", "https://www.lenta.ru/news/1",
             "https://a.example/1", "https://b.example/1", "https://c.example/1"],
        )

    def test_cached_no_repeat_call(self):
        import modules.parallel_search as ps
        import modules.web_search as ws
        ws._clear_search_cache()
        fake = _FakeParallel(("ответ", ["https://x.ru"], True))
        with patch.object(ps, "parallel_search", fake):
            _run(ws.search_grounded("кто президент Франции"))
            _run(ws.search_grounded("КТО ПРЕЗИДЕНТ ФРАНЦИИ"))
        self.assertEqual(fake.calls, 1), "кэш 30 минут: повтор не бьёт по rate-лимитам"

    def test_facts_capped_at_4000_chars(self):
        import modules.parallel_search as ps
        import modules.web_search as ws
        ws._clear_search_cache()
        fake = _FakeParallel(("Предложение фактов. " * 400, ["https://x.ru"], True))
        with patch.object(ps, "parallel_search", fake):
            answer, _, ok = _run(ws.search_grounded("кто президент Франции"))
        self.assertTrue(ok)
        self.assertLessEqual(len(answer), 4000)


class Test1_ParallelFailure(unittest.TestCase):
    """1.3: если поиск упал — честный отказ (ok=False), без фолбэков."""

    def test_not_ok_passthrough(self):
        import modules.parallel_search as ps
        import modules.web_search as ws
        ws._clear_search_cache()
        fake = _FakeParallel(("", [], False))
        with patch.object(ps, "parallel_search", fake):
            answer, sources, ok = _run(ws.search_grounded("кто президент Франции"))
        self.assertFalse(ok)
        self.assertEqual(answer, "")
        self.assertEqual(sources, [])
        self.assertEqual(fake.calls, 1), "фолбэков нет — ровно один вызов поиска"

    def test_exception_returns_not_ok(self):
        import modules.parallel_search as ps
        import modules.web_search as ws
        ws._clear_search_cache()
        fake = _FakeParallel(RuntimeError("mcp down"))
        with patch.object(ps, "parallel_search", fake):
            answer, sources, ok = _run(ws.search_grounded("кто президент Франции"))
        self.assertFalse(ok)
        self.assertEqual((answer, sources), ("", []))


class Test1_ParallelParsing(unittest.TestCase):
    """Парсер tools/call web_search — реальный формат Parallel MCP."""

    def test_structured_content(self):
        from modules.parallel_search import _parse_result
        res = _mcp_result([
            ("https://ru.wikipedia.org/wiki/Франция", "Президент Франции",
             ["Макрон — президент Франции."]),
            ("https://www.elysee.fr/en/", "Élysée", []),
        ])
        text, urls, ok = _parse_result(res)
        self.assertTrue(ok)
        self.assertIn("Макрон", text)
        self.assertEqual(urls, ["https://ru.wikipedia.org/wiki/Франция",
                                "https://www.elysee.fr/en/"])

    def test_text_json_fallback(self):
        from modules.parallel_search import _parse_result
        res = _mcp_result([("https://x.ru", "Титул", ["факт"])], structured=False)
        text, urls, ok = _parse_result(res)
        self.assertTrue(ok)
        self.assertIn("факт", text)
        self.assertEqual(urls, ["https://x.ru"])

    def test_is_error_returns_not_ok(self):
        from modules.parallel_search import _parse_result
        self.assertEqual(_parse_result(_mcp_result([], is_error=True)), ("", [], False))

    def test_empty_results_returns_not_ok(self):
        from modules.parallel_search import _parse_result
        self.assertEqual(_parse_result(_mcp_result([])), ("", [], False))

    def test_max_results_cap(self):
        from modules.parallel_search import _parse_result
        res = _mcp_result([(f"https://s{i}.example/p", "t", ["e"]) for i in range(8)])
        _, urls, ok = _parse_result(res, max_results=5)
        self.assertTrue(ok)
        self.assertEqual(len(urls), 5)

    def test_keywords_strips_punctuation(self):
        from modules.parallel_search import _keywords
        self.assertEqual(_keywords("кто сейчас президент Франции?"),
                         ["кто сейчас президент Франции"])
        self.assertTrue(_keywords("тест")[0])


class Test1_DedupDomains(unittest.TestCase):
    def test_dedupes_by_domain(self):
        import modules.web_search as ws
        self.assertEqual(
            ws._dedup_domains([
                "https://ru.wikipedia.org/wiki/Франция",
                "https://ru.wikipedia.org/wiki/Макрон",
                "https://www.lenta.ru/news/1",
                "https://lenta.ru/news/2",
            ]),
            ["https://ru.wikipedia.org/wiki/Франция", "https://www.lenta.ru/news/1"],
        )

    def test_cap_five(self):
        import modules.web_search as ws
        urls = [f"https://site{i}.example/page" for i in range(8)]
        self.assertEqual(len(ws._dedup_domains(urls)), 5)

    def test_skips_empty(self):
        import modules.web_search as ws
        self.assertEqual(ws._dedup_domains(["", "https://a.ru", None]), ["https://a.ru"])


class Test1_ClipAnswer(unittest.TestCase):
    def test_short_answer_untouched(self):
        from modules.web_search import _clip_answer
        self.assertEqual(_clip_answer("Короткий ответ."), "Короткий ответ.")

    def test_long_answer_clipped_at_sentence(self):
        from modules.web_search import _clip_answer
        text = "Предложение один. " * 300  # ~5400 символов
        out = _clip_answer(text)
        self.assertLessEqual(len(out), 2000)
        self.assertTrue(out.endswith("."))

    def test_long_answer_no_sentence_fallback(self):
        from modules.web_search import _clip_answer
        out = _clip_answer("а" * 2500)
        self.assertLessEqual(len(out), 2001)  # обрезок + многоточие
        self.assertTrue(out.endswith("…"))


if __name__ == "__main__":
    unittest.main()
