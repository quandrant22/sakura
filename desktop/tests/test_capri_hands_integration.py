"""Тест интеграции Capri-команд в desktop.core.hands.execute_command"""

import pytest
from desktop.core.hands import execute_command
from desktop.core.features import get_ink_manager, get_call_mode_manager, get_lookout_engine


def test_capri_commands_execution():
    # 1. Ink commands
    res_ink = execute_command("ink:circle 10 10 20 20")
    assert "нарисовала" in res_ink["result"]
    assert len(get_ink_manager().current_drawing.shapes) == 1

    res_clear = execute_command("clear_ink:")
    assert "стёрла" in res_clear["result"]
    assert len(get_ink_manager().current_drawing.shapes) == 0

    # 2. Call mode commands
    res_call_on = execute_command("call_mode:on")
    assert "включен" in res_call_on["result"]
    assert get_call_mode_manager().active is True

    res_call_off = execute_command("call_mode:off")
    assert "выключен" in res_call_off["result"]
    assert get_call_mode_manager().active is False

    # 3. Lookout commands
    res_lookout = execute_command("lookout:100% скачалось")
    assert "слежу" in res_lookout["result"]

    res_stop_lookout = execute_command("stop_watch:100%")
    assert "перестала" in res_stop_lookout["result"]

    # 4. Watch along commands
    res_watch = execute_command("watch_along:Cyberpunk")
    assert "смотрю" in res_watch["result"]

    res_stop_watch = execute_command("watch_along:stop")
    assert "остановлен" in res_stop_watch["result"]
