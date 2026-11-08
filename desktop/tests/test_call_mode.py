"""Тесты для desktop.core.call_mode"""

import pytest
from desktop.core.call_mode import CallModeManager


def test_call_mode_lifecycle_and_errand():
    said = []
    actions = []

    manager = CallModeManager(
        on_say_in_call=lambda t: said.append(t),
        on_action=lambda a, arg: actions.append((a, arg)),
    )

    manager.enable("Discord")
    assert manager.active is True

    # 1. User sets an errand
    manager.set_errand("launch_game", "Привет, мастер отошел на 5 минут, во что играем?")
    assert len(said) == 1
    assert "во что играем" in said[0]

    # 2. Friend speaks in voice
    prompt = manager.process_caller_speech("Dota 2")
    assert prompt is not None
    assert "Dota 2" in prompt
    assert manager.held_request is not None

    # 3. User confirms
    reply = manager.confirm_held_request(confirmed=True)
    assert "Dota 2" in reply
    assert len(actions) == 1
    assert actions[0][0] == "launch_game"
    assert actions[0][1]["game"] == "Dota 2"
