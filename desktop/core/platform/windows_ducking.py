"""desktop.core.platform.windows_ducking — Windows Audio Ducking через pycaw.

Плавно приглушает внешние приложения при речи/слушании Сакуры:
- Музыка (Яндекс Музыка / браузерные плееры) — до DUCK_MUSIC_FACTOR (30% от текущей громкости)
- Активная игра (foreground window process) — до DUCK_GAME_FACTOR (55% от текущей громкости)
- Исключения: сама Сакура (текущий PID / python) и голосовые чаты (Discord, Telegram и др.)

Безопасность:
- Исходная громкость сохраняется ДО приглушения: orig_vol * factor
- Гарантированное восстановление в исходное состояние при отбое, ошибке и выходе из процесса (atexit)
"""

import atexit
import logging
import os
import threading
import time
from typing import Dict, Optional, Tuple

log = logging.getLogger("sakura.ducking")

# Ключевые слова музыкальных процессов
_MUSIC_PROCESS_KEYWORDS = (
    "yandex", "яндекс", "music", "spotify", "musicbee",
    "foobar2000", "aimp", "vlc", "wmplayer"
)

# Системные процессы Windows, которые никогда не считаются игрой
_SYSTEM_PROCESSES = frozenset({
    "explorer.exe", "dwm.exe", "taskmgr.exe", "svchost.exe",
    "shellexperiencehost.exe", "searchhost.exe", "startmenuexperiencehost.exe",
    "cmd.exe", "powershell.exe", "conhost.exe", "windowsterminal.exe"
})


