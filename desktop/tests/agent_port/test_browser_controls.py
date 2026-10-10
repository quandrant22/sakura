import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

AGENT_ROOT = Path(__file__).resolve().parents[2]
if str(AGENT_ROOT) not in sys.path:
    sys.path.insert(0, str(AGENT_ROOT))

from desktop.core import browser


def test_find_opera_hwnd_returns_first_visible_opera(monkeypatch):
    windows = {10: (False, "Opera GX"), 11: (True, "Notepad"), 12: (True, "Opera GX")}

    def enum_windows(callback, _parameter):
        for hwnd in windows:
            callback(hwnd, None)

    gui = SimpleNamespace(
        IsWindowVisible=lambda hwnd: windows[hwnd][0],
        GetWindowText=lambda hwnd: windows[hwnd][1],
        EnumWindows=enum_windows,
    )
    monkeypatch.setattr(browser, "HAS_WIN32", True)
    monkeypatch.setattr(browser, "win32gui", gui, raising=False)

    assert browser._find_opera_hwnd() == 12


@pytest.mark.parametrize(
    ("command", "expected_text", "expected_keys"),
    [
        (browser.browser_tab_new, "новая вкладка", ("ctrl", "t")),
        (browser.browser_tab_close, "вкладка закрыта", ("ctrl", "w")),
        (browser.browser_tab_next, "следующая вкладка", ("ctrl", "tab")),
        (browser.browser_scroll_down, "прокрутила вниз", ("space",)),
        (browser.browser_back, "назад", ("alt", "left")),
        (browser.browser_forward, "вперёд", ("alt", "right")),
    ],
)
def test_browser_commands_dispatch_hotkeys(monkeypatch, command, expected_text, expected_keys):
    calls = []
    monkeypatch.setattr(browser, "_hotkey_bg", lambda *keys: calls.append(keys) or True)

    assert command() == expected_text
    assert calls == [expected_keys]


def test_browser_url_commands_use_background_opener(monkeypatch):
    opened = []
    monkeypatch.setattr(browser, "_open_url_background", lambda url: opened.append(url) or True)
    query = "Miyagi Эндшпиль"

    assert browser.browser_open_url("music.yandex.ru") == "открыла https://music.yandex.ru"
    assert browser.music_open() == "открыла Яндекс Музыку"
    assert browser.music_track(query) == f"ищу: {query}"

    assert opened == [
        "https://music.yandex.ru",
        browser.YANDEX_MUSIC_URL,
        f"{browser.YANDEX_MUSIC_URL}/search?text={browser.quote(query)}&type=all",
    ]


def test_music_media_commands_dispatch_media_keys(monkeypatch):
    keys = []
    monkeypatch.setattr(browser, "_media", lambda key: keys.append(key) or True)

    assert browser.music_play_pause() == "пауза/воспроизведение"
    assert browser.music_next() == "следующий трек"
    assert keys == [0xB3, 0xB0]