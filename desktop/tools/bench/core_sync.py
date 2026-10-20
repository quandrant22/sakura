"""Замер «до/после» для ядра без живых проверок: ничего не включает, не нажимает и не меняет.

1. Стоимость синхронных вызовов, которые раньше выполнялись прямо в цикле событий ядра
   (heartbeat и опрос панели музыки): окно, датчики, громкость сессии (только чтение),
   получение менеджера SMTC (request_async без чтения сессий).
2. Модель задержки «смена трека → окно» в наблюдателе SMTC: событие приходит в случайный момент;
   чтение занимает READ_MS. Старый алгоритм терял событие, пришедшее во время чтения (ждал сторожа
   1 с), новый читает ещё раз.

python -m desktop.tools.bench.core_sync
"""
import asyncio
import random
import statistics
import time

READ_NEW_MS = 12.0   # чтение свойств сессии без request_async (модель; сессию Я.Музыки стенд не читает)
DEBOUNCE_MS = 30.0
WATCHDOG_MS = 1000.0


def _ms(fn, n=20):
    out = []
    for _ in range(n):
        t = time.perf_counter()
        try:
            fn()
        except Exception:  # noqa: BLE001
            pass
        out.append((time.perf_counter() - t) * 1000)
    out.sort()
    return {"p50": round(statistics.median(out), 2), "max": round(out[-1], 2)}


def sync_costs() -> dict:
    from desktop.core.eyes import get_active_window
    from desktop.core.media.yandex_remote import _app_running
    from desktop.core.platform import get_platform
    from desktop.core.presence import _collect_system_info
    res = {"get_active_window": _ms(get_active_window),
           "system_info (psutil, датчики)": _ms(_collect_system_info, n=5),
           "app_volume_get (COM, чтение)": _ms(lambda: get_platform().app_volume_get(("яндекс", "yandex"))),
           "процесс Я.Музыки (psutil.process_iter)": _ms(_app_running, n=5)}
    try:
        from winsdk.windows.media.control import GlobalSystemMediaTransportControlsSessionManager as M

        async def req():
            await M.request_async()

        def one():
            asyncio.run(req())
        res["SMTC request_async"] = _ms(one)
    except Exception as e:  # noqa: BLE001
        res["SMTC request_async"] = f"нет winsdk ({type(e).__name__})"
    return res


def simulate(new: bool, request_ms: float, events=400, seed=1) -> dict:
    """Задержка событие → состояние в окне, мс (модель цикла чтений наблюдателя).
    Старое чтение = новое + request_async (измерен в п. 1)."""
    rnd = random.Random(seed)
    read = READ_NEW_MS if new else READ_NEW_MS + request_ms
    lat = []
    for _ in range(events):
        # Начало текущего чтения — от 0 до 3 READ до события: событие то во время чтения, то между.
        busy_until = rnd.uniform(-2 * read, read)
        if busy_until <= 0:  # цикл свободен — debounce и чтение
            lat.append(DEBOUNCE_MS + read)
            continue
        if new:  # событие во время чтения: после него — ещё одно чтение
            lat.append(busy_until + read)
        else:    # старый: событие поглощено, ждём сторожа (в среднем полпериода, худшее — период)
            lat.append(busy_until + rnd.uniform(0, WATCHDOG_MS) + read)
    lat.sort()
    return {"p50": round(statistics.median(lat)), "p95": round(lat[int(0.95 * len(lat))]), "max": round(lat[-1])}


def main():
    print("Синхронные вызовы (раньше в цикле событий), мс:")
    costs = sync_costs()
    for k, v in costs.items():
        print(f"  {k}: {v}")
    req = costs.get("SMTC request_async")
    req_ms = req["p50"] if isinstance(req, dict) else 30.0
    print(f"Модель «смена трека → окно», мс (чтение {READ_NEW_MS} мс, request_async {req_ms} мс):")
    print("  до:   ", simulate(False, req_ms))
    print("  после:", simulate(True, req_ms))


if __name__ == "__main__":
    main()
