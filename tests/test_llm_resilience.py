import ast
import asyncio
import time
from types import SimpleNamespace

import pytest

import sakura_core.llm as llm


class _Client:
    def __init__(self, models):
        self.models = models


def _mock_keys(monkeypatch, keys=("key-1",)):
    monkeypatch.setattr(llm.config, "GEMINI_KEYS", list(keys))
    monkeypatch.setattr(llm.config, "get_active_key", lambda: keys[0])
    monkeypatch.setattr(llm.config, "mark_key_rate_limited", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(llm, "random", SimpleNamespace(random=lambda: 0.0))
    delays = []

    async def no_wait(delay):
        delays.append(delay)

    monkeypatch.setattr(llm.asyncio, "sleep", no_wait)
    return delays


def test_generate_retries_transient_twice_then_succeeds(monkeypatch):
    delays = _mock_keys(monkeypatch)
    calls = []

    class Models:
        def generate_content(self, *, model, **_kwargs):
            calls.append(model)
            if len(calls) < 3:
                raise RuntimeError("503 UNAVAILABLE")
            return SimpleNamespace(text="ok")

    monkeypatch.setattr(llm, "get_client", lambda _key: _Client(Models()))
    result = asyncio.run(llm.generate("hello", chain=("model-a",)))

    assert result == "ok"
    assert calls == ["model-a"] * 3
    assert delays == [1.0, 2.0]


def test_generate_moves_to_next_model_after_three_transient_failures(monkeypatch):
    _mock_keys(monkeypatch)
    calls = []

    class Models:
        def generate_content(self, *, model, **_kwargs):
            calls.append(model)
            if model == "model-a":
                raise RuntimeError("503 UNAVAILABLE")
            return SimpleNamespace(text="fallback")

    monkeypatch.setattr(llm, "get_client", lambda _key: _Client(Models()))
    result = asyncio.run(llm.generate("hello", chain=("model-a", "model-b")))

    assert result == "fallback"
    assert calls == ["model-a"] * 3 + ["model-b"]


def test_generate_rotates_key_on_429_without_sleep(monkeypatch):
    delays = _mock_keys(monkeypatch, ("key-1", "key-2"))
    keys = iter(("key-1", "key-2"))
    monkeypatch.setattr(llm.config, "get_active_key", lambda: next(keys, None))
    used = []

    class Models:
        def generate_content(self, *, model, **_kwargs):
            used.append(active_key[0])
            if active_key[0] == "key-1":
                raise RuntimeError("429 RESOURCE_EXHAUSTED")
            return SimpleNamespace(text="ok")

    active_key = [None]

    def get_client(key):
        active_key[0] = key
        return _Client(Models())

    monkeypatch.setattr(llm, "get_client", get_client)
    result = asyncio.run(llm.generate("hello", chain=("model-a",)))

    assert result == "ok"
    assert used == ["key-1", "key-2"]
    assert delays == []


def test_generate_moves_to_next_model_immediately_on_404(monkeypatch):
    _mock_keys(monkeypatch)
    calls = []

    class Models:
        def generate_content(self, *, model, **_kwargs):
            calls.append(model)
            if model == "model-a":
                raise RuntimeError("404 NOT_FOUND")
            return SimpleNamespace(text="fallback")

    monkeypatch.setattr(llm, "get_client", lambda _key: _Client(Models()))
    result = asyncio.run(llm.generate("hello", chain=("model-a", "model-b")))

    assert result == "fallback"
    assert calls == ["model-a", "model-b"]


def test_stream_does_not_retry_after_first_token(monkeypatch):
    _mock_keys(monkeypatch)
    calls = []

    class Models:
        def generate_content_stream(self, **_kwargs):
            calls.append(1)
            yield SimpleNamespace(text="partial")
            raise RuntimeError("503 UNAVAILABLE")

    monkeypatch.setattr(llm, "get_client", lambda _key: _Client(Models()))

    async def collect():
        return [token async for token in llm.stream_tokens("hello", chain=("model-a",))]

    assert asyncio.run(collect()) == ["partial"]
    assert len(calls) == 1


def test_generate_deadline_bounds_slow_request(monkeypatch):
    _mock_keys(monkeypatch)

    class Models:
        def generate_content(self, **_kwargs):
            time.sleep(0.2)
            return SimpleNamespace(text="too late")

    monkeypatch.setattr(llm, "get_client", lambda _key: _Client(Models()))

    async def measure():
        started = time.monotonic()
        result = await llm.generate("hello", chain=("model-a",), timeout=0.05)
        return result, time.monotonic() - started

    result, elapsed = asyncio.run(measure())
    assert result == ""
    assert elapsed < 1.0


def test_stream_deadline_bounds_slow_request(monkeypatch):
    _mock_keys(monkeypatch)

    class Models:
        def generate_content_stream(self, **_kwargs):
            time.sleep(0.2)
            yield SimpleNamespace(text="too late")

    monkeypatch.setattr(llm, "get_client", lambda _key: _Client(Models()))

    async def measure():
        started = time.monotonic()
        result = [token async for token in llm.stream_tokens(
            "hello", chain=("model-a",), timeout=0.05,
        )]
        return result, time.monotonic() - started

    result, elapsed = asyncio.run(measure())
    assert result == []
    assert elapsed < 1.0


def test_error_handler_has_no_recursive_ask_gemini_call():
    tree = ast.parse(open(llm.__file__, encoding="utf-8").read())
    handler = next(node for node in tree.body
                   if isinstance(node, ast.AsyncFunctionDef)
                   and node.name == "_handle_gemini_error")
    assert not any(isinstance(node, ast.Call)
                   and isinstance(node.func, ast.Name)
                   and node.func.id == "ask_gemini"
                   for node in ast.walk(handler))
