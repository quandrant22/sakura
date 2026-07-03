import asyncio, sys
sys.path.insert(0, r"C:\Sakura")
from core.extension_server import send_command, is_connected

async def test():
    print("Подключено:", is_connected())

    print("\n--- Вкладки ---")
    r = await send_command("tabs_list")
    if isinstance(r, list):
        for t in r:
            print(f"  [{t['id']}] {t['title'][:60]}")
    else:
        print(r)

    print("\n--- YouTube пауза ---")
    r = await send_command("youtube_pause")
    print(r)

    print("\n--- YouTube инфо ---")
    r = await send_command("youtube_info")
    print(r)

asyncio.run(test())