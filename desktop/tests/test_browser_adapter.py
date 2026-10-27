"""browser_adapter: инструменты сервера (схема — источник истины) → действия расширения 3.2.0.

Контракт: fixtures/server_tools.json — точная копия выгрузки сервера (scripts/export_tool_schema.py
ветки server/browser-step; обновляет desktop/scripts/sync_server_tools.*), формат
sakura.browser_tools/1. Для каждого tool и каждого значения enum, с аргументами server_args и без,
to_ext даёт действие, которое есть в расширении (lib/agent.js), op — из content.js act, а все
обязательные аргументы действия расширения заполнены."""
import itertools
import json
import re
from pathlib import Path

import pytest

from desktop.core import browser_adapter as A

HERE = Path(__file__).resolve().parent
FORMAT = "sakura.browser_tools/1"


def load_schema(doc: dict) -> tuple[dict, dict]:
    """Выгрузка сервера → ({tool: {props, required}}, server_args). Незнакомый формат — ошибка."""
    if doc.get("format") != FORMAT:
        raise ValueError(f"неизвестный формат схемы инструментов: {doc.get('format')!r}")
    tools = {}
    for t in doc["tools"]:
        params = t["parameters"]
        assert params["type"] == "object", t["name"]
        tools[t["name"]] = {"props": params.get("properties", {}), "required": params.get("required", [])}
    return tools, doc.get("server_args", {})


SCHEMA, SERVER_ARGS = load_schema(json.loads((HERE / "fixtures" / "server_tools.json").read_text(encoding="utf-8")))
EXT = HERE.parent / "extension"
AGENT_JS = (EXT / "lib" / "agent.js").read_text(encoding="utf-8")
CONTENT_JS = (EXT / "content.js").read_text(encoding="utf-8")

EXT_ACTIONS = set(re.findall(r'"((?:tabs|page|agent_window)\.[a-z_]+)"',
                             AGENT_JS[AGENT_JS.index("const ACTIONS"):AGENT_JS.index("]);")]))
_act = CONTENT_JS[CONTENT_JS.index("async function act(a)"):CONTENT_JS.index("// ── page.scroll")]
CONTENT_OPS = set(re.findall(r'case "([a-z_]+)":', _act))

SAMPLE_BY_TYPE = {"string": "f0:e3", "integer": 2, "boolean": True, "number": 1.5}
SAMPLE = {"tab_id": 12, "url": "https://example.org/", "ref": "f0:e3", "text": "Анна", "key": "Enter",
          "crop_ref": "f0:e7", "q_index": 2, "file": "cv.pdf", "submit_ref": "f0:e9", "note": "проверка"}
CTX = {"tab_id": 11, "window_id": 7, "issue_file": lambda name: "tok-" + name}


def _sample(name: str, spec: dict):
    """Значение аргумента по его JSON Schema. Массив объектов — по элементу на каждое
    необязательное свойство items (fields: [{ref, value}, {ref, checked}])."""
    if name in SAMPLE:
        return SAMPLE[name]
    if spec.get("type") == "array":
        props, required = spec["items"]["properties"], spec["items"].get("required", [])
        base = {k: _sample(k, props[k]) for k in required}
        return [base | {k: _sample(k, v)} for k, v in props.items() if k not in required]
    return SAMPLE_BY_TYPE[spec["type"]]


def _cases():
    for tool, spec in SCHEMA.items():
        if tool in ("done", "fail"):
            continue
        props = spec["props"]
        enums = {k: v["enum"] for k, v in props.items() if "enum" in v}
        names = list(enums)
        extra = SERVER_ARGS.get(tool, {})
        for combo in itertools.product(*[enums[n] for n in names]) or [()]:
            args = {k: _sample(k, v) for k, v in props.items() if k not in enums}
            args.update(dict(zip(names, combo, strict=True)))
            yield pytest.param(tool, args, id=f"{tool}-{'-'.join(combo) or 'all'}")
            if extra:
                yield pytest.param(tool, args | {k: _sample(k, v) for k, v in extra.items()},
                                   id=f"{tool}-{'-'.join(combo) or 'all'}-server_args")
        # только обязательные аргументы (без enum-кортежей — их покрывает полный набор)
        if not enums:
            yield pytest.param(tool, {k: _sample(k, props[k]) for k in spec["required"]}, id=f"{tool}-required")


