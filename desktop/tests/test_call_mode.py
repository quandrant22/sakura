"""Тесты для desktop.core.call_mode"""

import pytest
from desktop.core.call_mode import CallModeManager


def test_call_mode_lifecycle_and_errand():
    said = []
    actions = []
    notifs = []

    manager = CallModeManager(
        on_say_in_call=lambda t: said.append(t),
        on_action=lambda a, arg: actions.append((a, arg)),
        on_notify=lambda title, text: notifs.append((title, text)),
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
    assert len(notifs) >= 1

    # 3. User confirms
    reply = manager.confirm_held_request(confirmed=True)
    assert "Dota 2" in reply
    assert len(actions) == 1
    assert actions[0][0] == "launch_game"
    assert actions[0][1]["game"] == "Dota 2"


def test_call_mode_caller_security_hold():
    said = []
    manager = CallModeManager(on_say_in_call=lambda t: said.append(t))
    manager.enable("Discord")

    # Friend attempts dangerous command
    prompt = manager.process_caller_speech("Сакура закрой игру немедленно")
    assert prompt is not None
    assert "Разрешить мастер" in prompt
    assert manager.held_request is not None
    assert manager.held_request.suggested_action == "system_command"

    # Master denies
    reject = manager.confirm_held_request(confirmed=False)
    assert "Отклонила" in reject
