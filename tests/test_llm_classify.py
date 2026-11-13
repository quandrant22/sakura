"""Тесты classify_action / make_llm_classify — контракт LlmClassify.

Run: python -m pytest tests/test_llm_classify.py -q

Проверяется парсинг ответа (id / null / проза / обёртки в кавычки) и async-контракт классификатора.
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
    return asyncio.run(coro)


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


def test_make_llm_classify_is_async(monkeypatch):
    monkeypatch.setattr(llm, "generate", _fake_generate("vps.status"))
    classify = llm.make_llm_classify()
    assert _run(classify("как там сервер", CATALOG)) == "vps.status"


def test_make_llm_classify_failure_is_none(monkeypatch):
    async def _boom(contents, **kwargs):
        raise RuntimeError("сеть лежит")
    monkeypatch.setattr(llm, "generate", _boom)
    classify = llm.make_llm_classify()
    assert _run(classify("как там сервер", CATALOG)) is None


def test_classify_action_with_pipe_param(monkeypatch):
    monkeypatch.setattr(llm, "generate", _fake_generate("music.play_track | nirvana"))
    res = _run(llm.classify_action("поставь нирвану", CATALOG))
    assert res == "music.play_track"
    assert res.action == "music.play_track"
    assert res.param == "nirvana"
    action, param = res
    assert action == "music.play_track"
    assert param == "nirvana"


def test_classify_action_with_json_param(monkeypatch):
    monkeypatch.setattr(llm, "generate", _fake_generate('{"id": "kettle.heat", "param": "85"}'))
    res = _run(llm.classify_action("нагрей до 85", CATALOG))
    assert res == "kettle.heat"
    assert res.action == "kettle.heat"
    assert res.param == "85"


def test_classify_system_prompt_rules():
    prompt = llm.CLASSIFY_SYSTEM
    assert "J.A.R.V.I.S." in prompt
    assert "null" in prompt
    assert "отрицание" in prompt
    assert "ПРЯМО СЕЙЧАС" in prompt