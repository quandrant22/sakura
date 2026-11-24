"""desktop.core.gpu_stats — телеметрия видеокарты (загрузка GPU, VRAM, температура).

Основной путь на NVIDIA: прямой вызов nvml.dll через ctypes.CDLL (без дочерних процессов, <0.1 мс).
Запасной путь на AMD/Intel (Windows): счётчики производительности win32pdh (GPU Engine 3D).
"""

from __future__ import annotations

import ctypes
import logging
import sys
import threading
import time

log = logging.getLogger("sakura.gpu")

_CACHE_TTL_S = 1.5
_lock = threading.Lock()
_cache_data: dict = {}
_cache_until = 0.0


class _NvmlUtilization(ctypes.Structure):
    _fields_ = [("gpu", ctypes.c_uint), ("memory", ctypes.c_uint)]


class _NvmlMemory(ctypes.Structure):
    _fields_ = [
        ("total", ctypes.c_ulonglong),
        ("free", ctypes.c_ulonglong),
        ("used", ctypes.c_ulonglong),
    ]


class _NvmlReader:
    """Лёгкая обёртка вокруг nvml.dll без внешних пакетов."""

    def __init__(self) -> None:
        self._lib = None
        self._handle = None
        self._name: str | None = None
        self._failed_permanently = False

    def _ensure(self) -> bool:
        if self._failed_permanently:
            return False
        if self._lib is not None and self._handle is not None:
            return True
        for candidate in ("nvml.dll", r"C:\Windows\System32\nvml.dll"):
            try:
                lib = ctypes.CDLL(candidate)
                if lib.nvmlInit_v2() != 0:
                    continue
                count = ctypes.c_uint(0)
                if lib.nvmlDeviceGetCount_v2(ctypes.byref(count)) != 0 or count.value == 0:
                    continue
                handle = ctypes.c_void_p()
                if lib.nvmlDeviceGetHandleByIndex_v2(0, ctypes.byref(handle)) != 0:
                    continue
                name_buf = ctypes.create_string_buffer(96)
                if lib.nvmlDeviceGetName(handle, name_buf, 96) == 0:
                    self._name = name_buf.value.decode("utf-8", errors="ignore").strip() or None
                self._lib = lib
                self._handle = handle
                return True
            except OSError:
                continue
            except Exception as e:
                log.debug("[gpu] nvml init error: %s", e)
        self._failed_permanently = True
        return False

    def read(self) -> dict:
        if not self._ensure():
            return {}
        try:
            util = _NvmlUtilization()
            mem = _NvmlMemory()
            temp = ctypes.c_uint(0)
            out: dict = {}
            if self._name:
                out["gpu_name"] = self._name
            if self._lib.nvmlDeviceGetUtilizationRates(self._handle, ctypes.byref(util)) == 0:
                out["gpu"] = int(util.gpu)
            if self._lib.nvmlDeviceGetMemoryInfo(self._handle, ctypes.byref(mem)) == 0 and mem.total > 0:
                out["vram"] = round(mem.used / mem.total * 100.0, 1)
                out["vram_used_gb"] = round(mem.used / (1024 ** 3), 2)
                out["vram_total_gb"] = round(mem.total / (1024 ** 3), 2)
            if self._lib.nvmlDeviceGetTemperature(self._handle, 0, ctypes.byref(temp)) == 0:
                out["gpu_temp"] = float(temp.value)
            return out
        except Exception as e:
            log.debug("[gpu] nvml read error: %s", e)
            self._handle = None
            return {}


_nvml = _NvmlReader()
_pdh_query = None
_pdh_counter = None
_pdh_failed = False


def _read_pdh_gpu() -> dict:
    """Fallback для AMD/Intel на Windows через win32pdh (GPU Engine 3D)."""
    global _pdh_query, _pdh_counter, _pdh_failed
    if _pdh_failed:
        return {}
    try:
        import win32pdh
        if _pdh_query is None:
            _pdh_query = win32pdh.OpenQuery()
            _pdh_counter = win32pdh.AddEnglishCounter(
                _pdh_query, r"\GPU Engine(*engtype_3D)\Utilization Percentage"
            )
            win32pdh.CollectQueryData(_pdh_query)
            return {}
        win32pdh.CollectQueryData(_pdh_query)
        _, vals = win32pdh.GetFormattedCounterArray(_pdh_counter, win32pdh.PDH_FMT_DOUBLE)
        total = min(100.0, sum(max(0.0, float(v)) for _, v in vals))
        return {"gpu": int(round(total))}
    except Exception:
        _pdh_failed = True
        return {}


def get_gpu_stats(*, use_cache: bool = True) -> dict:
    """Возвращает словарь с данными GPU: gpu (% загрузки), gpu_temp, vram (%), gpu_name."""
    global _cache_data, _cache_until
    if sys.platform != "win32":
        return {}
    now = time.monotonic()
    with _lock:
        if use_cache and now < _cache_until:
            return dict(_cache_data)
        data = _nvml.read()
        if not data or data.get("gpu") is None:
            pdh = _read_pdh_gpu()
            if pdh:
                data = {**pdh, **data}
        _cache_data = data
        _cache_until = now + _CACHE_TTL_S
        return dict(data)
