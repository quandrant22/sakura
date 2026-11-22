import json
import os
import tempfile
import pytest

from desktop.core.game_hud.telemetry.registry import get_telemetry_provider
from desktop.core.game_hud.telemetry.scrap_mechanic import (
    ScrapMechanicTelemetryProvider,
    calculate_relative_navigation,
)


def test_relative_navigation():
    # Игрок в (0, 0, 0), смотрит на север (+Y: 0, 1, 0)
    # 1. Цель прямо впереди (0, 10, 0)
    dir_str, dist, h_str = calculate_relative_navigation(0, 0, 0, 0, 1, 0, 0, 10, 0)
    assert dir_str == "прямо"
    assert dist == 10.0
    assert h_str == "на этом этаже"

    # 2. Цель справа под 90 градусов (10, 0, 0)
    dir_str, dist, h_str = calculate_relative_navigation(0, 0, 0, 0, 1, 0, 10, 0, 0)
    assert dir_str == "направо на 90°"
    assert dist == 10.0

    # 3. Цель слева под 90 градусов (-10, 0, 0)
    dir_str, dist, h_str = calculate_relative_navigation(0, 0, 0, 0, 1, 0, -10, 0, 0)
    assert dir_str == "налево на 90°"
    assert dist == 10.0

    # 4. Цель сзади (0, -15, 0)
    dir_str, dist, h_str = calculate_relative_navigation(0, 0, 0, 0, 1, 0, 0, -15, 0)
    assert dir_str == "сзади"
    assert dist == 15.0

    # 5. Цель чуть правее (2, 8, 0)
    dir_str, dist, _ = calculate_relative_navigation(0, 0, 0, 0, 1, 0, 2, 8, 0)
    assert dir_str == "чуть правее"

    # 6. Цель чуть левее (-2, 8, 0)
    dir_str, dist, _ = calculate_relative_navigation(0, 0, 0, 0, 1, 0, -2, 8, 0)
    assert dir_str == "чуть левее"

    # 7. Высота: этажом выше / ниже
    _, _, h_up = calculate_relative_navigation(0, 0, 0, 0, 1, 0, 0, 5, 6)
    assert "выше" in h_up
    assert "6.0м" in h_up

    _, _, h_down = calculate_relative_navigation(0, 0, 0, 0, 1, 0, 0, 5, -8)
    assert "ниже" in h_down
    assert "8.0м" in h_down


def test_registry_scrap_mechanic():
    prov1 = get_telemetry_provider("scrapmechanic.exe")
    assert prov1 is not None
    assert isinstance(prov1, ScrapMechanicTelemetryProvider)

    prov2 = get_telemetry_provider("Scrap Mechanic")
    assert prov2 is not None
    assert prov2 is prov1


def test_provider_read_state_and_commands():
    with tempfile.TemporaryDirectory() as tmpdir:
        survival_dir = os.path.join(tmpdir, "Survival")
        os.makedirs(survival_dir, exist_ok=True)

        provider = ScrapMechanicTelemetryProvider(game_dir=tmpdir)

        # 1. Записываем фейковый sakura_state.json
        state_data = {
            "player": {
                "x": 10.0,
                "y": 20.0,
                "z": 5.0,
                "dir_x": 0.0,
                "dir_y": 1.0,
                "dir_z": 0.0,
                "hp": 85.0,
                "maxhp": 100.0,
                "breath": 90.0,
                "food": 70.0,
                "water": 80.0,
                "godmode": False,
                "world_id": 1,
            },
            "bags": [
                {
                    "x": 10.0,
                    "y": 35.0,
                    "z": 5.0,
                    "in_current_world": True,
                    "distance": 15.0,
                }
            ],
            "elevators": [
                {
                    "x": -10.0,
                    "y": 20.0,
                    "z": 5.0,
                    "in_current_world": True,
                    "distance": 20.0,
                }
            ],
            "nearby_bots": [
                {
                    "type": "Tapebot",
                    "x": 10.0,
                    "y": 28.0,
                    "z": 5.0,
                    "distance": 8.0,
                }
            ],
        }

        with open(provider.state_file_path, "w", encoding="utf-8") as f:
            json.dump(state_data, f)

        # Читаем состояние
        st = provider.get_state()
        assert st is not None
        assert st.game_id == "scrapmechanic"
        assert st.metrics["hp"] == 85.0
        assert st.metrics["bag_dir"] == "прямо"
        assert st.metrics["bag_dist"] == 15.0
        assert st.metrics["elevator_dir"] == "налево на 90°"
        assert st.metrics["elevator_dist"] == 20.0
        assert "Tapebot" in st.metrics["nearest_bot"]
        assert "Тейпбот" in st.metrics["bot_warning"]

        # 2. Отправка команд
        assert provider.tp_to_bag()
        with open(provider.cmd_file_path, "r", encoding="utf-8") as f:
            cmd_data = json.load(f)
        assert cmd_data["cmd"] == "tp_to_bag"
        assert cmd_data["processed"] is False

        assert provider.heal()
        with open(provider.cmd_file_path, "r", encoding="utf-8") as f:
            cmd_data = json.load(f)
        assert cmd_data["cmd"] == "heal"

        assert provider.godmode(True)
        with open(provider.cmd_file_path, "r", encoding="utf-8") as f:
            cmd_data = json.load(f)
        assert cmd_data["cmd"] == "godmode_on"

        assert provider.kill_nearby_bots()
        with open(provider.cmd_file_path, "r", encoding="utf-8") as f:
            cmd_data = json.load(f)
        assert cmd_data["cmd"] == "kill_nearby_bots"
        assert "cmd_id" in cmd_data


