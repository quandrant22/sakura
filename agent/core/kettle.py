"""
core/kettle.py — Управление SkyKettle RK-G210S по BLE (Сакура-агент).

Протокол подтверждён диагностикой на реальном устройстве DA:55:99:95:24:76.

Команды (action в WS):
  kettle:boil          — вскипятить и выключить
  kettle:heat:80       — нагреть до 80°C и держать
  kettle:boil_heat:80  — вскипятить, остудить до 80°C и держать
  kettle:off           — выключить
  kettle:status        — текущая температура и статус

Зависимости: pip install bleak
"""

import asyncio
import json
import logging
import os
import secrets
from typing import Optional

log = logging.getLogger("sakura.kettle")

# ── Конфигурация ──────────────────────────────────────────────────────
KETTLE_MAC = "DA:55:99:95:24:76"
KEY_FILE   = "memory/kettle_key.json"

# BLE характеристики (Nordic UART Service)
CHAR_TX = "6e400002-b5a3-f393-e0a9-e50e24dcca9e"  # write → чайник
CHAR_RX = "6e400003-b5a3-f393-e0a9-e50e24dcca9e"  # notify ← чайник

# Команды протокола (подтверждено диагностикой RK-G210S)
CMD_AUTH   = 0xFF  # авторизация ключом
CMD_STATUS = 0x06  # запрос статуса
CMD_ON     = 0x03  # включить (boil/heat/boil_heat)
CMD_OFF    = 0x04  # выключить

# Режимы для CMD_ON (первый байт данных)
MODE_BOIL      = 0x00  # кипятить и выключить
MODE_HEAT      = 0x01  # нагреть до температуры и держать
MODE_BOIL_HEAT = 0x02  # вскипятить → остудить до температуры → держать

# Расшифровка статуса (байт 3 ответа на STATUS)
STATUS_NAMES = {
    0x00: "выключен",
    0x01: "нагрев",
    0x02: "кипячение",
    0x03: "поддержание",
    0x04: "готов",
}

BLE_TIMEOUT = 15.0


# ── Ключ авторизации ─────────────────────────────────────────────────

def _load_key() -> Optional[bytes]:
    try:
        if os.path.exists(KEY_FILE):
            with open(KEY_FILE, "r") as f:
                return bytes.fromhex(json.load(f)["key"])
    except Exception:
        pass
    return None


def _save_key(key: bytes):
    os.makedirs(os.path.dirname(KEY_FILE) or ".", exist_ok=True)
    with open(KEY_FILE, "w") as f:
        json.dump({"key": key.hex()}, f)


def _get_or_create_key() -> bytes:
    key = _load_key()
    if not key:
        key = secrets.token_bytes(8)
        _save_key(key)
        log.info(f"[kettle] Новый ключ: {key.hex()}")
    return key


# ── Пакеты протокола ─────────────────────────────────────────────────

_counter = 0


def _pkt(cmd: int, data: bytes = b"") -> bytes:
    global _counter
    _counter = (_counter + 1) & 0xFF
    return bytes([0x55, _counter, cmd]) + data + bytes([0xAA])


# ── BLE клиент ───────────────────────────────────────────────────────

