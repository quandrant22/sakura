"""Мелкие части ядра без тестов в старом агенте: config, dep_check, LocalMood,
список устройств вывода, Settings, EventBus."""
import importlib.util
import logging
import time
from pathlib import Path
from types import SimpleNamespace

import pytest

CONFIG = Path(__file__).resolve().parents[1] / "core" / "config.py"


def _load_config(monkeypatch, **env):
    for k in ("SAKURA_NO_DOTENV", "SAKURA_ENV_FILE", "SAKURA_DATA_DIR", "SAKURA_MODELS_DIR"):
        monkeypatch.delenv(k, raising=False)
    for k, v in env.items():
        monkeypatch.setenv(k, v)
    spec = importlib.util.spec_from_file_location("_cfg_under_test", CONFIG)
    cfg = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(cfg)
    return cfg


def test_config_env_file_override(monkeypatch, tmp_path):
    env = tmp_path / "custom.env"
    env.write_text("DEVICE_ID=from-env-file\nGIGAAM_MODEL=v3_e2e_ctc\n", encoding="utf-8")
    # load_dotenv(override=True) пишет в os.environ — заранее берём ключи под monkeypatch,
    # чтобы после теста они вернулись.
    monkeypatch.setenv("DEVICE_ID", "placeholder")
    monkeypatch.setenv("GIGAAM_MODEL", "placeholder")
    cfg = _load_config(monkeypatch, SAKURA_ENV_FILE=str(env))
    assert cfg.ENV_FILE == str(env)
    assert cfg.DEVICE_ID == "from-env-file" and cfg.GIGAAM_MODEL == "v3_e2e_ctc"


def test_config_no_dotenv_flag(monkeypatch, tmp_path):
    env = tmp_path / "x.env"
    env.write_text("DEVICE_ID=nope\n", encoding="utf-8")
    cfg = _load_config(monkeypatch, SAKURA_NO_DOTENV="1", SAKURA_ENV_FILE=str(env))
    assert cfg.ENV_FILE is None


def test_config_data_dir_and_models(monkeypatch, tmp_path):
    models = tmp_path / "models"
    (models / "vosk-model-small-ru-0.22").mkdir(parents=True)
    cfg = _load_config(monkeypatch, SAKURA_NO_DOTENV="1", SAKURA_DATA_DIR=str(tmp_path / "data"),
                       SAKURA_MODELS_DIR=str(models))
    assert cfg.DATA_DIR == str(tmp_path / "data")
    assert cfg.APPS_FILE.startswith(cfg.DATA_DIR) and cfg.LOG_DIR.startswith(cfg.DATA_DIR)
    assert cfg.VOSK_MODEL_PATH == str(models / "vosk-model-small-ru-0.22")
    assert Path(cfg.BASE_DIR, "command_packs").is_dir()


def test_dep_check_logs_missing(monkeypatch, caplog):
    from desktop.core import dep_check
    monkeypatch.setattr(dep_check, "_CRITICAL_PACKAGES",
                        [("definitely_not_a_module_xyz", "xyz", "проверка"), ("json", "json", "-")])
    with caplog.at_level(logging.WARNING):
        missing = dep_check.check_critical_packages(force=True)
    assert missing == ["definitely_not_a_module_xyz"]
    assert "definitely_not_a_module_xyz" in caplog.text
    assert dep_check.check_critical_packages() == []  # повторный вызов — no-op


def test_local_mood_params_shape_and_bounds():
    from desktop.core.local_mood import LocalMood
    m = LocalMood()
    for _ in range(5):
        m.update(track={"title": "x", "artist": "y"}, activity=0.9, cpu_temp=50)
    p = m.get_orb_params()
    assert {"pulse_amp", "petal_speed", "inner_weather"} <= set(p)
    cur = m.get_current()
    assert -1.0 <= cur["valence"] <= 1.0 and 0.0 <= cur["arousal"] <= 1.0
    assert m.get_color().startswith("#")


def test_list_output_devices_marks_default(monkeypatch):
    from desktop.core import voice
    fake = SimpleNamespace(
        default=SimpleNamespace(device=(0, 2)),
        query_devices=lambda: [{"name": "Mic", "max_output_channels": 0},
                               {"name": "HDMI", "max_output_channels": 2},
                               {"name": "Speakers", "max_output_channels": 2}])
    monkeypatch.setattr(voice, "sd", fake)
    out = voice.list_output_devices()
    assert "[1] HDMI" in out and "[2] Speakers <- ДЕФОЛТ" in out and "Mic" not in out


def test_settings_persist(tmp_path):
    from desktop.core.settings import Settings
    s = Settings(str(tmp_path / "s.json"))
    s.set("theme", "sakura-day")
    s.save()
    assert Settings(str(tmp_path / "s.json")).get("theme") == "sakura-day"


def test_event_bus_isolates_failing_subscriber():
    from desktop.core.events import EventBus
    bus, got = EventBus(), []
    bus.subscribe(lambda e, d: (_ for _ in ()).throw(RuntimeError("boom")))
    bus.subscribe(lambda e, d: got.append((e, d)))
    bus.emit("state", value="idle")
    assert got == [("state", {"value": "idle"})]


@pytest.mark.parametrize("n", [1])
def test_tasks_spawn_logs_exceptions(n, caplog):
    import asyncio

    from desktop.core.tasks import spawn

    async def boom():
        raise ValueError("x")

    async def go():
        spawn(boom(), name="t-boom")
        await asyncio.sleep(0.05)
    with caplog.at_level(logging.ERROR):
        asyncio.run(go())
        time.sleep(0.01)
    assert "t-boom" in caplog.text or "x" in caplog.text
