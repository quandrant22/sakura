import ast
import asyncio
import time
from pathlib import Path
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


def test_generate_moves_to_next_model_on_empty_response(monkeypatch, caplog):
    _mock_keys(monkeypatch)
    calls = []

    class Models:
        def generate_content(self, *, model, **_kwargs):
            calls.append(model)
            return SimpleNamespace(text="  " if model == "model-a" else "fallback")

    monkeypatch.setattr(llm, "get_client", lambda _key: _Client(Models()))
    with caplog.at_level("INFO", logger="sakura.llm"):
        result = asyncio.run(llm.generate("hello", chain=("model-a", "model-b")))

    assert result == "fallback"
    assert calls == ["model-a", "model-b"]
    assert "code=empty" in caplog.text


def test_generate_builds_valid_gemma4_config(monkeypatch):
    _mock_keys(monkeypatch)
    captured = {}
    model_name = "gemma-4-26b-a4b-it"

    class Models:
        def generate_content(self, *, model, contents, config):
            captured.update(model=model, contents=contents, config=config)
            return SimpleNamespace(text="ok")

    monkeypatch.setattr(llm, "get_client", lambda _key: _Client(Models()))
    system_prompt = "Ты — Сакура. Отвечай кратко и естественно."
    result = asyncio.run(llm.generate(
        "Привет", system=system_prompt, model=model_name,
        chain=(model_name,), safety=True, thinking=True,
    ))

    from google.genai import types

    assert result == "ok"
    assert captured["model"] == model_name
    assert isinstance(captured["config"], types.GenerateContentConfig)
    assert captured["config"].system_instruction == system_prompt
    assert {setting.category for setting in captured["config"].safety_settings} == {
        types.HarmCategory.HARM_CATEGORY_HARASSMENT,
        types.HarmCategory.HARM_CATEGORY_HATE_SPEECH,
        types.HarmCategory.HARM_CATEGORY_SEXUALLY_EXPLICIT,
        types.HarmCategory.HARM_CATEGORY_DANGEROUS_CONTENT,
        types.HarmCategory.HARM_CATEGORY_CIVIC_INTEGRITY,
    }
    assert captured["config"].thinking_config is None


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


@pytest.mark.parametrize("api", ("generate", "stream"))
@pytest.mark.parametrize("image_field", ("inline_data", "file_data"))
@pytest.mark.parametrize("wrapped", (False, True))
def test_image_requests_use_vision_chain(monkeypatch, api, image_field, wrapped):
    _mock_keys(monkeypatch)
    monkeypatch.setattr(llm.config, "MODEL_CHAIN", ("chat-model",))
    monkeypatch.setattr(llm.config, "VISION_MODEL_CHAIN", ("vision-model",))
    image_part = SimpleNamespace(**{
        "inline_data": None,
        "file_data": None,
        image_field: SimpleNamespace(mime_type="image/png"),
    })
    contents = ([SimpleNamespace(parts=[image_part])] if wrapped else [image_part])
    calls = []

    class Models:
        def generate_content(self, *, model, **_kwargs):
            calls.append(model)
            return SimpleNamespace(text="ok")

        def generate_content_stream(self, *, model, **_kwargs):
            calls.append(model)
            yield SimpleNamespace(text="ok")

    monkeypatch.setattr(llm, "get_client", lambda _key: _Client(Models()))

    async def run_api():
        if api == "generate":
            return await llm.generate(contents)
        return "".join([token async for token in llm.stream_tokens(contents)])

    assert asyncio.run(run_api()) == "ok"
    assert calls == ["vision-model"]


@pytest.mark.parametrize("api", ("generate", "stream"))
def test_text_requests_use_path_chain(monkeypatch, api):
    _mock_keys(monkeypatch)
    monkeypatch.setattr(llm.config, "MODEL_CHAIN", ("chat-model", "chat-fallback"))
    monkeypatch.setattr(llm.config, "VISION_MODEL_CHAIN", ("vision-model",))
    calls = []

    class Models:
        def generate_content(self, *, model, **_kwargs):
            calls.append(model)
            return SimpleNamespace(text="ok")

        def generate_content_stream(self, *, model, **_kwargs):
            calls.append(model)
            yield SimpleNamespace(text="ok")

    monkeypatch.setattr(llm, "get_client", lambda _key: _Client(Models()))

    async def run_api():
        if api == "generate":
            return await llm.generate("hello")
        return "".join([token async for token in llm.stream_tokens("hello")])

    assert asyncio.run(run_api()) == "ok"
    assert calls == ["chat-model"]


def test_ask_gemini_defaults_to_model_chain_without_history(monkeypatch, caplog):
    monkeypatch.setattr(llm.config, "VOICE_HISTORY_LIMIT", 10)
    monkeypatch.setattr(llm.config, "MODEL_CHAIN", ("chat",))
    monkeypatch.setattr(llm.config, "VOICE_MODEL_CHAIN", ("voice",))
    monkeypatch.setattr(llm.config, "BACKGROUND_MODEL_CHAIN", ("background",))

    assert llm._chain_for_request(30, True) == ("chat",)
    assert llm._chain_for_request(10, False) == ("chat",)
    assert llm._chain_for_request(30, False) == ("chat",)
    assert "using MODEL_CHAIN" in caplog.text


def test_all_save_history_false_ask_calls_set_chain():
    root = Path(__file__).resolve().parents[1]
    missed = []
    for directory in ("adapters", "modules", "sakura_core"):
        for path in (root / directory).rglob("*.py"):
            tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
            names = {"ask_gemini", "ask_gemini_fn"}
            for node in ast.walk(tree):
                if isinstance(node, ast.ImportFrom):
                    names.update(
                        alias.asname or alias.name
                        for alias in node.names
                        if alias.name == "ask_gemini"
                    )
            for node in ast.walk(tree):
                if not isinstance(node, ast.Call):
                    continue
                callee = (node.func.id if isinstance(node.func, ast.Name)
                          else node.func.attr if isinstance(node.func, ast.Attribute)
                          else None)
                keywords = {keyword.arg: keyword.value for keyword in node.keywords}
                save_history = keywords.get("save_history")
                if (callee in names and isinstance(save_history, ast.Constant)
                        and save_history.value is False and "chain" not in keywords):
                    missed.append(f"{path.relative_to(root)}:{node.lineno}")

    assert not missed, "ask_gemini(save_history=False) without chain=: " + ", ".join(missed)


def test_model_chain_parser_preserves_legacy_and_child_defaults(monkeypatch):
    import config

    monkeypatch.delenv("MODEL_CHAIN", raising=False)
    monkeypatch.delenv("VOICE_MODEL_CHAIN", raising=False)
    assert config._parse_model_chain("MODEL_CHAIN", ("main", "fallback")) == (
        "main", "fallback",
    )
    default_chain = config._parse_model_chain("MODEL_CHAIN", ("main", "fallback"))
    assert config._parse_model_chain("VOICE_MODEL_CHAIN", default_chain) == default_chain

    monkeypatch.setenv("MODEL_CHAIN", "first, second,first,,")
    assert config._parse_model_chain("MODEL_CHAIN", ("main",)) == ("first", "second")


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
