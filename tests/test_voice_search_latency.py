"""fix/voice-search-latency: голосовой ответ с поиском не молчит.

Журнал 2026-11-01: запросы для Parallel составлялись моделью с thinking=True
без таймаута (15 с), ответ модели упирался в 8 с — пустой ответ и тишина.

Run: python -m pytest tests/test_voice_search_latency.py -q
"""
import asyncio

import modules.parallel_search as ps
from sakura_core import llm


def test_query_builder_is_fast(monkeypatch):
    seen = {}

    async def fake_generate(prompt, **kw):
        seen.update(kw)
        return '["Scrap Mechanic механическая станция"]'
    monkeypatch.setattr(ps, "_llm_generate", fake_generate)
    out = asyncio.run(ps._model_queries("делать по квесту механическая станция"))
    assert out
    assert seen["thinking"] is False and seen["timeout"] == ps.QUERY_TIMEOUT_S <= 5


def test_query_builder_timeout_falls_back(monkeypatch):
    async def slow(prompt, **kw):
        raise TimeoutError
    monkeypatch.setattr(ps, "_llm_generate", slow)
    queries = asyncio.run(ps.build_search_queries("где найти паяльник в Scrap Mechanic"))
    assert queries and all(isinstance(q, str) and q for q in queries)


def test_given_queries_skip_model(monkeypatch):
    """Готовый запрос (зрение) — модель для запросов не зовётся."""
    called, sent = [], []

    async def model(*a, **k):
        called.append(1)
        return []

    async def rpc(client, sid, msg):
        if msg.get("method") == "initialize":
            return 200, {}, [{"id": 1, "result": {}}]
        if msg.get("method") == "tools/call":
            sent.append(msg["params"]["arguments"])
            return 200, {}, [{"id": 2, "result": {"structuredContent": {"results": [
                {"url": "https://wiki.example/a", "title": "A", "excerpts": ["Паяльник на складе."]}]}}}]
        return 202, {}, []
    class Client:
        def __init__(self, *a, **k):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return False
    monkeypatch.setattr(ps.httpx, "AsyncClient", Client)
    monkeypatch.setattr(ps, "_model_queries", model)
    monkeypatch.setattr(ps, "_rpc", rpc)
    text, _sources, ok = asyncio.run(ps.parallel_search("x", queries=["Scrap Mechanic «паяльник»"]))
    assert ok and called == [] and "Паяльник" in text
    assert sent[0]["search_queries"] == ['Scrap Mechanic "паяльник"']


def test_voice_constants_fit_turn_watchdog():
    import config
    assert llm.VOICE_SEARCH_TIMEOUT_S > llm.VOICE_LLM_TIMEOUT_S
    # поиск (≤ ~5 с с запросами) + ответ укладываются в сторож хода
    assert llm.VOICE_SEARCH_TIMEOUT_S + ps.QUERY_TIMEOUT_S + 5 < config.TURN_TIMEOUT_S
    assert llm.VOICE_EMPTY_REPLY
