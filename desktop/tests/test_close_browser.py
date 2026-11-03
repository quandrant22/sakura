"""close_window.браузер: окно браузера ищется по процессу и классу, а не по слову в заголовке."""
from types import SimpleNamespace

from desktop.core import hands, results
from desktop.core.platform.windows import pick_browser_window

WINDOWS = [  # порядок z-order: верхнее окно первым
    (1, "sakura-dev — Visual Studio Code", "Code.exe", "Chrome_WidgetWin_1"),   # Electron, не браузер
    (2, "Sakura", "electron.exe", "Chrome_WidgetWin_1"),
    (3, "", "chrome.exe", "Chrome_WidgetWin_1"),                                 # без заголовка — служебное
    (4, "Новости — Opera", "opera.exe", "Chrome_WidgetWin_1"),
    (5, "Почта — Google Chrome", "chrome.exe", "Chrome_WidgetWin_1"),
]


def test_pick_topmost_browser_by_process_and_class():
    assert pick_browser_window(WINDOWS) == (4, "Новости — Opera")
    assert pick_browser_window([(9, "Firefox", "firefox.exe", "MozillaWindowClass")]) == (9, "Firefox")


def test_electron_apps_are_not_browsers():
    assert pick_browser_window(WINDOWS[:3]) is None
    # процесс браузера, но чужой класс окна (например, диалог) — не закрываем
    assert pick_browser_window([(7, "Сохранить как", "chrome.exe", "#32770")]) is None


def test_execute_close_browser(monkeypatch):
    closed = []
    fake = SimpleNamespace(close_browser_window=lambda: closed.append(1) or "Новости — Opera")
    monkeypatch.setattr(hands, "get_platform", lambda: fake)
    out = results.from_legacy(hands.execute_command("close_window:браузер")["result"])
    assert out["ok"] is True and "Opera" in out["detail"] and closed == [1]

    monkeypatch.setattr(hands, "get_platform", lambda: SimpleNamespace(close_browser_window=lambda: None))
    out = results.from_legacy(hands.execute_command("close_window:браузер")["result"])
    assert out == {"ok": False, "status": "failed", "detail": "окно браузера не найдено"}
