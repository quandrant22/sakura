"""Клиент не снимает экран сам по себе.

Раньше ядро раз в 5 минут молча слало скриншот на сервер (`screen_context`).
Кадр экрана теперь уходит только по явному действию пользователя
(`window_ask`) или по запросу сервера. Тест — страж от возврата цикла:
ни один модуль ядра (и старого агента) не формирует сообщение
`screen_context` и не определяет `_screen_analysis_loop`.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
CLIENT_DIRS = [REPO / "desktop" / "core", REPO / "agent" / "core", REPO / "agent"]


def _client_sources() -> list[Path]:
    files: set[Path] = set()
    for d in CLIENT_DIRS:
        if not d.is_dir():
            continue
        pattern = "*.py" if d.name == "agent" else "**/*.py"
        files.update(p for p in d.glob(pattern) if "tests" not in p.parts)
    return sorted(files)


SOURCES = _client_sources()


def test_sources_found():
    assert any(p.parts[-3:-1] == ("desktop", "core") for p in SOURCES), "не найдено ядро desktop/core"


@pytest.mark.parametrize("path", SOURCES, ids=lambda p: str(p.relative_to(REPO)))
def test_no_screen_context_message(path: Path):
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    for node in ast.walk(tree):
        if isinstance(node, ast.Constant) and node.value == "screen_context":
            pytest.fail(f"{path.relative_to(REPO)}:{node.lineno}: клиент формирует screen_context")
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == "_screen_analysis_loop":
            pytest.fail(f"{path.relative_to(REPO)}:{node.lineno}: вернулся фоновый цикл снятия экрана")
