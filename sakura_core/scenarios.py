"""Сценарии v1: хранение, проверка, исполнение (протокол v2 scenarios_*).

Сценарий: {"id", "name", "enabled", "builtin", "conditions": [{"type",
"value"}], "actions": [{"type", "value"}]} (desktop/tools/fixtures).

  * действия: action (id реестра), pause (секунды ≤ 60), telegram (текст
    Мастеру), notify (reply kind=proactive всем master-устройствам);
  * не больше 20 шагов; action — только из реестра с обработчиком;
  * действие с confirm (опасное) — запуск только с confirm: true; без
    него — ошибка со списком таких действий;
  * условия v1: phrase (голосовая фраза запускает сценарий без опасных
    действий); time / device_connected / device_disconnected /
    app_started — хранятся, автозапуска в v1 нет (docs/DECISIONS.md).
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import re
import secrets
import tempfile
import threading

import config

log = logging.getLogger("sakura.scenarios")

MAX_STEPS = 20
PAUSE_MAX_S = 60.0
NAME_MAX = 60
COND_TYPES = ("phrase", "time", "device_connected", "device_disconnected", "app_started")
ACTION_TYPES = ("action", "pause", "telegram", "notify")
_TIME = re.compile(r"^([01]\d|2[0-3]):[0-5]\d(-([01]\d|2[0-3]):[0-5]\d)?$")
_lock = threading.Lock()


class ScenarioError(ValueError):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code
        self.message = message


def _path() -> str:
    return getattr(config, "SCENARIOS_PATH", "memory/scenarios.json")


def _load() -> list[dict]:
    try:
        with open(_path(), encoding="utf-8") as f:
            return list(json.load(f).get("scenarios") or [])
    except (FileNotFoundError, ValueError):
        return []


def _save(items: list[dict]) -> None:
    d = os.path.dirname(os.path.abspath(_path()))
    os.makedirs(d, exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix=".scenarios-", dir=d)
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        json.dump({"scenarios": items}, f, ensure_ascii=False, indent=1)
    os.chmod(tmp, 0o600)
    os.replace(tmp, _path())


def _declarations() -> dict:
    from sakura_core.bridge import _declarations as decls
    return {d.id: d for d in decls}


def _norm(text: str) -> str:
    t = (text or "").lower().replace("ё", "е")
    return " ".join(re.findall(r"[a-zа-я0-9]+", t))


# ── проверка ──────────────────────────────────────────────────────

def validate(s: dict) -> dict:
    if not isinstance(s, dict):
        raise ScenarioError("bad_request", "сценарий — объект")
    name = s.get("name")
    if not isinstance(name, str) or not name.strip() or len(name) > NAME_MAX:
        raise ScenarioError("bad_request", f"name: 1–{NAME_MAX} символов")
    conds = s.get("conditions") or []
    acts = s.get("actions") or []
    if not isinstance(conds, list) or not isinstance(acts, list):
        raise ScenarioError("bad_request", "conditions/actions — списки")
    if not acts:
        raise ScenarioError("bad_request", "нет действий")
    if len(acts) > MAX_STEPS:
        raise ScenarioError("bad_request", f"больше {MAX_STEPS} шагов")
    decls = _declarations()
    from sakura_core.executor import get_handler
    for c in conds:
        if not isinstance(c, dict) or c.get("type") not in COND_TYPES:
            raise ScenarioError("bad_request", f"условие: тип из {COND_TYPES}")
        v = str(c.get("value") or "")
        if c["type"] == "time" and not _TIME.match(v):
            raise ScenarioError("bad_request", "time: ЧЧ:ММ или ЧЧ:ММ-ЧЧ:ММ")
        if c["type"] == "phrase" and not _norm(v):
            raise ScenarioError("bad_request", "phrase: пустая фраза")
    for i, a in enumerate(acts):
        if not isinstance(a, dict) or a.get("type") not in ACTION_TYPES:
            raise ScenarioError("bad_request", f"шаг {i + 1}: тип из {ACTION_TYPES}")
        v = a.get("value")
        if a["type"] == "action":
            if v not in decls or get_handler(v) is None:
                raise ScenarioError("bad_request", f"шаг {i + 1}: неизвестное действие {v!r}")
        elif a["type"] == "pause":
            try:
                p = float(v)
            except (TypeError, ValueError):
                raise ScenarioError("bad_request", f"шаг {i + 1}: пауза — число секунд") from None
            if not 0 <= p <= PAUSE_MAX_S:
                raise ScenarioError("bad_request", f"шаг {i + 1}: пауза 0–{PAUSE_MAX_S:.0f} с")
        elif not isinstance(v, str) or not v.strip() or len(v) > 500:
            raise ScenarioError("bad_request", f"шаг {i + 1}: текст 1–500 символов")
    return {"id": s.get("id"), "name": name.strip(), "enabled": bool(s.get("enabled", True)),
            "builtin": bool(s.get("builtin", False)),
            "conditions": [{"type": c["type"], "value": str(c.get("value") or "")} for c in conds],
            "actions": [{"type": a["type"], "value": str(a.get("value"))} for a in acts]}


def dangerous_actions(s: dict) -> list[str]:
    decls = _declarations()
    return [a["value"] for a in s.get("actions", [])
            if a["type"] == "action" and decls.get(a["value"]) and decls[a["value"]].confirm]


# ── хранилище ─────────────────────────────────────────────────────

def list_all() -> list[dict]:
    with _lock:
        return _load()


def get(sid: str) -> dict | None:
    return next((s for s in list_all() if s.get("id") == sid), None)


def save(s: dict) -> dict:
    clean = validate(s)
    with _lock:
        items = _load()
        old = next((x for x in items if x.get("id") == clean["id"]), None) if clean["id"] else None
        if old is None:
            clean["id"] = clean["id"] or f"s{secrets.token_hex(4)}"
            if any(x.get("id") == clean["id"] for x in items):
                raise ScenarioError("bad_request", "id занят")
            items.append(clean)
        else:
            if old.get("builtin"):
                clean["builtin"] = True
            old.clear()
            old.update(clean)
            clean = old
        _save(items)
    return dict(clean)


def delete(sid: str) -> bool:
    with _lock:
        items = _load()
        s = next((x for x in items if x.get("id") == sid), None)
        if s is None:
            return False
        if s.get("builtin"):
            raise ScenarioError("bad_request", "встроенный сценарий не удаляется (можно выключить)")
        items.remove(s)
        _save(items)
        return True


def match_phrase(text: str) -> dict | None:
    """Включённый сценарий, у которого фраза-условие совпала с текстом."""
    t = _norm(text)
    if not t:
        return None
    for s in list_all():
        if s.get("enabled") and any(c["type"] == "phrase" and _norm(c["value"]) == t
                                    for c in s.get("conditions", [])):
            return s
    return None


# ── из текста (без LLM) ───────────────────────────────────────────

_SPLIT = re.compile(r"\s*(?:,|;|\bи потом\b|\bпотом\b|\bзатем\b|\bа ещё\b|\bи\b)\s*")


def from_text(text: str) -> tuple[dict, list[str]]:
    """Черновик сценария из фразы: части → действия реестра. Не сохраняется."""
    from sakura_core.bridge import get_router
    text = (text or "").strip()
    if not text:
        raise ScenarioError("bad_request", "пустая фраза")
    index = get_router()._index
    actions, warnings = [], []
    for part in [p for p in _SPLIT.split(text) if p and p.strip()][:MAX_STEPS]:
        m = re.search(r"(?:подожди|пауза)\s+(\d+)", part)
        if m:
            actions.append({"type": "pause", "value": str(min(int(m.group(1)), int(PAUSE_MAX_S)))})
            continue
        hit = index.match(part, None)
        if hit is None:
            warnings.append(f"не понято: «{part}»")
            continue
        actions.append({"type": "action", "value": hit[1].id})
    if not actions:
        warnings.append("ни одного действия не распознано")
    name = text[:40]
    return ({"id": None, "name": name, "enabled": True, "builtin": False,
             "conditions": [{"type": "phrase", "value": name}], "actions": actions}, warnings)


# ── исполнение ────────────────────────────────────────────────────

async def run(s: dict, *, emit, device_ws, device_id: str, register_command,
              confirmed: bool = False, run_id: str | None = None) -> str:
    """Шаги по очереди; emit(event) — пуш scenario_event. Ошибка шага —
    остановка. Возвращает run_id."""
    from sakura_core.executor import ExecutionContext
    from sakura_core.bridge import get_executor
    run_id = run_id or f"r{secrets.token_hex(4)}"
    ex = get_executor()
    for i, a in enumerate(s["actions"][:MAX_STEPS]):
        status, detail = "ok", a["type"]
        try:
            if a["type"] == "action":
                ctx = ExecutionContext(device_ws=device_ws, device_id=device_id,
                                       register_command=register_command,
                                       extra={"confirmed": confirmed, "source": device_id,
                                              "text": f"сценарий {s['name']}"})
                result = await ex.execute(a["value"], ctx)
                detail = a["value"]
                if isinstance(result, tuple) and len(result) == 2:
                    detail = str(result[0])[:200]
                    if result[1] is False:
                        status = "error"
            elif a["type"] == "pause":
                await asyncio.sleep(min(float(a["value"]), PAUSE_MAX_S))
                detail = f"пауза {a['value']} с"
            elif a["type"] == "telegram":
                from adapters.telegram import send_to_master
                await send_to_master(a["value"])
                detail = "telegram"
            else:
                from sakura_core.voice_turns import broadcast_reply
                await broadcast_reply(a["value"], "proactive")
                detail = "notify"
        except Exception as e:
            status, detail = "error", f"{type(e).__name__}: {str(e)[:120]}"
        await emit({"type": "scenario_event", "run_id": run_id, "step": i,
                    "status": status, "detail": detail})
        if status == "error":
            log.info(f"[scenario] {s['id']} run={run_id}: остановлен на шаге {i + 1}")
            await emit({"type": "scenario_event", "run_id": run_id, "step": i + 1,
                        "status": "done", "detail": f"остановлено на шаге {i + 1}"})
            return run_id
    await emit({"type": "scenario_event", "run_id": run_id, "step": len(s["actions"]),
                "status": "done", "detail": ""})
    log.info(f"[scenario] {s['id']} run={run_id}: выполнен ({len(s['actions'])} шагов)")
    return run_id
