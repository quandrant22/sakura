import asyncio
import os
import sys
from types import SimpleNamespace

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from desktop.core import browser


def test_youtube_player_command_uses_agent_loop(monkeypatch):
    agent_loop = object()
    calls = {}
    response = {"ok": True, "result": "played"}

    async def send_command(action):
        calls["action"] = action
        return response

    class CompletedFuture:
        def __init__(self, result):
            self._result = result

        def result(self, timeout=None):
            calls["timeout"] = timeout
            return self._result

        def cancel(self):
            calls["cancelled"] = True

    def run_coroutine_threadsafe(coroutine, loop):
        calls["loop"] = loop
        return CompletedFuture(asyncio.run(coroutine))

    extension_server = SimpleNamespace(
        is_connected=lambda: True,
        _agent_loop=agent_loop,
        send_command=send_command,
    )
    monkeypatch.setitem(sys.modules, "desktop.core.extension_server", extension_server)
    monkeypatch.setattr(asyncio, "run_coroutine_threadsafe", run_coroutine_threadsafe)

    result = browser.youtube_player_cmd("youtube_volume_up")

    assert result == {"ok": True, "status": "done", "detail": "played"}
    assert calls["action"] == "youtube_volume_up"
    assert calls["loop"] is agent_loop


def _no_extension(monkeypatch, active_title=""):
    monkeypatch.setitem(sys.modules, "desktop.core.extension_server",
                        SimpleNamespace(is_connected=lambda: False))
    pressed = []
    monkeypatch.setattr(browser, "pyautogui", SimpleNamespace(press=pressed.append,
                        click=lambda *a, **k: pressed.append("CLICK")), raising=False)
    monkeypatch.setattr(browser, "HAS_PYAUTOGUI", True)
    from desktop.core import eyes
    monkeypatch.setattr(eyes, "get_active_window", lambda: active_title)
    return pressed


def test_without_extension_no_click_and_honest_refusal(monkeypatch):
    pressed = _no_extension(monkeypatch, "Видео - YouTube - Opera")
    r = browser.youtube_player_cmd("youtube_forward")
    assert r["ok"] is False and r["status"] == "unsupported" and "расширение" in r["detail"]
    like = browser.youtube_player_cmd("youtube_like")
    assert like["status"] == "unsupported" and "лайк" in like["detail"]
    assert pressed == []  # ни клавиш, ни клика мышью


def test_without_extension_pause_only_when_youtube_focused(monkeypatch):
    pressed = _no_extension(monkeypatch, "Документ — Блокнот")
    assert browser.youtube_player_cmd("youtube_pause")["status"] == "unsupported"
    assert pressed == []
    pressed = _no_extension(monkeypatch, "Видео - YouTube - Google Chrome")
    assert browser.youtube_player_cmd("youtube_pause")["ok"] is True
    assert pressed == ["k"]


def test_trending_opens_page(monkeypatch):
    opened = []
    monkeypatch.setattr(browser, "_open_url_background", opened.append)
    r = browser.youtube_player_cmd("youtube_trending")
    assert r["ok"] is True and opened == [browser.YOUTUBE_TRENDING_URL]
