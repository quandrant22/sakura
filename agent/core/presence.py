"""
core/presence.py — Присутствие на стороне клиента (бэклоги №45, №20).

№45: Орб «тихо оживает» когда ты печатаешь или двигаешь мышь,
     даже без слов. Присутствие без разговора.

№20: Watchdog — следит за состоянием компонентов агента
     (WS-соединение, TTS, Hearing). При падении — перезапускает
     и докладывает Сакуре.

Интеграция в sakura.py:
    from core.presence import ActivityWatcher, Watchdog
    watcher  = ActivityWatcher(bus)
    watchdog = Watchdog(agent, bus)
    watcher.start()
    watchdog.start()
"""

import asyncio
import logging
import threading
import time
from datetime import datetime

log = logging.getLogger("sakura.presence")


# ── Детект активности (№45) ──────────────────────────────────────────

class ActivityWatcher:
    """
    Следит за активностью мыши и клавиатуры через pynput.
    При активности эмитирует в шину bus событие activity_pulse.
    SphereCore реагирует: лёгкое ускорение пульса без смены состояния.

    Событие: bus.emit("activity_pulse", level=0.0..1.0)
      level = 1.0 при быстром вводе, 0.3 при редком движении мыши.
    """

    def __init__(self, bus, idle_sec: float = 30.0):
        self._bus      = bus
        self._idle_sec = idle_sec
        self._last_at  = time.monotonic()
        self._level    = 0.0
        self._lock     = threading.Lock()
        self._thread   = None
        self._running  = False

    def _on_move(self, x, y):
        self._touch(0.3)

    def _on_key(self, key):
        self._touch(0.7)

    def _on_click(self, x, y, button, pressed):
        if pressed:
            self._touch(0.5)

    def _on_scroll(self, x, y, dx, dy):
        self._touch(0.4)

    def _touch(self, level: float):
        with self._lock:
            self._last_at = time.monotonic()
            self._level   = max(self._level, level)

    def _emit_loop(self):
        """Периодически шлёт текущий уровень активности в шину и обновляет глобал."""
        global _activity_level
        while self._running:
            time.sleep(2.0)
            with self._lock:
                idle = time.monotonic() - self._last_at
                if idle < self._idle_sec:
                    # Затухание: чем дольше не трогали — тем меньше
                    decay  = max(0.0, 1.0 - idle / self._idle_sec)
                    level  = self._level * decay
                    self._level = level
                    _activity_level = level
                    if level > 0.05:
                        self._bus.emit("activity_pulse", level=round(level, 2))
                else:
                    _activity_level = 0.0

    def start(self):
        try:
            from pynput import mouse, keyboard
            self._running = True

            mouse.Listener(
                on_move=self._on_move,
                on_click=self._on_click,
                on_scroll=self._on_scroll,
            ).start()

            keyboard.Listener(on_press=self._on_key).start()

            self._thread = threading.Thread(target=self._emit_loop, daemon=True)
            self._thread.start()
            log.info("[presence] ActivityWatcher запущен.")
        except ImportError:
            log.warning("[presence] pynput не установлен — активность не отслеживается. "
                        "pip install pynput")
        except Exception as e:
            log.warning(f"[presence] ActivityWatcher не запустился: {e}")

    def stop(self):
        self._running = False


# ── Глобальный доступ к уровню активности ──────────────────────────────

_activity_level: float = 0.0

def get_activity_level() -> float:
    """Текущий уровень активности 0..1 — для агента и сервера."""
    return _activity_level

def _set_activity_level(level: float):
    global _activity_level
    _activity_level = level

# ── Patch: ActivityWatcher обновляет глобальный уровень ─────────────────
# (вызывается из _emit_loop)


# ── Patch SphereCore для activity_pulse ─────────────────────────────

# Добавить в ui/app.py UiBridge:
#   activityPulse = pyqtSignal(float)
#   bus.subscribe("activity_pulse", lambda **kw: self.activityPulse.emit(kw["level"]))
#
# В sakura.py:
#   bridge.activityPulse.connect(overlay.set_activity)
#
# В ui/overlay.py добавить метод Overlay.set_activity(level):
#   def set_activity(self, level: float):
#       """Лёгкое оживление орба без смены состояния."""
#       if self._state == "idle":
#           self.hud._activity_boost = level
#
# В SphereCore._tick():
#   # Activity boost: лёгкое ускорение в idle
#   if hasattr(self, '_activity_boost') and self._activity_boost > 0:
#       self._phase += 0.02 * self._activity_boost
#       self._activity_boost = max(0.0, self._activity_boost - 0.05)


