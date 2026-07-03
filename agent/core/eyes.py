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
    except Exception:
        pass
    return info