def test_schema_format_is_checked():
    with pytest.raises(ValueError, match="неизвестный формат"):
        load_schema({"format": "sakura.browser_tools/2", "tools": []})
    with pytest.raises(ValueError, match="неизвестный формат"):
        load_schema({"tools": {}})       # прежняя рукописная схема без format


def test_server_args_are_known():
    assert SERVER_ARGS == {"page_shot": {"q_index": {"type": "integer"}}}
    for tool, extra in SERVER_ARGS.items():
        assert tool in SCHEMA and not set(extra) & set(SCHEMA[tool]["props"])


def test_extension_sources_parsed():
    assert {"page.act", "page.fill_form", "page.scroll", "tabs.new"} <= EXT_ACTIONS
    assert {"click", "fill", "select", "check", "uncheck", "press", "hover", "focus"} <= CONTENT_OPS
    assert set(A.EXT_REQUIRED) <= EXT_ACTIONS       # у расширения есть и действия вне схемы сервера (mute, pin…)
    assert set(A.ACT_OPS.values()) <= CONTENT_OPS


@pytest.mark.parametrize("tool,args", list(_cases()))
def test_contract_every_server_tool_maps_to_extension(tool, args):
    action, ext = A.to_ext(tool, args, "s9", **CTX)
    assert action in EXT_ACTIONS
    missing = [k for k in A.EXT_REQUIRED[action] if ext.get(k) in (None, "")]
    assert missing == []
    if action == "page.shot":
        assert A.shot_target(ext)
    if action == "page.act":
        assert ext["op"] in CONTENT_OPS
    if "ref" in ext or "values" in ext:
        assert ext["snapshot_id"] == "s9" or action == "page.upload"
    if args.get("submit_ref"):
        f_action, f_args = A.submit_followup(tool, args, "s10", tab_id=11)
        assert f_action in EXT_ACTIONS and f_args["op"] in CONTENT_OPS
        assert all(f_args.get(k) for k in A.EXT_REQUIRED[f_action])


def test_schema_enums_are_all_mapped():
    assert set(SCHEMA["page_act"]["props"]["action"]["enum"]) == set(A.ACT_OPS)
    assert set(SCHEMA["page_scroll"]["props"]["direction"]["enum"]) == {"up", "down", "top", "bottom"}
    assert all("note" in s["required"] for s in SCHEMA.values())
    assert set(SCHEMA) - {"done", "fail"} == {
        "tabs_list", "tabs_activate", "tabs_new", "tabs_close", "page_observe", "page_act", "page_shot",
        "page_forms", "page_questions", "page_fill_form", "page_upload", "page_scroll"}


# ── перевод аргументов ────────────────────────────────────────────

@pytest.mark.parametrize("action,expected", [
    ({"action": "type", "text": "a\nb"}, {"op": "fill", "value": "a\nb"}),
    ({"action": "clear"}, {"op": "fill", "value": ""}),
    ({"action": "submit"}, {"op": "click"}),
    ({"action": "select", "text": "Москва"}, {"op": "select", "value": "Москва"}),
    ({"action": "press", "key": "Tab"}, {"op": "press", "value": "Tab"}),
    ({"action": "press"}, {"op": "press", "value": "Enter"}),
    ({"action": "click"}, {"op": "click"}),
    ({"action": "check"}, {"op": "check"}),
    ({"action": "hover"}, {"op": "hover"}),
])
def test_page_act_mapping(action, expected):
    name, ext = A.to_ext("page_act", {"ref": "f0:e1", **action}, "s1", tab_id=3)
    assert name == "page.act"
    assert ext == {"tab_id": 3, "snapshot_id": "s1", "ref": "f0:e1", **expected}


def test_page_act_errors():
    with pytest.raises(A.AdapterError) as e:
        A.to_ext("page_act", {"ref": "f0:e1", "action": "type"}, "s1", tab_id=3)
    assert e.value.status == "error"
    with pytest.raises(A.AdapterError) as e:
        A.to_ext("page_act", {"ref": "f0:e1", "action": "explode"}, "s1", tab_id=3)
    assert e.value.status == "unsupported"
    with pytest.raises(A.AdapterError) as e:      # снимка ещё не было
        A.to_ext("page_act", {"ref": "f0:e1", "action": "click"}, None, tab_id=3)
    assert e.value.status == "stale"


