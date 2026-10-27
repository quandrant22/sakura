"""server/browser-step S4: параметры генерации по модели (llm.filter_params).

Run: python -m pytest tests/test_gemma_params.py -q
"""

import asyncio
from types import SimpleNamespace

import config
from sakura_core import llm

JPEG = b"\xff\xd8\xff\xe0" + b"\x00" * 100


def test_filter_params_gemma_and_flash_lite(monkeypatch):
    monkeypatch.setattr(config, "GEMMA_PARAMS", ("max_output_tokens", "temperature", "tools"))
    cfg = {"max_output_tokens": 10, "temperature": 0.0, "top_p": 0.9, "tools": [1],
           "presence_penalty": 0.5, "safety_settings": [1], "system_instruction": None}
    assert llm.filter_params("gemma-4-26b-a4b-it", cfg) == {
        "max_output_tokens": 10, "temperature": 0.0, "tools": [1], "system_instruction": None}
    lite = llm.filter_params("gemini-3.5-flash-lite", cfg)
    assert "temperature" not in lite and "top_p" not in lite and lite["presence_penalty"] == 0.5
    assert llm.filter_params("gemini-3.1-flash-lite", cfg) == cfg


def _capture_generate(monkeypatch):
    seen = []

    class Models:
        def generate_content(self, model, contents, config):
            seen.append((model, config))
            return SimpleNamespace(text='{"type": "done", "reason": "ок"}')

    monkeypatch.setattr(llm, "get_client", lambda key: SimpleNamespace(models=Models()))
    monkeypatch.setattr(llm, "_initial_key", lambda k=None: "k")
    monkeypatch.setattr(config, "VISION_MODEL_CHAIN", ("gemini-3.5-flash-lite",))
    return seen


def test_computer_use_and_vision_send_no_sampling_to_flash_lite(monkeypatch):
    """computer_use/vision_request: temperature к gemini-3.5-flash-lite не уходит."""
    from google.genai import types as T
    seen = _capture_generate(monkeypatch)
    img = T.Part(inline_data=T.Blob(mime_type="image/jpeg", data=JPEG))
    asyncio.run(llm.generate([img, T.Part(text="q")], chain=config.VISION_MODEL_CHAIN,
                             max_tokens=200, temperature=0.0, safety=False, thinking=False))
    asyncio.run(llm.generate([img, T.Part(text="q")], chain=config.VISION_MODEL_CHAIN,
                             max_tokens=300, safety=False, thinking=False))
    assert [m for m, _ in seen] == ["gemini-3.5-flash-lite"] * 2
    assert all(c.temperature is None and c.top_p is None for _, c in seen)


def test_gemma_thinking_config_only_level():
    from google.genai import types as T
    full = T.ThinkingConfig(thinking_level="minimal", thinking_budget=0, include_thoughts=True)
    out = llm.filter_params("gemma-4-26b-a4b-it", {"thinking_config": full})
    tc = out["thinking_config"]
    assert tc.thinking_level == T.ThinkingLevel.MINIMAL or str(tc.thinking_level).lower().endswith("minimal")
    assert tc.thinking_budget is None and tc.include_thoughts is None
    # только budget — thinking_config не передаётся вовсе
    out = llm.filter_params("gemma-4-31b-it", {"thinking_config": T.ThinkingConfig(thinking_budget=0)})
    assert "thinking_config" not in out
    out = llm.filter_params("gemma-4-31b-it", {"thinking_config": {"thinking_level": "low",
                                                                    "thinking_budget": 5}})
    assert out["thinking_config"].thinking_budget is None
    # не-Gemma — без изменений
    assert llm.filter_params("gemini-3.1-flash-lite", {"thinking_config": full})["thinking_config"] is full


def test_generate_agent_thinking_level(monkeypatch):
    from sakura_core import rate_limiter as rl
    got = []

    async def raw(model, contents, timeout=None, **cfg):
        got.append(cfg)
        return SimpleNamespace(text="ok", usage_metadata=None)

    monkeypatch.setattr(llm, "generate_raw", raw)
    lim = rl.RateLimiter(rpm=100, rpd=100, path=None)
    asyncio.run(llm.generate_agent(["x"], chain=("gemma-4-26b-a4b-it",), limiter=lim,
                                   thinking_level="minimal"))
    asyncio.run(llm.generate_agent(["x"], chain=("gemma-4-31b-it",), limiter=lim))
    assert got[0]["thinking_config"].thinking_budget is None
    assert str(got[0]["thinking_config"].thinking_level).lower().endswith("minimal")
    assert "thinking_config" not in got[1]