def test_provider_read_state_from_game_log():
    with tempfile.TemporaryDirectory() as tmpdir:
        logs_dir = os.path.join(tmpdir, "Logs")
        os.makedirs(logs_dir, exist_ok=True)

        provider = ScrapMechanicTelemetryProvider(game_dir=tmpdir)

        # Пишем фейковый game-20261122-200000.log с префиксом [SAKURA_STATE]
        log_file = os.path.join(logs_dir, "game-20261122-200000.log")
        payload = {
            "timestamp": 12345.67,
            "tick": 5000,
            "player": {
                "x": 50.0,
                "y": 60.0,
                "z": 10.0,
                "dir_x": 1.0,
                "dir_y": 0.0,
                "dir_z": 0.0,
                "hp": 99.0,
                "maxhp": 100.0,
                "breath": 100.0,
                "food": 100.0,
                "water": 100.0,
                "godmode": True,
                "world_id": 4,
            },
            "bags": [],
            "elevators": [],
            "nearby_bots": [],
        }
        with open(log_file, "w", encoding="utf-8") as f:
            f.write("20:00:00 (1/1) [Main:1444] Initializing...\n")
            f.write(f"20:00:01 (1/2) [UnnamedThread:1234] [Lua] [SAKURA_STATE] {json.dumps(payload)}\n")

        # Проверяем доступность и чтение
        assert provider.is_available() is True
        st = provider.get_state()
        assert st is not None
        assert st.metrics["hp"] == 99.0
        assert st.metrics["godmode"] is True
        assert st.metrics["player_x"] == 50.0



def test_hands_and_offline_intent():
    from desktop.core.agent import _legacy_action
    from desktop.core.hands import execute_command
    from desktop.core.offline_intent import OfflineIntents

    # 1. Legacy action mapping
    assert _legacy_action("scrap_mechanic.tp_bag") == "sm:tp_bag"
    assert _legacy_action("scrap_mechanic.heal") == "sm:heal"
    assert _legacy_action("scrap_mechanic.godmode_on") == "sm:godmode_on"

    # 2. Hands execution (mocked provider or live provider)
    res_heal = execute_command("sm:heal")
    assert "result" in res_heal

    res_god = execute_command("sm:godmode_on")
    assert "result" in res_god

    # 3. Offline intents match
    intents = OfflineIntents()
    match_bag = intents.match("телепортируй к вещам")
    assert match_bag is not None
    assert match_bag[0] == "scrap_mechanic.tp_bag"

    match_heal = intents.match("отхиль меня")
    assert match_heal is not None
    assert match_heal[0] == "scrap_mechanic.heal"

    match_god = intents.match("включи бессмертие")
    assert match_god is not None
    assert match_god[0] == "scrap_mechanic.godmode_on"

