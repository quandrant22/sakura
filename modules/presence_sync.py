"""
modules/presence_sync.py — Бесшовное присутствие (бэклоги №29, №30).

№29: Присутствие следует за тобой — сел за другой ПК →
     орб «переехал» (передача фокуса между устройствами).

№30: Бесшовный перенос разговора — начал на ноуте, продолжил
     на ПК без потери контекста (память централизована — почти бесплатно).

Логика (одно активное устройство — get_active_device):
  - голос или текст с устройства (note_input) → оно активное сразу;
  - иначе активно то, где был последний ввод: ping несёт input_idle_s —
    секунд с последнего ввода на этом ПК;
  - переключаем только если на новом ввод был ≤ SWITCH_NEW_IDLE_S назад,
    а на текущем ≥ SWITCH_CUR_IDLE_S назад (три ПК с пингами без ввода
    активное не меняют);
  - input_idle_s не пришло — прежняя оценка по input_score (ниже).
  - О смене активного клиенты узнают через check_device_transfer +
    broadcast_transfer: proto 2 — событие presence, proto 1 — mood_update
    только с is_arrival/is_departure.

Хранение: таблица device_presence в sakura.db.
"""

import json
import logging
import threading
import time
from datetime import datetime, timedelta
from typing import Optional

log = logging.getLogger("sakura.presence_sync")

# Устройство считается живым, если ping/ввод был не далее ACTIVE_WINDOW секунд назад
ACTIVE_WINDOW_SEC  = 120
# Переключение по input_idle_s: на новом ввод ≤ NEW, на текущем ≥ CUR секунд назад
SWITCH_NEW_IDLE_S  = 5.0
SWITCH_CUR_IDLE_S  = 30.0
# Сообщения, после которых устройство активно сразу (голос или текст)
INPUT_TYPES = frozenset({"voice_command", "chat_send"})

_lock = threading.RLock()
_announced:   str = ""       # кого последним объявили клиентам (check_device_transfer)
_active:      str = ""       # решение: текущее активное устройство
# device_id → {"seen": monotonic последнего ping/ввода, "input_at": monotonic
# последнего ввода или None, если клиент input_idle_s не присылает}
_devs: dict[str, dict] = {}
# Отключения ПК: device_id → {"wall": time.time(), "reason": shutdown|sleep|exit|None}
_offline: dict[str, dict] = {}
_bye: dict[str, str] = {}    # device_id → причина: клиент прислал bye, сокет мог ещё жить
BYE_REASONS = ("shutdown", "sleep", "exit")
# Нет ввода столько секунд (при онлайн-ПК) — Мастер отошёл
AWAY_AFTER_S = 600.0


def _now() -> float:
    return time.monotonic()


def _wall() -> float:
    return time.time()


def reset() -> None:
    """Сбросить состояние (тесты)."""
    global _announced, _active
    with _lock:
        _devs.clear()
        _offline.clear()
        _bye.clear()
        _announced = _active = ""


