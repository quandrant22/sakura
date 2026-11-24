"""core/eyes.py — глаза: активное окно и состояние железа."""

try:    import psutil
except ImportError: psutil = None
try:    import win32gui
except ImportError: win32gui = None


def get_active_window() -> str:
    if not win32gui:
        return ""
    try:
        return win32gui.GetWindowText(win32gui.GetForegroundWindow()) or ""
    except Exception:
        return ""


def get_system_info() -> dict:
    info = {"cpu": 0, "ram": 0, "battery": None, "plugged": True}
    if not psutil:
        return info
    try:
        info["cpu"] = int(psutil.cpu_percent(interval=None))
        info["ram"] = int(psutil.virtual_memory().percent)
        batt = psutil.sensors_battery()
        if batt is not None:
            info["battery"] = int(batt.percent)
            info["plugged"] = bool(batt.power_plugged)
        from desktop.core.gpu_stats import get_gpu_stats
        gpu_data = get_gpu_stats()
        for key in ("gpu", "gpu_temp", "vram", "gpu_name"):
            if gpu_data.get(key) is not None:
                info[key] = gpu_data[key]
    except Exception:
        pass
    return info
