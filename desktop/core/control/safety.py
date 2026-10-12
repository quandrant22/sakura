"""Безопасность управления ПК: частота, журнал, чёрный список окон, белый список клавиш, процессы."""
import collections
import logging
import os
import time

log = logging.getLogger("sakura.actions")

RATE_PER_S = 5

# Окна, в которых ui.* и keys.* ничего не делают: менеджеры паролей, банки (WINDOW_BLOCKLIST дополняет).
DEFAULT_BLOCKLIST = ("keepass", "1password", "bitwarden", "lastpass", "dashlane", "enpass", "сбербанк",
                     "тинькофф", "т-банк", "альфа-банк", "втб онлайн", "credential", "пароль", "password")

# keys.hotkey — только эти сочетания (нижний регистр, «+» между клавишами).
HOTKEY_WHITELIST = frozenset({
    "ctrl+c", "ctrl+v", "ctrl+x", "ctrl+z", "ctrl+y", "ctrl+a", "ctrl+s", "ctrl+f",
    "alt+tab", "win+d", "win+tab", "printscreen", "ctrl+w", "ctrl+t", "ctrl+shift+t",
    "ctrl+add", "ctrl+subtract", "ctrl+0", "f5", "f11", "esc", "enter", "space",
})
# Синонимы клавиш → имена pyautogui.
KEY_ALIASES = {"control": "ctrl", "windows": "win", "prtsc": "printscreen", "print": "printscreen",
               "plus": "add", "minus": "subtract", "escape": "esc", "return": "enter"}

# process.kill никогда не трогает системные процессы и саму Сакуру.
PROTECTED_PROCESSES = frozenset({"system", "smss.exe", "csrss.exe", "wininit.exe", "winlogon.exe", "services.exe",
                                 "lsass.exe", "svchost.exe", "explorer.exe", "dwm.exe", "fontdrvhost.exe",
                                 "sakura.exe", "electron.exe"})


def blocklist() -> tuple[str, ...]:
    extra = tuple(s.strip().lower() for s in os.getenv("WINDOW_BLOCKLIST", "").split(",") if s.strip())
    return DEFAULT_BLOCKLIST + extra


def blocked_window(title: str, process: str = "") -> bool:
    text = f"{title} {process}".lower()
    return any(b in text for b in blocklist())


def normalize_hotkey(combo: str) -> str | None:
    """Сочетание из белого списка в виде для нажатия или None."""
    keys = [KEY_ALIASES.get(k, k) for k in (p.strip().lower() for p in combo.replace(" ", "").split("+")) if k]
    c = "+".join(keys)
    return c if c in HOTKEY_WHITELIST else None


class RateLimiter:
    """Не больше limit действий за window секунд."""

    def __init__(self, limit: int = RATE_PER_S, window: float = 1.0, clock=time.monotonic):
        self.limit, self.window, self.clock = limit, window, clock
        self._times: collections.deque = collections.deque()

    def allow(self) -> bool:
        now = self.clock()
        while self._times and now - self._times[0] >= self.window:
            self._times.popleft()
        if len(self._times) >= self.limit:
            return False
        self._times.append(now)
        return True


def journal(action: str, status: str) -> None:
    """Журнал действий: только id и итог — без текстов ввода, путей к файлам и изображений."""
    log.info("[action] %s → %s", action, status)