# ── Watchdog (№20) ───────────────────────────────────────────────────

class Watchdog:
    """
    Следит за состоянием агента.
    Если WS-соединение пропало дольше RECONNECT_TIMEOUT — докладывает.
    Если TTS завис — перезапускает.

    Реализован как asyncio-задача, запускается в event loop агента.
    """

    RECONNECT_TIMEOUT = 120    # секунд офлайн → докладывать
    TTS_TIMEOUT       = 30     # секунд без конца TTS → считать зависшим
    CHECK_INTERVAL    = 15     # секунд между проверками

    def __init__(self, agent, bus):
        self._agent    = agent
        self._bus      = bus
        self._offline_since: float | None = None
        self._reported_offline = False
        self._tts_started: float | None   = None
        self._running  = True

    def on_connection_change(self, online: bool):
        if online:
            self._offline_since    = None
            self._reported_offline = False
        else:
            if self._offline_since is None:
                self._offline_since = time.monotonic()

    def on_tts_start(self):
        self._tts_started = time.monotonic()

    def on_tts_end(self):
        self._tts_started = None

    async def run(self):
        while self._running:
            await asyncio.sleep(self.CHECK_INTERVAL)
            self._check_connection()
            self._check_tts()

    def _check_connection(self):
        if self._offline_since is None:
            return
        offline_secs = time.monotonic() - self._offline_since
        if offline_secs > self.RECONNECT_TIMEOUT and not self._reported_offline:
            self._reported_offline = True
            mins = int(offline_secs // 60)
            log.warning(f"[watchdog] Офлайн уже {mins} минут — докладываю.")
            self._bus.emit("watchdog_alert",
                           message=f"Нет связи с Сакурой {mins} минут. Агент пробует переподключиться.")

    def _check_tts(self):
        if self._tts_started is None:
            return
        elapsed = time.monotonic() - self._tts_started
        if elapsed > self.TTS_TIMEOUT:
            log.warning(f"[watchdog] TTS завис ({elapsed:.0f}с) — сброс.")
            self._tts_started = None
            try:
                self._agent.player.flush()
                self._agent.set_state("idle")
            except Exception as e:
                log.error(f"[watchdog] Сброс TTS не удался: {e}")

    def start(self):
        """Запустить в asyncio event loop агента."""
        asyncio.create_task(self.run())
        log.info("[watchdog] Watchdog запущен.")


# ── Расширение system_info агента ────────────────────────────────────

def get_extended_system_info() -> dict:
    """
    Расширяет системные данные: добавляет температуры и место на диске.
    Вызывать из core/agent.py в _payload() вместо оригинального get_system_info().

    Требует psutil (уже в зависимостях).
    """
    try:
        import psutil

        # Базовые
        cpu  = psutil.cpu_percent(interval=0.1)
        ram  = psutil.virtual_memory().percent
        bat  = psutil.sensors_battery()
        battery = bat.percent if bat else None
        plugged = bat.power_plugged if bat else True

        # Диск (C:\ на Windows, / на Linux)
        try:
            import os
            disk_path = "C:\\" if os.name == "nt" else "/"
            disk = psutil.disk_usage(disk_path)
            disk_free_gb = disk.free / (1024 ** 3)
        except Exception:
            disk_free_gb = None

        # Температуры (Windows: требует LibreHardwareMonitor или WMI)
        cpu_temp = gpu_temp = None
        try:
            temps = psutil.sensors_temperatures()
            if temps:
                for name, entries in temps.items():
                    for e in entries:
                        if "cpu" in name.lower() or "core" in name.lower():
                            cpu_temp = max(cpu_temp or 0, e.current)
                        if "gpu" in name.lower() or "nvidia" in name.lower():
                            gpu_temp = max(gpu_temp or 0, e.current)
        except Exception:
            pass

        return {
            "cpu":         cpu,
            "ram":         ram,
            "battery":     battery,
            "plugged":     plugged,
            "cpu_temp":    round(cpu_temp, 1) if cpu_temp else None,
            "gpu_temp":    round(gpu_temp, 1) if gpu_temp else None,
            "disk_free":   round(disk_free_gb, 1) if disk_free_gb is not None else None,
        }

    except ImportError:
        return {}
    except Exception as e:
        log.debug(f"[presence] system_info error: {e}")
        return {}
