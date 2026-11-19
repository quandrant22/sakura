"""Автозапуск сценариев по условиям (фразу обрабатывает adapters/ws._maybe_run_scenario).

  * time — раз в минуту: «ЧЧ:ММ» (у диапазона — начало) в дни из days;
  * device_connected — устройство появилось после отсутствия ≥ OFFLINE_S
    (короткие переподключения и подключения в первые GRACE_S после старта
    сервера не считаются — иначе каждый рестарт запускал бы сценарии);
  * device_disconnected — устройство пропало и не вернулось за OFFLINE_S;
  * app_started — в названии активного окна (ping агента) или начатой игры
    появилось значение условия; первый замер после старта только запоминается,
    повтор того же сценария — не чаще APP_COOLDOWN_S.

Опасные сценарии и сценарии без нужного устройства не запускаются: итог
«skipped» с причиной пишется в карточку и уходит пушем scenario_event.
"""

from __future__ import annotations

import asyncio
import datetime as dt
import logging
import secrets
import time

import modules.state as st
from sakura_core import scenarios
from sakura_core.tasks import spawn

log = logging.getLogger("sakura.scenarios")

GRACE_S = 90.0
OFFLINE_S = 60.0
APP_COOLDOWN_S = 300.0
TICK_S = 20.0

_started = time.monotonic()
_fired_minutes: set[tuple[str, str]] = set()
_last_disconnect: dict[str, float] = {}
_offline_tasks: dict[str, asyncio.Task] = {}
_app_seen: dict[tuple[str, str], bool] = {}
_app_last_fire: dict[str, float] = {}

TRIGGER_TITLES = {
    "time": "по времени", "device_connected": "устройство подключилось",
    "device_disconnected": "устройство отключилось", "app_started": "открыто приложение",
    "telegram": "из Telegram",
}


def reset(now: float | None = None) -> None:
    """Для тестов и старта: забыть состояние, отсчитать GRACE_S заново."""
    global _started
    _started = time.monotonic() if now is None else now
    _fired_minutes.clear()
    _last_disconnect.clear()
    for t in _offline_tasks.values():
        t.cancel()
    _offline_tasks.clear()
    _app_seen.clear()
    _app_last_fire.clear()


def _enabled_with(ctype: str) -> list[tuple[dict, dict]]:
    out = []
    for s in scenarios.list_all():
        if not s.get("enabled", True):
            continue
        for c in s.get("conditions", []):
            if c.get("type") == ctype:
                out.append((s, c))
    return out


def _pick_device(preferred: str | None) -> tuple[str | None, object | None]:
    if preferred and preferred in st.connected_devices:
        return preferred, st.connected_devices[preferred]
    from sakura_core import proto_devices, proto_v2
    focus = proto_devices._focused()
    if focus and focus in st.connected_devices:
        return focus, st.connected_devices[focus]
    for dev, ws in list(st.connected_devices.items()):
        if proto_v2._is_master(dev):
            return dev, ws
    return None, None


async def _broadcast(event: dict) -> None:
    from sakura_core import proto_v2
    await proto_v2.broadcast(event)


async def fire(s: dict, trigger: str, device_id: str | None = None, *, confirmed: bool = False) -> str | None:
    """Запустить сценарий по условию (или из Telegram: confirmed — Мастер нажал «Да»).
    Возвращает run_id или None (пропущен)."""
    sid = s["id"]
    if sid in scenarios.running:
        log.info(f"[scenario] {sid}: уже выполняется — {trigger} пропущен")
        return None
    reason = TRIGGER_TITLES.get(trigger, trigger)
    run_id = f"r{secrets.token_hex(4)}"
    skip = None
    if scenarios.dangerous_actions(s) and not confirmed:
        skip = "опасные действия — только кнопкой ▶"
    dev, ws = await asyncio.to_thread(_pick_device, device_id)
    if skip is None and ws is None and scenarios.needs_device(s):
        skip = "нет устройства онлайн"
    await _broadcast({"type": "scenario_run_started", "run_id": run_id, "id": sid,
                      "name": s.get("name", ""), "trigger": reason})
    if skip:
        log.info(f"[scenario] {sid} ({reason}): пропущен — {skip}")
        await asyncio.to_thread(scenarios.note_run, sid, "skipped", skip)
        await _broadcast({"type": "scenario_event", "run_id": run_id, "id": sid, "step": 0,
                          "status": "done", "detail": f"пропущен: {skip}"})
        return None
    from adapters.ws import _register_command
    log.info(f"[scenario] {sid}: автозапуск ({reason}) на {dev}")
    scenarios.running.add(sid)
    spawn(scenarios.run(s, emit=_broadcast, device_ws=ws, device_id=dev or "",
                        register_command=_register_command, confirmed=confirmed,
                        run_id=run_id, trigger=trigger),
          name=f"scenario-auto-{sid}")
    return run_id


