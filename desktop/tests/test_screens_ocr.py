"""Экран Сакуры (выбор монитора), координаты рисования, живой токен Яндекс.Музыки."""
from desktop.core import screens


def teardown_function():
    screens.set_target(None)
    screens._last_shot_size = None


def test_parse_target_rejects_garbage():
    assert screens.parse_target(None) is None
    assert screens.parse_target({"x": 0}) is None
    assert screens.parse_target({"x": 0, "y": 0, "width": 10, "height": 10}) is None
    b = screens.parse_target({"x": -1920, "y": 0, "width": 1920, "height": 1080, "id": 2})
    assert b and b.bbox == (-1920, 0, 0, 1080)


def test_grab_uses_selected_monitor():
    calls = []

    def fake(**kw):
        calls.append(kw)
        return "img"

    assert screens.grab(fake) == "img"
    assert calls[-1] == {"all_screens": False}
    screens.set_target({"x": 2560, "y": 0, "width": 1920, "height": 1080, "id": 5, "label": "Монитор 2"})
    screens.grab(fake)
    assert calls[-1] == {"bbox": (2560, 0, 4480, 1080), "all_screens": True}
    assert screens.describe()["label"] == "Монитор 2"


def test_ink_space_prefers_last_shot():
    assert screens.ink_space() == {"w": 0, "h": 0}
    screens.set_target({"x": 0, "y": 0, "width": 2560, "height": 1440})
    assert screens.ink_space() == {"w": 2560, "h": 1440}
    screens.note_shot_size(1280, 720)
    assert screens.ink_space() == {"w": 1280, "h": 720}


def test_ocr_unavailable_off_windows():
    import sys

    from desktop.core import ocr
    if sys.platform != "win32":
        assert ocr.recognize(object()) is None


def test_apply_ym_token_resets_client(monkeypatch):
    from desktop.core import config, music
    music._ym_client = object()
    music.apply_ym_token("  abc  ")
    assert config.YANDEX_MUSIC_TOKEN == "abc"
    assert music._ym_client is None
    assert music._ym_token() == "abc"
    music.apply_ym_token("")
