"""Выгрузка схемы инструментов навигатора browser agent в JSON.

    venv/bin/python scripts/export_tool_schema.py [путь]

Без пути — в stdout. Формат — фикстура desktop/tests/fixtures/server_tools.json:
  {"format": "sakura.browser_tools/1",
   "tools": [{"name", "description", "parameters": <JSON Schema аргументов, с note>}],
   "server_args": {tool: {arg: <JSON Schema>}}   — аргументы, которые добавляет сервер}
Источник — sakura_core/browser_step.TOOL_SPEC; снимок для сверки —
tests/fixtures/server_tools.json (tests/test_tool_schema.py).
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def render() -> str:
    from sakura_core.browser_step import export_tools
    return json.dumps(export_tools(), ensure_ascii=False, indent=2) + "\n"


def main() -> None:
    text = render()
    if len(sys.argv) > 1:
        Path(sys.argv[1]).write_text(text, encoding="utf-8")
    else:
        sys.stdout.write(text)


if __name__ == "__main__":
    main()
