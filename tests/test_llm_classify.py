"""Тесты classify_action / make_llm_classify — контракт LlmClassify.

Run: python -m pytest tests/test_llm_classify.py -q

В продакшене пока не подключено (Router(llm_classify=None)): проверяется
парсинг ответа (id / null / проза / обёртки в кавычки) и синхронный мост.
"""

import asyncio

import sakura_core.llm as llm

CATALOG = "- music.next: следующий трек\n- vps.status: статус сервера"


def _fake_generate(answer):
    async def _gen(contents, **kwargs):
        return answer
    return _gen


def _run(coro):
    """Паттерн репозитория: asyncio.run() снимает глобальный цикл и ломает
    легаси-тесты (см. tests/test_music_domain.py)."""
    return asyncio.get_event_loop().run_until_complete(coro)


def test_classify_action_returns_id(monkeypatch):
    monkeypatch.setattr(llm, "generate", _fake_generate("music.next"))
    assert _run(llm.classify_action("врубай следующий", CATALOG)) == "music.next"


def test_classify_action_null_is_none(monkeypatch):
    monkeypatch.setattr(llm, "generate", _fake_generate("null"))
    assert _run(llm.classify_action("болтаем о космосе", CATALOG)) is None


def test_classify_action_strips_backticks_and_noise(monkeypatch):
    monkeypatch.setattr(llm, "generate", _fake_generate("  `music.next`\n"))
    assert _run(llm.classify_action("дальше", CATALOG)) == "music.next"


def test_classify_action_prose_is_none(monkeypatch):
    monkeypatch.setattr(
        llm, "generate",
        _fake_generate("Конечно! music.next — вот подходящее действие"))
    assert _run(llm.classify_action("следующий", CATALOG)) is None


def test_classify_action_empty_inputs(monkeypatch):
    def _boom(*a, **k):
        raise AssertionError("generate не должен зваться на пустых входах")
    monkeypatch.setattr(llm, "generate", _boom)
    assert _run(llm.classify_action("", CATALOG)) is None
    assert _run(llm.classify_action("привет", "")) is None


def test_make_llm_classify_bridges_to_sync(monkeypatch):
    monkeypatch.setattr(llm, "generate", _fake_generate("vps.status"))
    classify = llm.make_llm_classify()
    assert classify("как там сервер", CATALOG) == "vps.status"


def test_make_llm_classify_failure_is_none(monkeypatch):
    async def _boom(contents, **kwargs):
        raise RuntimeError("сеть лежит")
    monkeypatch.setattr(llm, "generate", _boom)
    classify = llm.make_llm_classify()
    assert classify("как там сервер", CATALOG) is None