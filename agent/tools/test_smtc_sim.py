#!/usr/bin/env python3
"""Симуляция рабочего SMTC-пути с машины Мастера (без Windows).

Мокает winsdk так, чтобы request_async()/try_get_media_properties_async()
вели себя как настоящие IAsyncOperation (awaitable), и проверяет:
  - _yandex_smtc_session() находит 'Яндекс Музыка.exe', а не 'opera.exe';
  - now_playing() возвращает трек Яндекс Музыки (Bad Apple!!), а не ютуб;
  - _smtc_control уходит именно в сессию Яндекс Музыки.
"""
import asyncio
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))  # agent/
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__)))))  # корень репо (modules/translit)

MODULES = {}


class FakeAsyncOp:
    """Имитация winsdk IAsyncOperation: awaitable + блокирующий .get()."""

    def __init__(self, value):
        self._value = value

    def __await__(self):
        if False:
            yield  # pragma: no cover
        return self._value

    def get(self):
        return self._value


class FakeProps:
    def __init__(self, title, artist):
        self.title = title
        self.artist = artist
        self.album_title = "album"


class FakeSession:
    def __init__(self, aumid, title):
        self.source_app_user_model_id = aumid
        self._title = title
        self.control_calls = []

    def try_get_media_properties_async(self):
        return FakeAsyncOp(FakeProps(self._title, "Artist"))

    def get_playback_info(self):
        class PB:
            playback_status = 1
        return PB()

    def TryTogglePlayPauseAsync(self):
        self.control_calls.append("play_pause")
        return FakeAsyncOp(True)


class FakeManager:
    sessions = []

    @staticmethod
    async def request_async():
        class Mgr:
            def get_sessions(self_inner):
                return list(FakeManager.sessions)
        return Mgr()


def install_fake_winsdk():
    import types
    mod = types.ModuleType("winsdk")
    media = types.ModuleType("winsdk.windows")
    control = types.ModuleType("winsdk.windows.media")
    mc = types.ModuleType("winsdk.windows.media.control")
    mc.GlobalSystemMediaTransportControlsSessionManager = FakeManager
    mc.GlobalSystemMediaTransportControlsSessionPlaybackStatus = type(
        "Status", (), {"PLAYING": 1, "PAUSED": 2, "STOPPED": 3,
                       "CHANGING": 4, "CLOSED": 5})
    mod.windows = media
    media.media = control
    control.control = mc
    sys.modules.update({
        "winsdk": mod,
        "winsdk.windows": media,
        "winsdk.windows.media": control,
        "winsdk.windows.media.control": mc,
    })


def main():
    install_fake_winsdk()
    from core import yamusic_app as ym

    # Ровно как в выводе SMTC на машине Мастера: Opera с ютубом РЯДОМ
    opera = FakeSession("opera.exe", "ютуб-ролик")
    yamusic = FakeSession("Яндекс Музыка.exe", "Miku and Friends - Bad Apple!!")
    FakeManager.sessions = [opera, yamusic]

    s = ym._yandex_smtc_session()
    assert s is yamusic, f"Выбрана не та сессия: {getattr(s, 'source_app_user_model_id', None)}"

    info = ym.now_playing()
    assert info.get("title") == "Miku and Friends - Bad Apple!!", info
    assert info.get("status") == "играет", info

    ok = ym.play_pause()
    assert ok and opera.control_calls == [] and yamusic.control_calls == ["play_pause"], \
        (ok, opera.control_calls, yamusic.control_calls)

    assert ym.music_target() == "app"
    FakeManager.sessions = [opera]
    assert ym.now_playing() == {}
    assert ym.music_target() == "browser"
    FakeManager.sessions = []

    print("OK: сессия Яндекс Музыки найдена (кириллический AUMID), "
          "play/pause ушёл в неё, Opera не тронута.")


if __name__ == "__main__":
    main()