class KettleClient:

    def __init__(self):
        self._response: Optional[bytes] = None
        self._event = asyncio.Event()

    def _on_notify(self, sender, data: bytearray):
        self._response = bytes(data)
        log.info(f"[kettle] RX: {self._response.hex()}")
        self._event.set()

    async def _send(self, client, packet: bytes, timeout: float = 5.0) -> Optional[bytes]:
        self._response = None
        self._event.clear()
        log.info(f"[kettle] TX: {packet.hex()}")
        await client.write_gatt_char(CHAR_TX, packet, response=False)
        try:
            await asyncio.wait_for(self._event.wait(), timeout=timeout)
        except asyncio.TimeoutError:
            log.warning("[kettle] Тайм-аут ответа")
        return self._response

    async def _auth(self, client, key: bytes) -> bool:
        resp = await self._send(client, _pkt(CMD_AUTH, key))
        if resp and len(resp) >= 4:
            ok = resp[3] == 0x01
            log.info(f"[kettle] Auth: {'OK' if ok else 'FAIL'}")
            return ok
        return False

    async def run(self, action: str) -> dict:
        from bleak import BleakClient, BleakError
        key = _get_or_create_key()
        try:
            async with BleakClient(KETTLE_MAC, timeout=BLE_TIMEOUT) as client:
                log.info(f"[kettle] Подключён к {KETTLE_MAC}")
                await client.start_notify(CHAR_RX, self._on_notify)
                await asyncio.sleep(0.5)

                if not await self._auth(client, key):
                    return {
                        "ok": False,
                        "result": "Авторизация не прошла. Зажми кнопку на чайнике до мигания и повтори.",
                    }
                await asyncio.sleep(0.5)

                result = await self._execute(client, action)
                await client.stop_notify(CHAR_RX)
                return result

        except BleakError as e:
            log.error(f"[kettle] BLE ошибка: {e}")
            return {"ok": False, "result": f"Чайник не отвечает: {e}"}
        except Exception as e:
            import traceback
            log.error(f"[kettle] Ошибка: {type(e).__name__}: {e}\n{traceback.format_exc()}")
            return {"ok": False, "result": f"{type(e).__name__}: {e}"}

    async def _execute(self, client, action: str) -> dict:
        parts = action.split(":")

        # ── status ───────────────────────────────────────────────────
        if action == "status":
            resp = await self._send(client, _pkt(CMD_STATUS))
            if not resp or len(resp) < 10:
                return {"ok": False, "result": "Нет данных от чайника"}
            # Байты ответа STATUS (подтверждено диагностикой):
            # 55 cnt 06 status mode temp_set temp_cur ... AA
            status_code  = resp[3]
            temp_current = resp[8]   # байт 8 = текущая температура
            temp_target  = resp[9]   # байт 9 = целевая температура
            status_name  = STATUS_NAMES.get(status_code, f"код {status_code}")
            msg = f"Чайник: {status_name}, {temp_current}°C"
            if temp_target and status_code in (0x01, 0x03):
                msg += f" (цель {temp_target}°C)"
            return {
                "ok": True, "result": msg,
                "status": status_name,
                "temp_current": temp_current,
                "temp_target": temp_target,
            }

        # ── off ───────────────────────────────────────────────────────
        if action == "off":
            resp = await self._send(client, _pkt(CMD_OFF))
            ok = resp and len(resp) >= 4 and resp[3] == 0x01
            return {"ok": ok, "result": "Чайник выключен" if ok else "Не удалось выключить"}

        # ── boil ──────────────────────────────────────────────────────
        if action == "boil":
            # CMD_ON + mode=00 (boil) + submode=00 + temp=00
            resp = await self._send(client, _pkt(CMD_ON))
            ok = resp and len(resp) >= 4 and resp[3] == 0x01
            return {"ok": ok, "result": "Чайник кипятится" if ok else "Не удалось включить"}

        # ── heat:N ────────────────────────────────────────────────────
        if parts[0] == "heat" and len(parts) == 2:
            temp = max(40, min(95, int(parts[1])))
            resp = await self._send(client, _pkt(CMD_ON, bytes([MODE_HEAT, temp])))
            ok = resp and len(resp) >= 4 and resp[3] == 0x01
            return {"ok": ok, "result": f"Нагрев до {temp}°C" if ok else "Не удалось включить нагрев"}

        # ── boil_heat:N ───────────────────────────────────────────────
        if parts[0] == "boil_heat" and len(parts) == 2:
            temp = max(40, min(95, int(parts[1])))
            resp = await self._send(client, _pkt(CMD_ON, bytes([MODE_BOIL_HEAT, temp])))
            ok = resp and len(resp) >= 4 and resp[3] == 0x01
            return {"ok": ok, "result": f"Кипячение → держать {temp}°C" if ok else "Не удалось включить"}

        return {"ok": False, "result": f"Неизвестная команда: {action}"}


async def kettle_command(action: str) -> dict:
    """Точка входа. Вызывать из agent._run_command."""
    return await KettleClient().run(action)