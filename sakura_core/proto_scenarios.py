"""Протокол v2, порция 4: сценарии (движок — sakura_core/scenarios.py).

  scenarios_list                 → scenarios {scenarios}
  scenario_get {id}              → scenario {scenario}
  scenario_save {scenario}       → scenario {scenario}     (без id — создать)
  scenario_delete {id}           → scenarios {scenarios}
  scenario_run {id, confirm?}    → scenario_run_started {run_id, id}, пуши scenario_event
  scenario_from_text {text}      → scenario_preview {scenario, warnings}  (не сохраняется)

Опасные действия (confirm в реестре) — запуск только с confirm: true,
иначе error/confirm_required со списком действий.
"""

from __future__ import annotations

import asyncio
import json
import logging

from sakura_core import proto_v2, scenarios
from sakura_core.proto_v2 import V2Error
from sakura_core.tasks import spawn

log = logging.getLogger("sakura.scenarios")


def _err(e: scenarios.ScenarioError) -> V2Error:
    return V2Error(e.code, e.message)


def _id(data) -> str:
    sid = data.get("id")
    if not isinstance(sid, str) or not sid:
        raise V2Error("bad_request", "id: нужен id сценария")
    return sid


async def _list(ws, data, ctx):
    return {"type": "scenarios", "scenarios": await asyncio.to_thread(scenarios.list_all)}


async def _get(ws, data, ctx):
    s = await asyncio.to_thread(scenarios.get, _id(data))
    if s is None:
        raise V2Error("not_found", "сценарий не найден")
    return {"type": "scenario", "scenario": s}


async def _save(ws, data, ctx):
    try:
        s = await asyncio.to_thread(scenarios.save, data.get("scenario"))
    except scenarios.ScenarioError as e:
        raise _err(e) from None
    return {"type": "scenario", "scenario": s}


async def _delete(ws, data, ctx):
    try:
        ok = await asyncio.to_thread(scenarios.delete, _id(data))
    except scenarios.ScenarioError as e:
        raise _err(e) from None
    if not ok:
        raise V2Error("not_found", "сценарий не найден")
    return {"type": "scenarios", "scenarios": await asyncio.to_thread(scenarios.list_all)}


async def _run(ws, data, ctx):
    s = await asyncio.to_thread(scenarios.get, _id(data))
    if s is None:
        raise V2Error("not_found", "сценарий не найден")
    danger = scenarios.dangerous_actions(s)
    confirmed = data.get("confirm") is True
    if danger and not confirmed:
        raise V2Error("confirm_required",
                      f"опасные действия: {', '.join(danger)} — запуск с confirm: true")
    run_id = f"r{__import__('secrets').token_hex(4)}"

    async def emit(event):
        try:
            await ws.send(json.dumps(event, ensure_ascii=False))
        except Exception as e:
            log.debug(f"[scenario] событие не отправлено: {type(e).__name__}")

    await ws.send(json.dumps({"type": "scenario_run_started", "request_id": data.get("request_id"),
                              "run_id": run_id, "id": s["id"]}, ensure_ascii=False))
    import modules.state as st
    device_id = data.get("device_id")
    spawn(scenarios.run(s, emit=emit, device_ws=st.connected_devices.get(device_id) or ws,
                        device_id=device_id, register_command=ctx.get("_register_command"),
                        confirmed=confirmed, run_id=run_id),
          name=f"scenario-{s['id']}")
    return None


async def _from_text(ws, data, ctx):
    try:
        scenario, warnings = await asyncio.to_thread(scenarios.from_text, data.get("text") or "")
    except scenarios.ScenarioError as e:
        raise _err(e) from None
    return {"type": "scenario_preview", "scenario": scenario, "warnings": warnings}


for _k, _f in {"scenarios_list": _list, "scenario_get": _get, "scenario_save": _save,
               "scenario_delete": _delete, "scenario_run": _run,
               "scenario_from_text": _from_text}.items():
    proto_v2.register(_k, _f)