def test_snapshot_substitution_only_where_ref_needs_it():
    assert A.to_ext("page_shot", {"crop_ref": "f0:e2"}, "s5", tab_id=1)[1]["snapshot_id"] == "s5"
    assert A.to_ext("page_scroll", {"direction": "down", "ref": "f0:e2"}, "s5", tab_id=1)[1] == {
        "tab_id": 1, "ref": "f0:e2", "snapshot_id": "s5"}
    assert A.to_ext("page_fill_form", {"fields": [{"ref": "f0:e1", "value": "x"}]}, "s5", tab_id=1)[1][
        "snapshot_id"] == "s5"
    assert "snapshot_id" not in A.to_ext("page_shot", {}, "s5", tab_id=1, window_id=7)[1]
    assert "snapshot_id" not in A.to_ext("page_scroll", {"direction": "top"}, "s5", tab_id=1)[1]


@pytest.mark.parametrize("direction,expected", [
    ("top", {"to": "top"}), ("bottom", {"to": "bottom"}), ("up", {"dy": -1}), ("down", {}),
])
def test_scroll_mapping(direction, expected):
    result = A.to_ext("page_scroll", {"direction": direction}, None, tab_id=4)
    assert result == ("page.scroll", {"tab_id": 4, **expected})


def test_fill_form_fields_to_values():
    fields = [{"ref": "f0:e1", "value": "Анна"}, {"ref": "f0:e2", "checked": True},
              {"ref": "f0:e3", "checked": False}, {"ref": "f0:e4", "option_ref": "f0:e5", "value": "Рим"},
              {"ref": "f0:e6", "option_ref": "f0:e7"}]
    _, ext = A.to_ext("page_fill_form", {"fields": fields, "submit_ref": "f0:e9"}, "s1", tab_id=2)
    assert ext["values"] == {"f0:e1": "Анна", "f0:e2": True, "f0:e3": False, "f0:e4": "Рим", "f0:e7": True}
    assert A.submit_followup("page_fill_form", {"fields": fields, "submit_ref": "f0:e9"}, "s2", tab_id=2) == (
        "page.act", {"tab_id": 2, "snapshot_id": "s2", "ref": "f0:e9", "op": "click"})
    assert A.submit_followup("page_fill_form", {"fields": fields}, "s2", tab_id=2) is None
    with pytest.raises(A.AdapterError):
        A.to_ext("page_fill_form", {"fields": []}, "s1", tab_id=2)


def test_fill_form_pairs_match_and_order():
    match = {"ref": "f0:e1", "kind": "match",
             "pairs": [{"row_ref": "f0:e2", "option_text": "Рим"}, {"row_ref": "f0:e3", "option_text": "Мадрид"}]}
    order = {"ref": "f0:e5", "kind": "order",
             "pairs": [{"row_ref": "f0:e6", "option_text": 2}, {"row_ref": "f0:e7", "option_text": "1"}]}
    name, ext = A.to_ext("page_fill_form", {"fields": [match, order, {"ref": "f0:e9", "value": "x"}]}, "s1", tab_id=2)
    assert name == "page.fill_form" and ext["snapshot_id"] == "s1"
    assert ext["values"] == {
        "f0:e1": {"kind": "match", "pairs": match["pairs"]},
        "f0:e5": {"kind": "order", "pairs": [{"row_ref": "f0:e6", "option_text": "2"},
                                             {"row_ref": "f0:e7", "option_text": "1"}]},
        "f0:e9": "x"}
    # без kind — расширение решает по строкам (select в строке или перестановка); чужой kind не передаётся
    _, ext = A.to_ext("page_fill_form", {"fields": [{**match, "kind": "single"}]}, "s1", tab_id=2)
    assert ext["values"]["f0:e1"] == {"pairs": match["pairs"]}


