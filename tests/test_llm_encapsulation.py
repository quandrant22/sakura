"""Тест этапа 6: инкапсуляция LLM.

Проверяет:
1. generate_content / generate_content_stream вызываются ТОЛЬКО из sakura_core/llm.py
   (кроме tests/ и docs/).
2. NO_SAFETY и _thinking определены в sakura_core/llm.py.
3. generate() и stream_tokens() принимают safety/thinking параметры.
"""

import ast
import os
import pathlib


def _scan_generate_calls(root: str, exclude_dirs: tuple[str, ...] = ()) -> list[tuple[str, int, str]]:
    """Собрать все вызовы .generate_content / .generate_content_stream в .py файлах."""
    results = []
    exclude = set(exclude_dirs)
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames if d not in exclude]
        for fn in filenames:
            if not fn.endswith(".py"):
                continue
            fp = os.path.join(dirpath, fn)
            try:
                tree = ast.parse(pathlib.Path(fp).read_text(), filename=fp)
            except SyntaxError:
                continue
            for node in ast.walk(tree):
                if not isinstance(node, ast.Attribute):
                    continue
                if node.attr in ("generate_content", "generate_content_stream"):
                    results.append((fp, node.lineno, node.attr))
    return results


def test_generate_content_only_in_llm_module():
    """generate_content / generate_content_stream — только в sakura_core/llm.py, tests/, docs/."""
    root = str(pathlib.Path(__file__).resolve().parent.parent)
    calls = _scan_generate_calls(root, exclude_dirs=("venv", ".git", "__pycache__"))
    bad = [
        (fp, line, attr)
        for fp, line, attr in calls
        if "sakura_core/llm.py" not in fp
        and "tests/" not in fp
        and "docs/" not in fp
    ]
    assert not bad, (
        "generate_content found outside sakura_core/llm.py:\n"
        + "\n".join(f"  {fp}:{line} — {attr}" for fp, line, attr in bad)
    )


def test_no_safety_defined_in_llm():
    """NO_SAFETY (функция _no_safety) определена в sakura_core/llm.py."""
    llm_path = pathlib.Path(__file__).resolve().parent.parent / "sakura_core" / "llm.py"
    src = llm_path.read_text()
    assert "def _no_safety" in src, "_no_safety not found in sakura_core/llm.py"


def test_thinking_defined_in_llm():
    """_thinking определена в sakura_core/llm.py."""
    llm_path = pathlib.Path(__file__).resolve().parent.parent / "sakura_core" / "llm.py"
    src = llm_path.read_text()
    assert "def _thinking" in src, "_thinking not found in sakura_core/llm.py"


def test_generate_accepts_safety_thinking():
    """generate() принимает параметры safety и thinking."""
    import inspect
    from sakura_core.llm import generate
    sig = inspect.signature(generate)
    assert "safety" in sig.parameters, "generate() missing 'safety' parameter"
    assert "thinking" in sig.parameters, "generate() missing 'thinking' parameter"


def test_stream_tokens_accepts_safety_thinking():
    """stream_tokens() принимает параметры safety и thinking."""
    import inspect
    from sakura_core.llm import stream_tokens
    sig = inspect.signature(stream_tokens)
    assert "safety" in sig.parameters, "stream_tokens() missing 'safety' parameter"
    assert "thinking" in sig.parameters, "stream_tokens() missing 'thinking' parameter"


def test_voice_contents_respect_voice_history_limit(monkeypatch):
    import asyncio
    import config
    from config import VOICE_HISTORY_LIMIT
    from memory import memory
    from modules import web_search
    from sakura_core import llm

    history = [
        {"role": "user", "parts": [f"message {index}"]}
        for index in range(VOICE_HISTORY_LIMIT + 5)
    ]
    monkeypatch.setattr(memory, "get_history", lambda: history)
    monkeypatch.setattr(memory, "add_to_history", lambda *_args: None)
    monkeypatch.setattr(config, "get_active_key", lambda: "test-key")
    monkeypatch.setattr(config, "mark_key_used", lambda *_args: None)
    monkeypatch.setattr(web_search, "needs_search", lambda _text: False)

    async def fake_build_system(**_kwargs):
        return "system"

    async def fake_generate(*_args, **_kwargs):
        return "Готово."

    monkeypatch.setattr(llm, "_build_system", fake_build_system)
    monkeypatch.setattr(llm, "generate", fake_generate)
    seen = {}
    build_contents = llm._build_contents

    def capture_contents(*args, **kwargs):
        contents = build_contents(*args, **kwargs)
        seen["count"] = len(contents)
        seen["history_limit"] = kwargs["history_limit"]
        return contents

    monkeypatch.setattr(llm, "_build_contents", capture_contents)
    monkeypatch.setattr(
        llm, "spawn", lambda coroutine, **_kwargs: coroutine.close()
    )

    asyncio.run(llm.ask_gemini_voice("сделай громче"))

    assert seen["history_limit"] == VOICE_HISTORY_LIMIT
    assert seen["count"] <= VOICE_HISTORY_LIMIT + 1
