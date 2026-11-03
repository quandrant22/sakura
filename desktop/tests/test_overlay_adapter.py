"""Адаптер оверлея: события локального API → методы agent/ui/overlay.Overlay."""
import inspect
import json

import pytest

from desktop.overlay import adapter


@pytest.mark.parametrize("event,expected", [
    ({"type": "state", "value": "speaking"}, [("set_state", ("speaking",))]),
    ({"type": "chat_message", "message": {"role": "user", "text": "привет"}},
     [("add_user_message", ("привет",))]),
    ({"type": "chat_message", "message": {"role": "assistant", "text": "ага"}},
     [("add_sakura_message", ("ага",))]),
    ({"type": "chat_message", "message": {"role": "system", "text": "!"}},
     [("add_system_message", ("!",))]),
    ({"type": "connection", "server": "online"}, [("set_connected", (True,))]),
    ({"type": "connection", "server": "offline"}, [("set_connected", (False,))]),
    ({"type": "game_mode", "on": 1}, [("set_game_mode", (True,))]),
    ({"type": "notify", "text": "x"}, [("add_system_message", ("x",))]),
    ({"type": "orb_arrival"}, [("animate_arrival", ())]),
    ({"type": "orb_departure"}, [("animate_departure", ())]),
    ({"type": "audio_level", "bars": [0.1, 0.2]}, [("hud.set_audio_level", ([0.1, 0.2],))]),
    ({"type": "mood", "params": {"color": "#fff"}}, [("set_mood", ({"color": "#fff"},))]),
    ({"type": "transcript", "text": "x"}, []),
])
def test_route(event, expected):
    assert adapter.route(event) == expected


def test_routed_methods_exist_on_legacy_overlay():
    Overlay = adapter._import_legacy_overlay()
    from ui.overlay import SphereCore
    names = {"set_state", "add_user_message", "add_sakura_message", "add_system_message",
             "set_connected", "set_game_mode", "animate_arrival", "animate_departure", "set_mood"}
    for n in names:
        assert callable(getattr(Overlay, n)), n
    assert "submit" in dict(inspect.getmembers(Overlay))
    assert callable(SphereCore.set_audio_level)


def test_read_token_file(tmp_path):
    p = tmp_path / "ui.token"
    p.write_text(json.dumps({"port": 8790, "token": "abc"}), encoding="utf-8")
    assert adapter.read_token_file(str(p)) == (8790, "abc")
