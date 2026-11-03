"""Старый клиент agent/ не снимает экран сам по себе (DECISIONS V1).

Раньше ядро раз в 5 минут молча слало скриншот на сервер (`screen_context`):
без согласия, без фильтра приватных окон, без проверки защищённого канала.
Страж от возврата цикла: ни один модуль agent/ не формирует `screen_context`
и не определяет `_screen_analysis_loop`. Тот же страж для desktop/ —
desktop/tests/test_no_silent_capture.py.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

AGENT = Path(__file__).resolve().parents[1]
SOURCES = sorted(p for p in AGENT.rglob("*.py") if "tests" not in p.relative_to(AGENT).parts)


def test_sources_found():
    assert AGENT / "core" / "agent.py" in SOURCES


@pytest.mark.parametrize("path", SOURCES, ids=lambda p: str(p.relative_to(AGENT)))
def test_no_silent_screen_capture(path: Path):
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    for node in ast.walk(tree):
        if isinstance(node, ast.Constant) and node.value == "screen_context":
            pytest.fail(f"{path.relative_to(AGENT)}:{node.lineno}: клиент формирует screen_context")
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == "_screen_analysis_loop":
            pytest.fail(f"{path.relative_to(AGENT)}:{node.lineno}: вернулся фоновый цикл снятия экрана")
