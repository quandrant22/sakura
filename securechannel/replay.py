"""Защита первого сообщения рукопожатия IK от повтора (закрытие ProVerif ik Q7).

Проблема (PROTOCOL.md §3.2, FINDINGS.md): IK_INIT зашифровано только на ключах
`es`, `ss`, поэтому записанное сообщение 1 можно переслать позже — сервер
ответит IK_RESP, тронет реестр и откроет ещё один сеанс устройства. Ключи сеанса
атакующий не получит (нет эфемерного секрета клиента), но неинъективность
согласования (ik Q7) — это и лишний сеанс, и рычаг для отказа в обслуживании.

Две линии защиты на сервере, без изменения формата протокола:

1. Кэш эфемерных открытых ключей `e`. В Noise IK сообщение 1 начинается с
   эфемерного ключа инициатора открытым текстом (первые 32 байта, X25519).
   Честный клиент генерирует `e` заново для каждого рукопожатия, поэтому
   совпадение `e` = повтор. Ключ запоминается только после успешной
   расшифровки и проверки реестра — мусор кэш не засоряет.

2. Окно свежести по `ts` из payload IK_INIT ({"v":1,"device_id","ts"}). `ts`
   лежит внутри AEAD-шифртекста, связанного с хешем рукопожатия: атакующий не
   может его заменить, не сломав тег. Сообщение с |now − ts| > window отклоняется.

Почему этого достаточно. Сообщение принимается, только если ts ∈ [t − W, t + W],
где t — момент приёма. Значит, оно может быть «свежим» лишь до ts + W ≤ t + 2W.
Кэш хранит `e` TTL = 2W от первого приёма — весь интервал, в котором повтор
прошёл бы проверку свежести. Вне интервала повтор отсекает окно `ts`. Внутри —
кэш. Ограничение размера (вытеснение самых старых записей) — защита памяти;
кэш пополняют только расшифрованные сообщения устройств из реестра, поэтому
переполнить его может лишь сам владелец ключа устройства.

Остаточный риск: кэш в памяти процесса. После перезапуска сервера повтор
сообщения, записанного менее чем за W до перезапуска, пройдёт один раз.
"""
from __future__ import annotations

import threading
import time
from collections import OrderedDict

E_LEN = 32                      # X25519 public key (Noise DH 25519)
TS_WINDOW_S = 12 * 3600.0       # W: допустимый разброс часов клиента и сервера
TTL_S = 2 * TS_WINDOW_S         # 2W — см. обоснование выше
MAX_ENTRIES = 100_000           # ~100 000 рукопожатий в сутки на запас; ≈ 10 МБ


def ephemeral_of(ik_init_body: bytes) -> bytes | None:
    """Эфемерный ключ инициатора из тела IK_INIT (None, если тело короче)."""
    return bytes(ik_init_body[:E_LEN]) if len(ik_init_body) >= E_LEN else None


def ts_is_fresh(ts, *, now: float, window: float = TS_WINDOW_S) -> bool:
    """|now − ts| ≤ window. Отсутствующий/нечисловой ts — свежим не считается."""
    if window <= 0:
        return True                      # проверка выключена
    if isinstance(ts, bool) or not isinstance(ts, (int, float)):
        return False
    return abs(now - float(ts)) <= window


class ReplayCache:
    """Множество недавно принятых `e` с TTL и ограничением размера (LRU по вставке)."""

    def __init__(self, *, ttl: float = TTL_S, max_entries: int = MAX_ENTRIES,
                 clock=time.monotonic):
        self.ttl = ttl
        self.max_entries = max_entries
        self._clock = clock
        self._lock = threading.Lock()
        self._seen: OrderedDict[bytes, float] = OrderedDict()   # e → момент истечения

    def __len__(self) -> int:
        with self._lock:
            self._expire(self._clock())
            return len(self._seen)

    def _expire(self, now: float) -> None:
        while self._seen:
            _, exp = next(iter(self._seen.items()))
            if exp > now:
                break
            self._seen.popitem(last=False)

    def check_and_add(self, e: bytes) -> bool:
        """True — `e` новый (запомнен); False — повтор в пределах TTL."""
        now = self._clock()
        with self._lock:
            self._expire(now)
            if e in self._seen:
                return False
            self._seen[e] = now + self.ttl
            while len(self._seen) > self.max_entries:
                self._seen.popitem(last=False)          # самая старая запись
            return True
