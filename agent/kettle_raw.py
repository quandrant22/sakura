"""
Диагностический скрипт — слушает ВСЕ notify от чайника и пробует разные команды.
Запускай когда чайник на подставке, включён в розетку, НЕ кипятится.

python kettle_raw.py
"""
import asyncio
from bleak import BleakClient

MAC     = "DA:55:99:95:24:76"
CHAR_TX = "6e400002-b5a3-f393-e0a9-e50e24dcca9e"
CHAR_RX = "6e400003-b5a3-f393-e0a9-e50e24dcca9e"
KEY     = bytes.fromhex("61dea766c2c676a4")  # твой ключ

def notify_handler(sender, data):
    print(f"  << RX [{sender}]: {bytes(data).hex()}  raw={list(data)}")

async def send(client, data: bytes, label: str = ""):
    print(f"  >> TX {label}: {data.hex()}")
    await client.write_gatt_char(CHAR_TX, data, response=False)
    await asyncio.sleep(2.0)  # ждём дольше

async def main():
    print(f"Подключаюсь к {MAC}...")
    async with BleakClient(MAC, timeout=15) as client:
        print(f"Подключён\n")

        # Подписываемся на notify
        await client.start_notify(CHAR_RX, notify_handler)
        await asyncio.sleep(1.0)

        # 1. Auth
        print("=== AUTH ===")
        auth_pkt = bytes([0x55, 0x01, 0xFF]) + KEY + bytes([0xAA])
        await send(client, auth_pkt, "auth")

        # 2. Status (0x06) — просто запрос состояния
        print("=== STATUS (cmd=06) ===")
        await send(client, bytes([0x55, 0x02, 0x06, 0xAA]), "status")

        # 3. SET boil (mode=00, temp=00)
        print("=== SET BOIL (cmd=05, mode=00) ===")
        await send(client, bytes([0x55, 0x03, 0x05, 0x00, 0x00, 0x00, 0x00, 0xAA]), "boil")

        # 4. Альтернативный формат SET (без нулевых байтов)
        print("=== SET BOIL alt (cmd=05 короткий) ===")
        await send(client, bytes([0x55, 0x04, 0x05, 0x00, 0xAA]), "boil_short")

        # 5. Ещё вариант — некоторые прошивки используют cmd=03
        print("=== cmd=03 (альт включение) ===")
        await send(client, bytes([0x55, 0x05, 0x03, 0xAA]), "cmd03")

        print("\nГотово. Если чайник не ответил ни на что — проверь воду в чайнике.")
        await asyncio.sleep(1.0)
        await client.stop_notify(CHAR_RX)

asyncio.run(main())
