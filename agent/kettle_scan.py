"""
Запусти этот скрипт на ноуте чтобы увидеть все BLE характеристики чайника.
Чайник должен быть включён в розетку.

python kettle_scan.py
"""
import asyncio
from bleak import BleakClient

MAC = "DA:55:99:95:24:76"

async def main():
    async with BleakClient(MAC, timeout=15) as client:
        print(f"Подключён: {client.is_connected}\n")
        for service in client.services:
            print(f"SERVICE: {service.uuid}  ({service.description})")
            for char in service.characteristics:
                props = ", ".join(char.properties)
                print(f"  CHAR: {char.uuid}  [{props}]")
                for desc in char.descriptors:
                    print(f"    DESC: {desc.uuid}")
            print()

asyncio.run(main())
