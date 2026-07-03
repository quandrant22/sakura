"""Sakura Agent v2 — Python Executor

Handles Windows API integration: apps, browser, music, system commands.
Communicates with Rust core via stdin/stdout JSON protocol.
"""

import json
import logging
import os
import subprocess
import sys
import time
import threading
from dataclasses import dataclass, field
from typing import Any, Optional

log = logging.getLogger("sakura.executor")


@dataclass
class Event:
    """Event to send to Rust core."""
    type: str
    device_id: str = ""
    timestamp: float = 0.0
    text: str = ""
    action: str = ""
    result: str = ""
    success: bool = True
    screenshot: str = ""


@dataclass
class Action:
    """Action received from Rust core."""
    type: str
    target: str = ""
    args: str = ""
    audio: str = ""
    text: str = ""


class Executor:
    """Windows API executor."""

    def __init__(self):
        self._running = False
        self._thread: Optional[threading.Thread] = None

    def start(self):
        """Start the executor."""
        self._running = True
        self._thread = threading.Thread(target=self._loop, daemon=True)
        self._thread.start()
        log.info("Executor started")

    def stop(self):
        """Stop the executor."""
        self._running = False
        log.info("Executor stopped")

    def _loop(self):
        """Main executor loop."""
        while self._running:
            try:
                line = input()
                if not line:
                    continue

                action = Action(**json.loads(line))
                result = self.execute(action)
                self.send_result(result)
            except EOFError:
                break
            except Exception as e:
                log.error(f"Executor error: {e}")

    def execute(self, action: Action) -> dict:
        """Execute an action."""
        log.info(f"Executing: {action.target}:{action.args}")

        if action.target == "open_app":
            return self.open_app(action.args)
        elif action.target == "close_window":
            return self.close_window(action.args)
        elif action.target == "volume":
            return self.set_volume(int(action.args or 50))
        elif action.target == "volume_up":
            return self.nudge_volume(int(action.args or 20))
        elif action.target == "volume_down":
            return self.nudge_volume(-int(action.args or 20))
        elif action.target == "browser":
            return self.browser_command(action.args)
        elif action.target == "music":
            return self.music_command(action.args)
        elif action.target == "system":
            return self.system_command(action.args)
        elif action.target == "screenshot":
            return self.screenshot()
        else:
            return {"result": f"Unknown action: {action.target}"}

    def open_app(self, name: str) -> dict:
        """Open an application."""
        try:
            os.startfile(name)
            return {"result": f"Opened {name}"}
        except Exception as e:
            return {"result": f"Failed to open {name}: {e}"}

    def close_window(self, query: str) -> dict:
        """Close a window by title."""
        try:
            import win32gui, win32con
            def callback(hwnd, _):
                if win32gui.IsWindowVisible(hwnd):
                    title = win32gui.GetWindowText(hwnd)
                    if query.lower() in title.lower():
                        win32gui.PostMessage(hwnd, win32con.WM_CLOSE, 0, 0)
            win32gui.EnumWindows(callback, None)
            return {"result": f"Closed windows matching '{query}'"}
        except Exception as e:
            return {"result": f"Failed: {e}"}

    def set_volume(self, percent: int) -> dict:
        """Set system volume."""
        try:
            import comtypes
            from ctypes import cast, POINTER
            from comtypes import CLSCTX_ALL
            from pycaw.pycaw import AudioUtilities, IAudioEndpointVolume
            speakers = AudioUtilities.GetSpeakers()
            iface = speakers.Activate(IAudioEndpointVolume._iid_, CLSCTX_ALL, None)
            volume = cast(iface, POINTER(IAudioEndpointVolume))
            volume.SetMasterVolumeLevelScalar(max(0, min(100, percent)) / 100.0, None)
            return {"result": f"Volume {percent}%"}
        except Exception as e:
            return {"result": f"Volume error: {e}"}

    def nudge_volume(self, delta: int) -> dict:
        """Adjust volume by delta."""
        try:
            import comtypes
            from ctypes import cast, POINTER
            from comtypes import CLSCTX_ALL
            from pycaw.pycaw import AudioUtilities, IAudioEndpointVolume
            speakers = AudioUtilities.GetSpeakers()
            iface = speakers.Activate(IAudioEndpointVolume._iid_, CLSCTX_ALL, None)
            volume = cast(iface, POINTER(IAudioEndpointVolume))
            current = int(volume.GetMasterVolumeLevelScalar() * 100)
            new = max(0, min(100, current + delta))
            volume.SetMasterVolumeLevelScalar(new / 100.0, None)
            return {"result": f"Volume {new}%"}
        except Exception as e:
            return {"result": f"Volume error: {e}"}

    def browser_command(self, args: str) -> dict:
        """Execute browser command."""
        import ctypes
        try:
            if args == "tab_new":
                ctypes.windll.user32.keybd_event(0x74, 0, 0, 0)  # F5
                return {"result": "New tab"}
            elif args == "tab_close":
                # Ctrl+W
                ctypes.windll.user32.keybd_event(0x11, 0, 0, 0)
                ctypes.windll.user32.keybd_event(0x57, 0, 0, 0)
                ctypes.windll.user32.keybd_event(0x57, 0, 2, 0)
                ctypes.windll.user32.keybd_event(0x11, 0, 2, 0)
                return {"result": "Tab closed"}
            else:
                return {"result": f"Unknown browser command: {args}"}
        except Exception as e:
            return {"result": f"Browser error: {e}"}

    def music_command(self, args: str) -> dict:
        """Execute music command."""
        import ctypes
        try:
            if args == "play_pause":
                ctypes.windll.user32.keybd_event(0xB3, 0, 0, 0)
                return {"result": "Play/Pause"}
            elif args == "next":
                ctypes.windll.user32.keybd_event(0xB0, 0, 0, 0)
                return {"result": "Next track"}
            elif args == "prev":
                ctypes.windll.user32.keybd_event(0xB1, 0, 0, 0)
                return {"result": "Previous track"}
            else:
                return {"result": f"Unknown music command: {args}"}
        except Exception as e:
            return {"result": f"Music error: {e}"}

    def system_command(self, args: str) -> dict:
        """Execute system command."""
        try:
            if args == "lock":
                import ctypes
                ctypes.windll.user32.LockWorkStation()
                return {"result": "Locked"}
            elif args == "shutdown":
                subprocess.Popen(["shutdown", "/s", "/t", "30"])
                return {"result": "Shutdown in 30s"}
            elif args == "sleep":
                subprocess.Popen(["rundll32.exe", "powrprof.dll,SetSuspendState", "0,1,0"])
                return {"result": "Sleep mode"}
            else:
                return {"result": f"Unknown system command: {args}"}
        except Exception as e:
            return {"result": f"System error: {e}"}

    def screenshot(self) -> dict:
        """Take a screenshot."""
        try:
            from PIL import ImageGrab
            import base64
            import io
            buf = io.BytesIO()
            ImageGrab.grab().convert("RGB").save(buf, format="JPEG", quality=70)
            b64 = base64.b64encode(buf.getvalue()).decode()
            return {"result": "Screenshot taken", "screenshot": b64}
        except Exception as e:
            return {"result": f"Screenshot error: {e}"}

    def send_result(self, result: dict):
        """Send result to stdout."""
        event = Event(
            type="command_result",
            device_id=os.getenv("DEVICE_ID", "pc"),
            timestamp=time.time(),
            action=result.get("action", ""),
            result=result.get("result", ""),
            success=not result.get("error"),
            screenshot=result.get("screenshot", ""),
        )
        print(json.dumps({
            "type": event.type,
            "device_id": event.device_id,
            "timestamp": event.timestamp,
            "action": event.action,
            "result": event.result,
            "success": event.success,
            "screenshot": event.screenshot,
        }))
        sys.stdout.flush()


def main():
    """Main entry point."""
    logging.basicConfig(level=logging.INFO)

    executor = Executor()
    executor.start()

    try:
        while executor._running:
            time.sleep(1)
    except KeyboardInterrupt:
        executor.stop()


if __name__ == "__main__":
    main()