def _ensure_table():
    from memory.db import _conn
    conn = _conn()
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS device_presence (
            device_id      TEXT    PRIMARY KEY,
            last_seen      TEXT    NOT NULL,
            last_input     TEXT,
            active_window  TEXT    NOT NULL DEFAULT '',
            is_online      INTEGER NOT NULL DEFAULT 0,
            input_score    REAL    NOT NULL DEFAULT 0.0
        );
    """)
    conn.commit()


# ── Обновление состояния устройства ──────────────────────────────────

def _idle_value(data: dict) -> Optional[float]:
    v = data.get("input_idle_s")
    if isinstance(v, bool) or not isinstance(v, (int, float)) or v != v or v < 0:
        return None
    return float(v)


def update(device_id: str, data: dict):
    """
    Вызывать при каждом ping/register от устройства.
    data: словарь из WS-сообщения (active_window, system_info, context,
    input_idle_s — секунд с последнего ввода на этом устройстве).
    """
    _ensure_table()
    from memory.db import _conn
    conn = _conn()

    active_window = data.get("active_window", "")
    now           = str(datetime.now())

    # input_score (прежняя оценка, когда input_idle_s нет):
    # voice_command — высокий score, просто ping — низкий
    msg_type    = data.get("type", "ping")
    input_score = 1.0 if msg_type == "voice_command" else 0.3

    conn.execute("""
        INSERT INTO device_presence
            (device_id, last_seen, last_input, active_window, is_online, input_score)
        VALUES (?, ?, ?, ?, 1, ?)
        ON CONFLICT(device_id) DO UPDATE SET
            last_seen     = excluded.last_seen,
            active_window = excluded.active_window,
            is_online     = 1,
            input_score   = MAX(input_score * 0.7 + excluded.input_score * 0.3, excluded.input_score),
            last_input    = CASE WHEN excluded.input_score > 0.5
                                 THEN excluded.last_seen
                                 ELSE last_input END
    """, (device_id, now, now if input_score > 0.5 else None,
          active_window, input_score))
    conn.commit()

    t = _now()
    with _lock:
        rec = _devs.setdefault(device_id, {"seen": t, "input_at": None, "since": t})
        rec["seen"] = t
        _bye.pop(device_id, None)           # жив — прежний bye недействителен
        _offline.pop(device_id, None)
        idle = _idle_value(data)
        if idle is not None:
            rec["input_at"] = t - idle
        if msg_type in INPUT_TYPES:
            note_input(device_id)
        else:
            _decide(t)


def note_input(device_id: str) -> None:
    """Голос или текст с устройства → оно активное сразу (без порогов)."""
    global _active
    if not device_id:
        return
    t = _now()
    with _lock:
        rec = _devs.setdefault(device_id, {"seen": t, "input_at": None, "since": t})
        rec["seen"] = rec["input_at"] = t
        _bye.pop(device_id, None)
        _offline.pop(device_id, None)
        if _active != device_id:
            log.info(f"[presence_sync] ввод на {device_id}: активное {_active or 'none'} → {device_id}")
        _active = device_id


def set_offline(device_id: str):
    """Вызывать в ws_handler finally."""
    global _active
    _ensure_table()
    from memory.db import _conn
    _conn().execute(
        "UPDATE device_presence SET is_online=0 WHERE device_id=?",
        (device_id,)
    )
    _conn().commit()
    with _lock:
        _devs.pop(device_id, None)
        prev = _bye.get(device_id) or (_offline.get(device_id) or {}).get("reason")
        _offline[device_id] = {"wall": _wall(), "reason": prev}
        if _active == device_id:
            _active = ""
        _decide(_now())


def mark_bye(device_id: str, reason: str = "exit") -> None:
    """Клиент прислал bye: ПК сразу офлайн с причиной (сокет может ещё жить)."""
    global _active
    if not device_id:
        return
    reason = reason if reason in BYE_REASONS else "exit"
    with _lock:
        _bye[device_id] = reason
        _offline[device_id] = {"wall": _wall(), "reason": reason}
        _devs.pop(device_id, None)
        if _active == device_id:
            _active = ""
        _decide(_now())
    log.info(f"[presence_sync] {device_id}: bye ({reason})")


def is_bye(device_id: str) -> bool:
    with _lock:
        return device_id in _bye


# ── Присутствие Мастера ──────────────────────────────────────────────

def is_pc(device_id: str) -> bool:
    """ПК (pc, laptop, mostech и др.), а не телефон."""
    try:
        from modules.device_manager import KNOWN_DEVICES
        kind = (KNOWN_DEVICES.get(device_id) or {}).get("type")
    except Exception:
        kind = None
    if kind:
        return kind != "phone"
    return "phone" not in (device_id or "").lower()


def get_master_presence(connected=None) -> dict:
    """Где Мастер на самом деле (по включённым ПК и вводу), а не по расписанию.

    state:
      at_pc         — ПК онлайн, ввод < 10 мин назад (device — какой ПК);
      at_work       — то же, но активный ПК — WORK_LAPTOP_DEVICE (mostech);
      away_from_pc  — ПК онлайн, ввода нет ≥ 10 мин (idle_s — сколько);
      pcs_off       — ни одного ПК онлайн (since — time.time() выключения
                      последнего, reason — shutdown|sleep|exit|None);
    Клиент без input_idle_s: ввод = последний голос/текст с этого ПК, иначе
    момент появления. Прислал bye — ПК не считается онлайн сразу.
    """
    import config
    if connected is None:
        import modules.state as st
        connected = st.connected_devices
    online = [d for d in list(connected) if is_pc(d) and d not in _bye]
    now = _now()
    with _lock:
        if not online:
            pcs = [(d, o) for d, o in _offline.items() if is_pc(d)]
            if pcs:
                dev, o = max(pcs, key=lambda x: x[1]["wall"])
                return {"state": "pcs_off", "device": dev, "idle_s": None,
                        "since": o["wall"], "reason": o.get("reason")}
            return {"state": "pcs_off", "device": None, "idle_s": None,
                    "since": None, "reason": None}
        _decide(now)
        idle = {}
        for d in online:
            rec = _devs.get(d)
            if rec is None:
                idle[d] = 0.0               # данных нет — считаем, что Мастер тут
            else:
                at = rec["input_at"] if rec["input_at"] is not None else rec.get("since", now)
                idle[d] = max(0.0, now - at)
        fresh = min(idle, key=idle.get)
        act = _active if _active in idle else fresh
        dev = act if idle[act] < AWAY_AFTER_S else fresh
        if idle[dev] >= AWAY_AFTER_S:
            return {"state": "away_from_pc", "device": dev, "idle_s": idle[dev],
                    "since": None, "reason": None}
        work = getattr(config, "WORK_LAPTOP_DEVICE", "mostech")
        return {"state": "at_work" if dev == work else "at_pc", "device": dev,
                "idle_s": idle[dev], "since": None, "reason": None}


def pc_voice_allowed() -> bool:
    """Можно ли говорить/писать проактивом на ПК: только если Мастер у ПК."""
    try:
        return get_master_presence()["state"] in ("at_pc", "at_work")
    except Exception as e:
        log.debug(f"[presence_sync] pc_voice_allowed: {type(e).__name__}: {e}")
        return True


# ── Определение активного устройства ─────────────────────────────────

def _legacy_active() -> Optional[str]:
    """Прежняя оценка (клиенты без input_idle_s): онлайн, недавний ping,
    ORDER BY input_score DESC, last_input DESC."""
    _ensure_table()
    from memory.db import _conn

    cutoff = str(datetime.now() - timedelta(seconds=ACTIVE_WINDOW_SEC))
    rows   = _conn().execute("""
        SELECT device_id, last_input, input_score
        FROM device_presence
        WHERE is_online = 1
          AND last_seen > ?
        ORDER BY input_score DESC, last_input DESC
        LIMIT 1
    """, (cutoff,)).fetchall()

    return rows[0]["device_id"] if rows else None


def _decide(now: float) -> None:
    """Единственное место, где выбирается активное устройство (под _lock)."""
    global _active
    for d in [d for d, r in _devs.items() if now - r["seen"] > ACTIVE_WINDOW_SEC]:
        del _devs[d]
    if not _devs:
        _active = ""
        return

    def idle(d):
        at = _devs[d]["input_at"]
        return None if at is None else max(0.0, now - at)

    known = {d: idle(d) for d in _devs if idle(d) is not None}
    cur = _active if _active in _devs else ""

    if not cur:
        if known:
            _active = min(known, key=known.get)
        else:
            try:
                legacy = _legacy_active()
            except Exception as e:
                log.debug(f"[presence_sync] legacy: {type(e).__name__}: {e}")
                legacy = None
            _active = legacy if legacy in _devs else max(_devs, key=lambda d: _devs[d]["seen"])
        return

    _active = cur
    rivals = {d: i for d, i in known.items() if d != cur}
    if not rivals:
        return
    best = min(rivals, key=rivals.get)
    if rivals[best] > SWITCH_NEW_IDLE_S:
        return
    # на текущем нет данных о вводе — других свидетельств нет
    if cur not in known or known[cur] >= SWITCH_CUR_IDLE_S:
        log.info(f"[presence_sync] ввод на {best} ({rivals[best]:.0f} с назад), "
                 f"на {cur} {'нет данных' if cur not in known else f'{known[cur]:.0f} с'}: "
                 f"активное → {best}")
        _active = best


def get_active_device() -> Optional[str]:
    """Единственное «активное устройство» сервера (см. docstring модуля)."""
    with _lock:
        _decide(_now())
        return _active or None


def get_all_online() -> list[dict]:
    """Список всех онлайн-устройств."""
    _ensure_table()
    from memory.db import _conn
    rows = _conn().execute("""
        SELECT device_id, active_window, input_score, last_seen
        FROM device_presence
        WHERE is_online = 1
        ORDER BY input_score DESC
    """).fetchall()
    return [dict(r) for r in rows]


# ── Детект смены активного устройства ────────────────────────────────

def check_device_transfer(connected_devices: dict) -> Optional[dict]:
    """
    Проверяет, сменилось ли активное устройство с прошлого объявления.
    Если да — возвращает {"from": str, "to": str} для broadcast_transfer.
    Если нет — None.

    Вызывать после каждого ping и после голоса/текста. Дребезга нет:
    пороги переключения — в _decide, отдельной паузы не нужно.
    """
    global _announced

    active = get_active_device()
    with _lock:
        if not active or active == _announced:
            return None
        # Проверяем что устройство в connected_devices
        if active not in connected_devices:
            return None
        prev      = _announced
        _announced = active

    log.info(f"[presence_sync] Фокус переехал: {prev or 'none'} → {active}")
    return {"from": prev, "to": active}


async def broadcast_transfer(
    transfer: dict,
    connected_devices: dict,
    mood_params: Optional[dict] = None,
):
    """
    Сообщает о переносе фокуса двум устройствам.
    proto 2: {"type": "presence", "event": "arrival"|"departure",
              "from": ..., "to": ...};
    proto 1: mood_update только с is_arrival / is_departure (без параметров
    настроения; mood_params оставлен для совместимости вызова и не шлётся).
    """
    import modules.state as st

    to_dev   = transfer["to"]
    from_dev = transfer.get("from", "")

    async def _tell(dev: str, event: str):
        ws = connected_devices.get(dev)
        if ws is None:
            return
        if st.device_proto.get(dev) == 2:
            msg = {"type": "presence", "event": event,
                   "from": from_dev or None, "to": to_dev}
        else:
            msg = {"type": "mood_update",
                   "params": {"is_arrival" if event == "arrival" else "is_departure": True}}
        try:
            await ws.send(json.dumps(msg, ensure_ascii=False))
        except Exception as e:
            log.debug(f"[presence_sync] {event} send {dev}: {e}")

    await _tell(to_dev, "arrival")
    if from_dev and from_dev != to_dev:
        await _tell(from_dev, "departure")


# ── №30 Контекстный мост (бесшовный перенос разговора) ───────────────

def get_context_for_device(device_id: str) -> str:
    """
    Возвращает последние N сообщений из истории для передачи контекста
    при смене активного устройства.
    Вызывать при регистрации нового устройства если произошёл transfer.
    """
    try:
        # История уже централизована на VPS — просто возвращаем summary
        # (соединение БД поток-локальное и берётся лениво — здесь оно не нужно)
        summary_file = "memory/session_summary.json"
        import os, json as _json
        if os.path.exists(summary_file):
            with open(summary_file) as f:
                data = _json.load(f)
            summary = data.get("summary", "")
            if summary:
                return f"[Контекст с другого устройства: {summary[:200]}]"
    except Exception:
        pass
    return ""
