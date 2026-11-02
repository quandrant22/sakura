"""Схема инструментов навигатора для desktop (scripts/export_tool_schema.py).

Снимок tests/fixtures/server_tools.json обязан совпадать с текущей spec
(sakura_core/browser_step.TOOL_SPEC). Spec поменялась — перегенерировать:
  venv/bin/python scripts/export_tool_schema.py tests/fixtures/server_tools.json
и отнести тот же файл в desktop/tests/fixtures/server_tools.json.

Run: python -m pytest tests/test_tool_schema.py -q
"""

import importlib.util
import json
from pathlib import Path

from sakura_core import browser_step as bs

ROOT = Path(__file__).resolve().parents[1]
FIXTURE = ROOT / "tests" / "fixtures" / "server_tools.json"


def _script():
    spec = importlib.util.spec_from_file_location("export_tool_schema",
                                                  ROOT / "scripts" / "export_tool_schema.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_export_matches_snapshot():
    assert json.loads(_script().render()) == json.loads(FIXTURE.read_text(encoding="utf-8"))
    assert _script().render() == FIXTURE.read_text(encoding="utf-8")


def test_export_covers_all_tools_with_note():
    data = bs.export_tools()
    assert data["format"] == "sakura.browser_tools/1"
    assert [t["name"] for t in data["tools"]] == list(bs.TOOLS)
    for tool in data["tools"]:
        assert "note" in tool["parameters"]["properties"]
        assert tool["parameters"]["required"][-1] == "note"
    assert data["server_args"] == {"page_shot": {"q_index": {"type": "integer"}}}


def test_function_declarations_built_from_same_spec():
    tools, _ = bs._tools()
    decls = {d.name: d for d in tools[0].function_declarations}
    for tool in bs.export_tools()["tools"]:
        params = decls[tool["name"]].parameters
        assert set(params.properties) == set(tool["parameters"]["properties"])
        assert list(params.required) == tool["parameters"]["required"]
        assert decls[tool["name"]].description == tool["description"]


def test_names_unchanged_for_desktop():
    """Имена инструментов и аргументов переводит desktop — их не менять."""
    args = {t["name"]: sorted(t["parameters"]["properties"]) for t in bs.export_tools()["tools"]}
    assert args == {
        "tabs_list": ["note"], "tabs_activate": ["note", "tab_id"],
        "tabs_new": ["note", "url"], "tabs_close": ["note", "tab_id"],
        "page_observe": ["note"], "page_act": ["action", "key", "note", "ref", "text"],
        "page_shot": ["crop_ref", "note"], "page_forms": ["note"], "page_questions": ["note"],
        "page_fill_form": ["fields", "note", "submit_ref"],
        "page_upload": ["file", "note", "ref"], "page_scroll": ["direction", "note", "ref"],
        "done": ["note", "summary"], "fail": ["note", "reason"],
    }


def test_fill_form_field_has_pairs():
    """page_fill_form.fields[]: прежние ref/value/checked + pairs [{row_ref, option_text}]."""
    tool = next(t for t in bs.export_tools()["tools"] if t["name"] == "page_fill_form")
    field = tool["parameters"]["properties"]["fields"]["items"]
    assert sorted(field["properties"]) == ["checked", "pairs", "ref", "value"]
    assert field["required"] == ["ref"]
    pair = field["properties"]["pairs"]
    assert pair["type"] == "array"
    assert pair["items"]["required"] == ["row_ref", "option_text"]
    tools, _ = bs._tools()
    decl = next(d for d in tools[0].function_declarations if d.name == "page_fill_form")
    assert "pairs" in decl.parameters.properties["fields"].items.properties
