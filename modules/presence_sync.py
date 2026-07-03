"""
modules/presence_sync.py — Бесшовное присутствие (бэклоги №29, №30).

№29: Присутствие следует за тобой — сел за другой ПК →
     орб «переехал» (передача фокуса между устройствами).

№30: Бесшовный перенос разговора — начал на ноуте, продолжил
     на ПК без потери контекста (память централизована — почти бесплатно).

Логика:
  - Каждое устройство при ping шлёт active_window и last_input_time
  - VPS определяет АКТИВНОЕ устройство — то, где последний ввод был недавно
  - При смене активного устройства VPS шлёт mood_update с флагом device_switch
  - Агент на новом устройстве получает это и анимирует «переезд» орба

Интеграция в ws_handler:
  При каждом ping вызвать presence_sync.update(device_id, data)
  После — presence_sync.get_active_device() для маршрутизации TTS

Хранение: таблица device_presence в sakura.db.
"""

import json
import logging
import time
from datetime import datetime, timedelta
from typing import Optional

log = logging.getLogger("sakura.presence_sync")

# Устройство считается активным если последний ввод был не далее ACTIVE_WINDOW секунд назад
ACTIVE_WINDOW_SEC  = 120
# После TRANSFER_COOLDOWN не переключаем снова (чтобы не мелькало)
TRANSFER_COOLDOWN  = 30.0

_last_transfer_at: float = 0.0
_current_active:   str   = ""


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

def update(device_id: str, data: dict):
    """
    Вызывать при каждом ping/register от устройства.
    data: словарь из WS-сообщения (active_window, system_info, context).
    """
    _ensure_table()
    from memory.db import _conn
    conn = _conn()

    active_window = data.get("active_window", "")
    now           = str(datetime.now())

    # input_score: оцениваем насколько активно устройство
    # (пришёл voice_command — высокий score, просто ping — низкий)
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


def set_offline(device_id: str):
    """Вызывать в ws_handler finally."""
    _ensure_table()
    from memory.db import _conn
    _conn().execute(
        "UPDATE device_presence SET is_online=0 WHERE device_id=?",
        (device_id,)
    )
    _conn().commit()


# ── Определение активного устройства ─────────────────────────────────

def get_active_device() -> Optional[str]:
    """
    Возвращает device_id наиболее активного онлайн-устройства.
    Критерии: недавний ввод + высокий input_score.
    """
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
    Проверяет, сменилось ли активное устройство.
    Если да — возвращает {"from": str, "to": str} для отправки mood_update.
    Если нет — None.

    Вызывать из proactive_loop или ws_handler каждые 10-15 секунд.
    """
    global _last_transfer_at, _current_active

    now    = time.monotonic()
    active = get_active_device()

    if not active or active == _current_active:
        return None

    if now - _last_transfer_at < TRANSFER_COOLDOWN:
        return None

    # Проверяем что оба устройства в connected_devices
    if active not in connected_devices:
        return None

    prev              = _current_active
    _current_active   = active
    _last_transfer_at = now

    log.info(f"[presence_sync] Фокус переехал: {prev or 'none'} → {active}")
    return {"from": prev, "to": active}


async def broadcast_transfer(
    transfer: dict,
    connected_devices: dict,
    mood_params: dict,
):
    """
    Рассылает уведомление о переносе фокуса.
    Новое устройство получает mood_update с флагом is_arrival=True —
    орб анимирует «прилёт».
    Старое устройство получает is_departure=True — орб «тускнеет».
    """
    import json

    to_dev   = transfer["to"]
    from_dev = transfer.get("from", "")

    # Новое устройство — «прилёт»
    if to_dev in connected_devices:
        arrive_params = {**mood_params, "is_arrival": True}
        try:
            await connected_devices[to_dev].send(
                json.dumps({"type": "mood_update", "params": arrive_params})
            )
        except Exception as e:
            log.debug(f"[presence_sync] arrival send: {e}")

    # Старое устройство — «уход»
    if from_dev and from_dev in connected_devices:
        depart_params = {**mood_params, "is_departure": True, "bright": 0.3}
        try:
            await connected_devices[from_dev].send(
                json.dumps({"type": "mood_update", "params": depart_params})
            )
        except Exception as e:
            log.debug(f"[presence_sync] departure send: {e}")


# ── №30 Контекстный мост (бесшовный перенос разговора) ───────────────

def get_context_for_device(device_id: str) -> str:
    """
    Возвращает последние N сообщений из истории для передачи контекста
    при смене активного устройства.
    Вызывать при регистрации нового устройства если произошёл transfer.
    """
    try:
        # История уже централизована на VPS — просто возвращаем summary
        from memory.db import _conn
        # Последнее summary дня
        conn = _conn()
        # Используем reflection summary если есть
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
