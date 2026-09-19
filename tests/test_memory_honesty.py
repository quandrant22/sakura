"""
tests/test_memory_honesty.py — честность памяти не должна ходить в сеть
без повода: один эмбеддинг на вопрос о памяти и ни одного на команду.

Раньше один сбор системного промпта делал два одинаковых сетевых вызова
(подзабытые факты + противоречия) с одним и тем же текстом — ~0.8 с.

Run: python3 -m pytest tests/test_memory_honesty.py -q
"""
import os
import unittest
from unittest.mock import patch

os.environ.setdefault("MASTER_ID", "123456789")
os.environ.setdefault("TELEGRAM_TOKEN", "test:fake-token")

import memory.db as db  # noqa: E402
from modules.memory_honesty import (  # noqa: E402
    enrich_memory_context,
    get_honesty_context,
    is_recall_query,
)


class _EmbedCounter:
    """Подменяет сетевой эмбеддинг и считает вызовы."""

    def __init__(self):
        self.calls = []

    def __call__(self, text, task):
        self.calls.append((task, text))
        return [0.01] * db.EMBED_DIMS


class TestEmbedCache(unittest.TestCase):
    """_embed кэшируется по (task, text)."""

    def setUp(self):
        with db._embed_cache_lock:
            db._embed_cache.clear()

    def test_same_text_one_network_call(self):
        c = _EmbedCounter()
        with patch.object(db, "_embed_remote", c):
            a = db._embed("Следующий трек", "RETRIEVAL_QUERY")
            b = db._embed("Следующий трек", "RETRIEVAL_QUERY")
        self.assertEqual(len(c.calls), 1)
        self.assertIs(a, b)

    def test_different_task_type_is_other_key(self):
        c = _EmbedCounter()
        with patch.object(db, "_embed_remote", c):
            db._embed("Следующий трек", "RETRIEVAL_QUERY")
            db._embed("Следующий трек", "RETRIEVAL_DOCUMENT")
        self.assertEqual(len(c.calls), 2)

    def test_none_is_not_cached(self):
        """Нет ключа или упала сеть — не залипаем на None навсегда."""
        calls = []

        def none_remote(text, task):
            calls.append(text)
            return None

        with patch.object(db, "_embed_remote", none_remote):
            self.assertIsNone(db._embed("нет ключа", "RETRIEVAL_QUERY"))
            self.assertIsNone(db._embed("нет ключа", "RETRIEVAL_QUERY"))
        self.assertEqual(len(calls), 2)


class TestHonestyGate(unittest.TestCase):
    """Команды не платят за семантический поиск, вопросы о памяти — платят."""

    def _count(self, query):
        c = _EmbedCounter()
        with patch.object(db, "_embed", c):
            out = get_honesty_context(query)
        return out, len(c.calls)

    def test_command_makes_no_embed(self):
        for cmd in ("Следующий трек", "Громче", "Поставь на паузу",
                    "Выключи свет", "Открой ютуб", "Какой трек играет"):
            with self.subTest(cmd=cmd):
                out, n = self._count(cmd)
                self.assertEqual(n, 0, f"команда ушла в сеть: {cmd!r}")
                self.assertEqual(out, "")

    def test_recall_question_embeds_once(self):
        """Было два одинаковых вызова — стал один."""
        for q in ("что ты помнишь про мой день рождения",
                  "мы говорили про Крым?",
                  "вспомни, что я люблю",
                  "напомни мои задачи"):
            with self.subTest(q=q):
                _, n = self._count(q)
                self.assertEqual(n, 1, f"ожидал 1 эмбеддинг для {q!r}, получил {n}")

    def test_short_and_empty_query_skipped(self):
        for q in ("", "да", "ок"):
            with self.subTest(q=q):
                _, n = self._count(q)
                self.assertEqual(n, 0)

    def test_embed_failure_is_silent(self):
        with patch.object(db, "_embed", return_value=None):
            out = get_honesty_context("что ты помнишь про мой день рождения")
        self.assertEqual(out, "")


class TestRecallQuery(unittest.TestCase):
    """is_recall_query — позитивный список, не «угадай по вопросу»."""

    def test_recall(self):
        for q in ("что ты помнишь", "вспомни про Крым", "обо мне",
                  "как меня зовут", "расскажи, что было раньше"):
            self.assertTrue(is_recall_query(q), q)

    def test_not_recall(self):
        for q in ("", "   ", "Следующий трек", "Громче",
                  "Поставь на паузу", "Выключи свет", None):
            self.assertFalse(is_recall_query(q), q)


class TestEnrichMemoryContext(unittest.TestCase):
    """enrich_memory_context отдаёт сырой контекст, если дополнять нечем."""

    def test_command_returns_raw_untouched(self):
        raw = "ПАМЯТЬ О МАСТЕРЕ:\n  • Мастер находится дома"
        with patch("memory.db._embed") as emb:
            out = enrich_memory_context(raw, "Следующий трек")
        emb.assert_not_called()
        self.assertEqual(out, raw)

    def test_empty_raw_and_empty_query(self):
        self.assertEqual(enrich_memory_context("", ""), "")


if __name__ == "__main__":
    unittest.main()
