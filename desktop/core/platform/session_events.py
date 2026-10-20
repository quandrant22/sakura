"""desktop.core.platform.session_events — выключение, перезагрузка и сон Windows для ядра.

Ядро — процесс без окон, поэтому заводит своё скрытое окно верхнего уровня (message-only окну
широковещательные WM_QUERYENDSESSION и WM_POWERBROADCAST не приходят) и в его потоке слушает:

  WM_QUERYENDSESSION / WM_ENDSESSION (wParam≠0) → "shutdown" (выключение, перезагрузка, выход из сеанса);
  WM_POWERBROADCAST PBT_APMSUSPEND               → "sleep";
  WM_POWERBROADCAST PBT_APMRESUMESUSPEND / PBT_APMRESUMEAUTOMATIC → "resume".

on_event(kind) зовётся в потоке окна и должен вернуться быстро (Windows ждёт ответа на
WM_QUERYENDSESSION несколько секунд): ядро отправляет bye не дольше секунды.
"""
import logging
import threading
import time

log = logging.getLogger("sakura.session")

WM_QUERYENDSESSION = 0x0011
WM_ENDSESSION = 0x0016
WM_POWERBROADCAST = 0x0218
PBT_APMSUSPEND = 0x0004
PBT_APMRESUMESUSPEND = 0x0007
PBT_APMRESUMEAUTOMATIC = 0x0012
REPEAT_S = 30.0   # то же событие чаще — повтор («запрос» и «конец» сеанса, два «пробуждения»)


def classify(msg: int, wparam: int) -> str | None:
    if msg == WM_QUERYENDSESSION or (msg == WM_ENDSESSION and wparam):
        return "shutdown"
    if msg == WM_POWERBROADCAST:
        if wparam == PBT_APMSUSPEND:
            return "sleep"
        if wparam in (PBT_APMRESUMESUSPEND, PBT_APMRESUMEAUTOMATIC):
            return "resume"
    return None


class SessionEvents(threading.Thread):
    def __init__(self, on_event, clock=time.monotonic):
        super().__init__(daemon=True, name="session-events")
        self.on_event = on_event
        self.clock = clock
        self._last: tuple[str, float] | None = None

    def handle(self, msg: int, wparam: int) -> None:
        """Сообщение окна → on_event; повтор того же события в течение REPEAT_S — один раз."""
        kind = classify(msg, wparam)
        if kind is None:
            return
        now = self.clock()
        if self._last and self._last[0] == kind and now - self._last[1] < REPEAT_S:
            return
        self._last = (kind, now)
        try:
            self.on_event(kind)
        except Exception:  # noqa: BLE001
            log.exception("[session] обработчик %s", kind)

    def _wndproc(self, hwnd, msg, wparam, lparam):
        import win32gui
        self.handle(msg, wparam)
        if msg in (WM_QUERYENDSESSION, WM_POWERBROADCAST):
            return True  # выключению и сну не мешаем
        return win32gui.DefWindowProc(hwnd, msg, wparam, lparam)

    def run(self):  # pragma: no cover — нужен рабочий стол Windows
        try:
            import win32api
            import win32gui
            wc = win32gui.WNDCLASS()
            wc.lpfnWndProc = self._wndproc
            wc.lpszClassName = "SakuraCoreSession"
            wc.hInstance = win32api.GetModuleHandle(None)
            atom = win32gui.RegisterClass(wc)
            # Окно верхнего уровня без WS_VISIBLE: невидимо, но широковещательные сообщения получает.
            win32gui.CreateWindowEx(0, atom, "Sakura core", 0, 0, 0, 0, 0, 0, 0, wc.hInstance, None)
            log.info("[session] слежу за выключением и сном")
            win32gui.PumpMessages()
        except Exception as e:  # noqa: BLE001
            log.warning("[session] выключение и сон не отслеживаются: %s", type(e).__name__)
