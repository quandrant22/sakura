"""Видимые подтверждения опасных действий: окно спрашивает «Разрешить?», ответ — ядру.

Опасное действие (confirm в реестре) пришло без confirmed: true — ядро показывает запрос в окне
(событие confirm_request) и ждёт ответа до TIMEOUT_S; нет ответа — отказ. Текст запроса описывает
действие (что и над чем), содержимое файлов и тексты ввода в него не попадают.
"""
import asyncio
import itertools
import time

TIMEOUT_S = 60.0

LABELS = {
    "power.sleep": lambda a: "Перевести компьютер в спящий режим",
    "process.kill": lambda a: f"Завершить процесс {a}",
    "net.wifi": lambda a: f"Wi-Fi: {'включить' if a.strip().lower() in ('on', 'вкл') else 'выключить'}",
    "files.move": lambda a: "Переместить файл: " + " → ".join(p.strip() for p in a.split("|")),
    "files.delete": lambda a: f"Удалить в корзину: {a}",
}


def label(action: str, arg: str) -> str:
    fn = LABELS.get(action)
    return fn(arg or "") if fn else f"Выполнить {action}"


class Confirmations:
    def __init__(self, emit, clock=time.time, timeout=TIMEOUT_S):
        self._emit = emit
        self._clock = clock
        self._timeout = timeout
        self._ids = itertools.count(1)
        self._pending: dict[str, dict] = {}

    def pending(self) -> list[dict]:
        return [{k: v for k, v in p.items() if k != "future"} for p in self._pending.values()]

    async def ask(self, action: str, arg: str) -> bool:
        cid = f"c{next(self._ids)}"
        fut = asyncio.get_running_loop().create_future()
        item = {"id": cid, "action": action, "label": label(action, arg), "ts": self._clock(),
                "expires": self._clock() + self._timeout, "future": fut}
        self._pending[cid] = item
        self._emit("confirm_request", **{k: v for k, v in item.items() if k != "future"})
        try:
            return bool(await asyncio.wait_for(fut, self._timeout))
        except asyncio.TimeoutError:
            return False
        finally:
            self._pending.pop(cid, None)
            self._emit("confirm_done", id=cid)

    def answer(self, cid: str, yes: bool) -> bool:
        item = self._pending.get(cid)
        if item is None or item["future"].done():
            return False
        item["future"].set_result(bool(yes))
        return True