# ── время ─────────────────────────────────────────────────────────

def due(cond: dict, now: dt.datetime) -> bool:
    start = str(cond.get("value") or "").split("-")[0]
    try:
        h, m = (int(x) for x in start.split(":"))
    except ValueError:
        return False
    days = cond.get("days")
    if days and now.weekday() not in days:
        return False
    return now.hour == h and now.minute == m


async def check_time(now: dt.datetime | None = None) -> list[str]:
    now = now or dt.datetime.now()
    stamp = now.strftime("%Y-%m-%d %H:%M")
    fired = []
    for s, c in await asyncio.to_thread(_enabled_with, "time"):
        key = (s["id"], stamp)
        if key in _fired_minutes or not due(c, now):
            continue
        _fired_minutes.add(key)
        fired.append(s["id"])
        await fire(s, "time")
    # старые отметки (не текущая минута) больше не нужны
    for k in [k for k in _fired_minutes if k[1] != stamp]:
        _fired_minutes.discard(k)
    return fired


async def time_loop() -> None:
    while True:
        try:
            await check_time()
        except Exception as e:
            log.warning(f"[scenario] таймер: {type(e).__name__}: {e}")
        await asyncio.sleep(TICK_S)


# ── устройства ────────────────────────────────────────────────────

def _matches_device(cond: dict, device_id: str) -> bool:
    v = str(cond.get("value") or "").strip()
    return not v or v == device_id


async def on_device_connected(device_id: str | None, was_online: bool) -> None:
    if not device_id or was_online:
        return
    now = time.monotonic()
    task = _offline_tasks.pop(device_id, None)
    if task is not None and not task.done():
        task.cancel()          # вернулось быстрее OFFLINE_S — это переподключение
        return
    if now - _started < GRACE_S:
        return
    last = _last_disconnect.get(device_id)
    if last is not None and now - last < OFFLINE_S:
        return
    for s, c in await asyncio.to_thread(_enabled_with, "device_connected"):
        if _matches_device(c, device_id):
            await fire(s, "device_connected", device_id)


async def _offline_after(device_id: str) -> None:
    await asyncio.sleep(OFFLINE_S)
    _offline_tasks.pop(device_id, None)
    if device_id in st.connected_devices:
        return
    for s, c in await asyncio.to_thread(_enabled_with, "device_disconnected"):
        if _matches_device(c, device_id):
            await fire(s, "device_disconnected", None)


async def on_device_disconnected(device_id: str | None) -> None:
    if not device_id:
        return
    _last_disconnect[device_id] = time.monotonic()
    old = _offline_tasks.pop(device_id, None)
    if old is not None and not old.done():
        old.cancel()
    _offline_tasks[device_id] = spawn(_offline_after(device_id), name=f"scenario-offline-{device_id}")


# ── приложения ────────────────────────────────────────────────────

async def on_window(device_id: str | None, title: str | None, *, game: bool = False) -> list[str]:
    """Активное окно (ping) или начатая игра (game=True) — проверка app_started."""
    if not device_id:
        return []
    text = scenarios._norm(title or "")
    now = time.monotonic()
    fired = []
    for s, c in await asyncio.to_thread(_enabled_with, "app_started"):
        want = scenarios._norm(c.get("value", ""))
        if not want:
            continue
        hit = bool(text) and want in text
        key = (s["id"], device_id)
        prev = _app_seen.get(key)
        if not game:
            _app_seen[key] = hit
        rising = hit and (game or prev is False)
        if not rising:
            continue
        if now - _app_last_fire.get(s["id"], -APP_COOLDOWN_S) < APP_COOLDOWN_S:
            continue
        _app_last_fire[s["id"]] = now
        fired.append(s["id"])
        await fire(s, "app_started", device_id)
    return fired