class WindowsAudioDucker:
    """Управляет плавным приглушением громкости игр и музыки через WASAPI/pycaw."""

    def __init__(self):
        self._enabled = os.name == "nt"
        self._lock = threading.Lock()
        self._orig_volumes: Dict[int, float] = {}  # pid -> исходная громкость (0.0..1.0)
        self._current_factors: Dict[int, float] = {}  # pid -> текущий множитель
        self._target_ducked = False
        self._worker_thread: Optional[threading.Thread] = None
        self._wake_event = threading.Event()
        self._stop_event = threading.Event()

        if self._enabled:
            atexit.register(self.restore_all_sync)
            self._start_worker()

    def _start_worker(self):
        self._worker_thread = threading.Thread(
            target=self._ramp_loop,
            daemon=True,
            name="sakura-audio-ducking"
        )
        self._worker_thread.start()

    def set_voice_state(self, state: str):
        """Реакция на смену состояния Сакуры: speaking/listening -> duck, иначе -> unduck."""
        if not self._enabled:
            return
        should_duck = state in ("speaking", "listening")
        with self._lock:
            if self._target_ducked == should_duck:
                return
            self._target_ducked = should_duck
            self._wake_event.set()

    def restore_all_sync(self):
        """Синхронное экстренное восстановление всех уровней громкости (atexit/shutdown)."""
        if not self._enabled:
            return
        with self._lock:
            if not self._orig_volumes:
                return
            log.info("[ducking] Экстренное восстановление исходной громкости Windows-сессий...")
            try:
                import comtypes
                try: comtypes.CoInitialize()
                except Exception: pass
                from pycaw.pycaw import AudioUtilities
                sessions = AudioUtilities.GetAllSessions()
                for s in sessions:
                    pid = s.ProcessId
                    if pid and pid in self._orig_volumes and s.SimpleAudioVolume:
                        try:
                            s.SimpleAudioVolume.SetMasterVolume(self._orig_volumes[pid], None)
                        except Exception:
                            pass
            except Exception as e:
                log.debug(f"[ducking] restore_all_sync ошибка: {e}")
            finally:
                self._orig_volumes.clear()
                self._current_factors.clear()
                self._target_ducked = False

    def _get_foreground_process(self) -> Tuple[Optional[int], str]:
        """Возвращает (pid, process_name) активного переднего окна."""
        try:
            import win32gui
            import win32process
            import psutil
            hwnd = win32gui.GetForegroundWindow()
            if not hwnd:
                return None, ""
            _, pid = win32process.GetWindowThreadProcessId(hwnd)
            if pid:
                pname = psutil.Process(pid).name().lower()
                return pid, pname
        except Exception:
            pass
        return None, ""

    def _classify_session(self, pid: int, pname: str, fg_pid: Optional[int], fg_pname: str,
                           exclude_set: set) -> Optional[Tuple[str, float]]:
        """Определяет категорию сессии и множитель громкости: ('music', factor) или ('game', factor)."""
        from desktop.core import config
        current_pid = os.getpid()

        # 1. Исключения: текущий процесс Сакуры, Python и голосовые чаты
        if pid == current_pid or "python" in pname or pname in exclude_set:
            return None

        # 2. Музыкальное приложение
        if any(kw in pname for kw in _MUSIC_PROCESS_KEYWORDS):
            factor = getattr(config, "DUCK_MUSIC_FACTOR", 0.30)
            return ("music", factor)

        # 3. Активная игра: окно на переднем плане (если не системный процесс и не исключение)
        if fg_pid and pid == fg_pid and fg_pname not in _SYSTEM_PROCESSES:
            factor = getattr(config, "DUCK_GAME_FACTOR", 0.55)
            return ("game", factor)

        return None

    def _ramp_loop(self):
        """Фоновый цикл плавного изменения громкости (атака / возврат)."""
        import comtypes
        try:
            comtypes.CoInitialize()
        except Exception:
            pass

        while not self._stop_event.is_set():
            self._wake_event.wait(timeout=0.25)
            self._wake_event.clear()

            with self._lock:
                target_duck = self._target_ducked

            try:
                self._process_ramp(target_duck)
            except Exception as e:
                log.debug(f"[ducking] Ошибка в цикле приглушения: {e}")

    def _process_ramp(self, target_duck: bool):
        from desktop.core import config
        from pycaw.pycaw import AudioUtilities
        import psutil

        exclude_set = set(getattr(config, "DUCK_EXCLUDE_PROCESSES", (
            "discord.exe", "telegram.exe", "slack.exe", "zoom.exe", "teams.exe"
        )))

        fg_pid, fg_pname = self._get_foreground_process()
        sessions = AudioUtilities.GetAllSessions()

        # Кэш имён процессов по PID
        proc_names: Dict[int, str] = {}
        for s in sessions:
            pid = s.ProcessId
            if pid and pid not in proc_names:
                try:
                    proc_names[pid] = psutil.Process(pid).name().lower()
                except Exception:
                    proc_names[pid] = ""

        # Собираем целевые множители для сессий
        target_factors: Dict[int, float] = {}
        target_sessions = []

        for s in sessions:
            pid = s.ProcessId
            if not pid or not s.SimpleAudioVolume:
                continue
            pname = proc_names.get(pid, "")
            cls = self._classify_session(pid, pname, fg_pid, fg_pname, exclude_set)
            if cls is not None:
                category, factor = cls
                target_factors[pid] = factor if target_duck else 1.0
                target_sessions.append((pid, pname, s.SimpleAudioVolume, category))

        if not target_sessions and not self._orig_volumes:
            return

        with self._lock:
            # Сохраняем исходную громкость новых сессий ДО приглушения
            for pid, pname, sav, cat in target_sessions:
                if pid not in self._orig_volumes:
                    try:
                        cur_v = sav.GetMasterVolume()
                        self._orig_volumes[pid] = cur_v
                        self._current_factors[pid] = 1.0
                    except Exception:
                        pass

        # Параметры рампы
        attack_ms = getattr(config, "DUCK_ATTACK_MS", 120)
        release_ms = getattr(config, "DUCK_RELEASE_MS", 450)
        total_time_ms = attack_ms if target_duck else release_ms
        steps = max(3, total_time_ms // 30)
        step_dt = (total_time_ms / steps) / 1000.0

        for step in range(1, steps + 1):
            alpha = step / float(steps)
            with self._lock:
                if self._target_ducked != target_duck:
                    # Состояние изменилось посреди рампы — прерываемся и перенацеливаемся
                    break

                for pid, pname, sav, cat in target_sessions:
                    if pid not in self._orig_volumes:
                        continue
                    orig_v = self._orig_volumes[pid]
                    start_f = self._current_factors.get(pid, 1.0)
                    end_f = target_factors.get(pid, 1.0)
                    cur_f = start_f + (end_f - start_f) * alpha
                    self._current_factors[pid] = cur_f
                    new_vol = max(0.0, min(1.0, orig_v * cur_f))
                    try:
                        sav.SetMasterVolume(new_vol, None)
                    except Exception:
                        pass
            time.sleep(step_dt)

        with self._lock:
            if not target_duck and self._target_ducked == target_duck:
                # Полный возврат к 100% завершён — гарантированно восстанавливаем orig_vol и очищаем
                for pid, pname, sav, cat in target_sessions:
                    if pid in self._orig_volumes:
                        try:
                            sav.SetMasterVolume(self._orig_volumes[pid], None)
                        except Exception:
                            pass
                self._orig_volumes.clear()
                self._current_factors.clear()
