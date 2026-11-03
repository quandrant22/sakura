"""desktop.core.browser_adapter — инструменты сервера → действия расширения 3.2.0.

Источник истины для того, что приходит в action, — схема инструментов сервера
(sakura_core/browser_step.py ветки server/browser-step; её выгрузка sakura.browser_tools/1 —
desktop/tests/fixtures/server_tools.json, обновляет desktop/scripts/sync_server_tools.*).
Расширение свои op не меняет: весь перевод аргументов — здесь, BrowserAgent._do только вызывает to_ext.

  page_act        action → op: type → fill, clear → fill "", submit → click, остальные как есть;
                  text → value (type/select), key → value (press)
  page_fill_form  fields [{ref, value | checked | option_ref}] → values {ref: value | checked};
                  fields [{ref, pairs: [{row_ref, option_text}], kind?}] (match/order) и прежняя
                  [{ref, order: [row_ref…]}] → values {ref: {pairs, kind?}};
                  submit_ref — отдельный page.act click после успешного заполнения (submit_followup)
  page_scroll     direction top|bottom → to; up → dy −1 (экран вверх); down → без dy; ref → к элементу
  page_shot       crop_ref → вырезка по ref (вкладка); без него — кадр окна агента
snapshot_id подставляется из последнего observation (page_act, page_fill_form, page_shot c crop_ref,
page_scroll c ref). Обратно: вопросы page_questions — в форму решателя сервера (from_ext_questions).
"""
from __future__ import annotations

from collections.abc import Callable

# Действия расширения и их обязательные аргументы (desktop/extension/lib/agent.js).
EXT_REQUIRED = {
    "tabs.list": (),
    "tabs.activate": ("tab_id",),
    "tabs.new": ("url",),
    "tabs.close": ("tab_id",),
    "page.observe": ("tab_id",),
    "page.act": ("tab_id", "snapshot_id", "ref", "op"),
    "page.shot": (),                    # tab_id или window_id — проверяет shot_target
    "page.forms": ("tab_id",),
    "page.questions": ("tab_id",),
    "page.fill_form": ("tab_id", "snapshot_id", "values"),
    "page.upload": ("tab_id", "ref", "file_token"),
    "page.scroll": ("tab_id",),
}
# action сервера → op расширения (content.js act).
ACT_OPS = {
    "click": "click", "type": "fill", "clear": "fill", "submit": "click", "select": "select",
    "check": "check", "uncheck": "uncheck", "press": "press", "focus": "focus", "hover": "hover",
}
SCROLL_UP = -1        # маркер «экран вверх»: content.js листает на 0.8 высоты окна
PAIR_KINDS = ("match", "order")


class AdapterError(ValueError):
    """Аргументы сервера нельзя выполнить в расширении — результат шага unsupported/error."""

    def __init__(self, message: str, status: str = "unsupported"):
        super().__init__(message)
        self.status = status


def _need(args: dict, *names: str) -> None:
    missing = [n for n in names if args.get(n) in (None, "")]
    if missing:
        raise AdapterError(f"нет аргумента: {', '.join(missing)}", "error")


def _snapshot(snapshot_id: str | None) -> str:
    if not snapshot_id:
        raise AdapterError("нет снимка страницы — нужен page_observe", "stale")
    return snapshot_id


def _pairs_value(f: dict) -> dict:
    """match/order: pairs [{row_ref, option_text}] → {pairs, kind?}; прежняя форма order [row_ref…] —
    пары с позициями 1…n (option_text порядка — позиция строки)."""
    if "pairs" in f:
        raw = f["pairs"]
        if not isinstance(raw, list) or not raw:
            raise AdapterError(f"поле {f['ref']}: pairs — непустой список", "error")
        pairs = []
        for p in raw:
            if not isinstance(p, dict) or not p.get("row_ref") or p.get("option_text") in (None, ""):
                raise AdapterError(f"поле {f['ref']}: пара без row_ref или option_text", "error")
            pairs.append({"row_ref": p["row_ref"], "option_text": str(p["option_text"])})
        kind = f.get("kind")
    else:
        order = f["order"]
        if not isinstance(order, list) or not order or not all(isinstance(r, str) and r for r in order):
            raise AdapterError(f"поле {f['ref']}: order — непустой список ref", "error")
        pairs = [{"row_ref": r, "option_text": str(i)} for i, r in enumerate(order, 1)]
        kind = "order"
    out: dict = {"pairs": pairs}
    if kind in PAIR_KINDS:
        out["kind"] = kind
    return out


