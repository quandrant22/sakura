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