def test_fill_form_legacy_order_becomes_positions():
    _, ext = A.to_ext("page_fill_form", {"fields": [{"ref": "f0:e1", "order": ["f0:e4", "f0:e2", "f0:e3"]}]},
                      "s1", tab_id=2)
    assert ext["values"]["f0:e1"] == {"kind": "order", "pairs": [
        {"row_ref": "f0:e4", "option_text": "1"}, {"row_ref": "f0:e2", "option_text": "2"},
        {"row_ref": "f0:e3", "option_text": "3"}]}


@pytest.mark.parametrize("field", [
    {"ref": "f0:e1", "pairs": []},
    {"ref": "f0:e1", "pairs": "f0:e2=Рим"},
    {"ref": "f0:e1", "pairs": [{"row_ref": "f0:e2"}]},
    {"ref": "f0:e1", "pairs": [{"option_text": "Рим"}]},
    {"ref": "f0:e1", "pairs": [{"row_ref": "f0:e2", "option_text": ""}]},
    {"ref": "f0:e1", "order": []},
    {"ref": "f0:e1", "order": ["f0:e2", 3]},
])
def test_fill_form_bad_pairs(field):
    with pytest.raises(A.AdapterError) as e:
        A.to_ext("page_fill_form", {"fields": [field]}, "s1", tab_id=2)
    assert e.value.status == "error"


def test_pairs_reach_extension_rows_from_questions():
    """Круг: rows из page.questions → пары сервера → values расширения с теми же row_ref."""
    q = {"q_ref": "f0:e1", "index": 1, "kind": "match", "text": "?",
         "rows": [{"row_ref": "f0:e2", "text": "Италия"}], "options": [{"text": "Рим"}]}
    [sq] = A.from_ext_questions([q])
    assert sq["ref"] == "f0:e1" and sq["rows"] == q["rows"] and sq["options"] == [{"text": "Рим", "name": "Рим"}]
    field = {"ref": sq["ref"], "kind": sq["kind"],
             "pairs": [{"row_ref": sq["rows"][0]["row_ref"], "option_text": sq["options"][0]["name"]}]}
    _, ext = A.to_ext("page_fill_form", {"fields": [field]}, "s3", tab_id=2)
    assert ext["values"] == {"f0:e1": {"kind": "match", "pairs": [{"row_ref": "f0:e2", "option_text": "Рим"}]}}


def test_shot_tabs_upload():
    assert A.to_ext("page_shot", {}, None, tab_id=1, window_id=7) == ("page.shot", {"window_id": 7, "mode": "plain"})
    assert A.to_ext("tabs_new", {"url": "https://a/"}, None, window_id=7) == (
        "tabs.new", {"url": "https://a/", "active": True, "window_id": 7})
    assert A.to_ext("tabs_list", {}, None, window_id=7) == ("tabs.list", {"window_id": 7})
    assert A.to_ext("page_upload", {"ref": "f0:e1", "file": "a.pdf"}, "s1", tab_id=1,
                    issue_file=lambda n: "T") == ("page.upload", {"tab_id": 1, "ref": "f0:e1", "file_token": "T",
                                                                  "snapshot_id": "s1"})
    with pytest.raises(A.AdapterError) as e:
        A.to_ext("page_upload", {"ref": "f0:e1", "file": "a.pdf"}, "s1", tab_id=1)
    assert e.value.status == "unsupported"


def test_questions_to_server_form():
    qs = [{"q_ref": "f0:e1", "index": 1, "kind": "single", "text": "?",
           "options": [{"ref": "f0:e2", "text": "Круг", "checked": False}]},
          {"q_ref": "f0:e3", "index": 2, "kind": "text", "input_ref": "f0:e4", "options": []},
          {"q_ref": "f0:e5", "index": 3, "kind": "single", "input_ref": "f0:e6",
           "options": [{"ref": "f0:e7", "text": "Рим", "checked": False}]}]
    out = A.from_ext_questions(qs)
    assert [q["ref"] for q in out] == ["f0:e1", "f0:e4", "f0:e6"]
    assert out[0]["options"][0]["name"] == "Круг"
    assert [q["kind"] for q in out] == ["single", "text", "select"]
    assert out[0]["q_ref"] == "f0:e1"       # поля расширения сохраняются