def _fill_values(fields) -> dict:
    if not isinstance(fields, list) or not fields:
        raise AdapterError("fields — непустой список", "error")
    values: dict = {}
    for f in fields:
        if not isinstance(f, dict) or not f.get("ref"):
            raise AdapterError("поле без ref", "error")
        if "pairs" in f or "order" in f:
            values[f["ref"]] = _pairs_value(f)
        elif isinstance(f.get("checked"), bool):
            values[f["ref"]] = f["checked"]
        elif f.get("value") is not None:
            values[f["ref"]] = f["value"]          # select — по тексту варианта (option_ref — подсказка сервера)
        elif f.get("option_ref"):
            values[f["option_ref"]] = True
        else:
            raise AdapterError(f"поле {f['ref']}: нет value или checked", "error")
    return values


def to_ext(tool: str, args: dict | None, snapshot_id: str | None, *, tab_id=None, window_id=None,
           issue_file: Callable[[str], str] | None = None) -> tuple[str, dict]:
    """(tool, args сервера) → (действие расширения, его аргументы). Иначе AdapterError."""
    a = dict(args or {})
    if tool == "tabs_list":
        return "tabs.list", ({"window_id": window_id} if window_id is not None else {})
    if tool == "tabs_activate":
        _need(a, "tab_id")
        return "tabs.activate", {"tab_id": a["tab_id"]}
    if tool == "tabs_new":
        _need(a, "url")
        out = {"url": a["url"], "active": True}
        if window_id is not None:
            out["window_id"] = window_id
        return "tabs.new", out
    if tool == "tabs_close":
        return "tabs.close", {"tab_id": a.get("tab_id", tab_id)}
    if tool in ("page_observe", "page_forms", "page_questions"):
        return "page." + tool[5:], {"tab_id": tab_id}
    if tool == "page_act":
        _need(a, "ref", "action")
        op = ACT_OPS.get(a["action"])
        if op is None:
            raise AdapterError(f"неизвестное действие: {str(a['action'])[:40]}")
        out = {"tab_id": tab_id, "snapshot_id": _snapshot(snapshot_id), "ref": a["ref"], "op": op}
        if a["action"] == "clear":
            out["value"] = ""
        elif a["action"] in ("type", "select"):
            _need(a, "text")
            out["value"] = a["text"]
        elif a["action"] == "press":
            out["value"] = a.get("key") or "Enter"
        return "page.act", out
    if tool == "page_fill_form":
        return "page.fill_form", {"tab_id": tab_id, "snapshot_id": _snapshot(snapshot_id),
                                  "values": _fill_values(a.get("fields"))}
    if tool == "page_shot":
        if a.get("crop_ref"):
            return "page.shot", {"tab_id": tab_id, "crop_ref": a["crop_ref"], "snapshot_id": _snapshot(snapshot_id)}
        if window_id is not None:
            return "page.shot", {"window_id": window_id, "mode": "plain"}
        return "page.shot", {"tab_id": tab_id, "mode": "plain"}
    if tool == "page_scroll":
        out = {"tab_id": tab_id}
        if a.get("ref"):
            out.update(ref=a["ref"], snapshot_id=_snapshot(snapshot_id))
            return "page.scroll", out
        direction = a.get("direction") or "down"
        if direction in ("top", "bottom"):
            out["to"] = direction
        elif direction == "up":
            out["dy"] = SCROLL_UP
        elif direction != "down":
            raise AdapterError(f"неизвестное направление: {str(direction)[:20]}", "error")
        return "page.scroll", out
    if tool == "page_upload":
        _need(a, "ref", "file")
        if issue_file is None:
            raise AdapterError("загрузка файлов не настроена (BROWSER_UPLOAD_DIR)")
        out = {"tab_id": tab_id, "ref": a["ref"], "file_token": issue_file(a["file"])}
        if snapshot_id:
            out["snapshot_id"] = snapshot_id
        return "page.upload", out
    raise AdapterError(f"неизвестный tool: {str(tool)[:40]}")


def submit_followup(tool: str, args: dict | None, snapshot_id: str | None, *, tab_id=None) -> tuple[str, dict] | None:
    """page_fill_form с submit_ref → page.act click по кнопке (в снимке после заполнения)."""
    if tool != "page_fill_form" or not (args or {}).get("submit_ref"):
        return None
    return "page.act", {"tab_id": tab_id, "snapshot_id": _snapshot(snapshot_id),
                        "ref": args["submit_ref"], "op": "click"}


def shot_target(ext_args: dict) -> bool:
    return ext_args.get("tab_id") is not None or ext_args.get("window_id") is not None


def from_ext_questions(questions: list) -> list[dict]:
    """Вопросы расширения → форма решателя сервера: ref — поле ответа (input_ref) или блок вопроса;
    у вариантов — name; один вариант из списка select — kind select."""
    out = []
    for q in questions or []:
        if not isinstance(q, dict):
            continue
        item = dict(q)
        item["ref"] = q.get("input_ref") or q.get("q_ref")
        item["options"] = [{**o, "name": o.get("text", "")} for o in q.get("options") or [] if isinstance(o, dict)]
        if q.get("kind") == "single" and q.get("input_ref"):
            item["kind"] = "select"
        out.append(item)
    return out
