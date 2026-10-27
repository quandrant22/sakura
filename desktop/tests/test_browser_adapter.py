"""browser_adapter: инструменты сервера (схема — источник истины) → действия расширения 3.2.0.

Контракт: для каждого tool и каждого значения enum из fixtures/server_tools.json to_ext даёт
действие, которое есть в расширении (lib/agent.js), op — из content.js act, а все обязательные
аргументы действия расширения заполнены."""
import itertools
import json
import re
from pathlib import Path

import pytest

from desktop.core import browser_adapter as A

HERE = Path(__file__).resolve().parent
SCHEMA = json.loads((HERE / "fixtures" / "server_tools.json").read_text(encoding="utf-8"))["tools"]
EXT = HERE.parent / "extension"
AGENT_JS = (EXT / "lib" / "agent.js").read_text(encoding="utf-8")
CONTENT_JS = (EXT / "content.js").read_text(encoding="utf-8")

EXT_ACTIONS = set(re.findall(r'"((?:tabs|page|agent_window)\.[a-z_]+)"',
                             AGENT_JS[AGENT_JS.index("const ACTIONS"):AGENT_JS.index("]);")]))
_act = CONTENT_JS[CONTENT_JS.index("async function act(a)"):CONTENT_JS.index("// ── page.scroll")]
CONTENT_OPS = set(re.findall(r'case "([a-z_]+)":', _act))

SAMPLE = {"tab_id": 12, "url": "https://example.org/", "ref": "f0:e3", "text": "Анна", "key": "Enter",
          "crop_ref": "f0:e7", "q_index": 2, "file": "cv.pdf", "submit_ref": "f0:e9",
          "fields": [{"ref": "f0:e3", "value": "Анна"}, {"ref": "f0:e4", "checked": True}]}
CTX = {"tab_id": 11, "window_id": 7, "issue_file": lambda name: "tok-" + name}


def _cases():
    for tool, spec in SCHEMA.items():
        if tool in ("done", "fail"):
            continue
        enums = {k: v["enum"] for k, v in spec["args"].items() if "enum" in v}
        names = list(enums)
        for combo in itertools.product(*[enums[n] for n in names]) or [()]:
            args = {k: SAMPLE[k] for k in spec["args"] if k not in enums}
            args.update(dict(zip(names, combo, strict=True)))
            yield pytest.param(tool, args, id=f"{tool}-{'-'.join(combo) or 'all'}")
        # только обязательные аргументы (без enum-кортежей — их покрывает полный набор)
        if not enums:
            yield pytest.param(tool, {k: SAMPLE[k] for k in spec["required"]}, id=f"{tool}-required")


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
    assert set(SCHEMA["page_act"]["args"]["action"]["enum"]) == set(A.ACT_OPS)
    assert set(SCHEMA["page_scroll"]["args"]["direction"]["enum"]) == {"up", "down", "top", "bottom"}
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
        A.to_ext("page_fill_form", {"fields": [{"ref": "f0:e1", "order": ["f0:e2"]}]}, "s1", tab_id=2)
    with pytest.raises(A.AdapterError):
        A.to_ext("page_fill_form", {"fields": []}, "s1", tab_id=2)


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
