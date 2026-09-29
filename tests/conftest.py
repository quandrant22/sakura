"""Shared setup for smoke tests: env stubs, temp DB path, pytest markers."""
import os
import sys
import tempfile

import pytest

# Must run before any project imports
os.environ.setdefault("MASTER_ID", "123456789")
os.environ.setdefault("TELEGRAM_TOKEN", "123456789:AAHdqTcvCH1vGWJxfSeofSAs0K5PALDsaw")
os.environ.setdefault("GEMINI_KEY_1", "AIzaFakeKeyForTests1234567890")
os.environ.setdefault("WS_SECRET", "test-secret-minimum-16-chars")
os.environ.setdefault("MASTER_DEVICES", "laptop,pc")

# Put project root on sys.path
_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _root not in sys.path:
    sys.path.insert(0, _root)

# Point memory DB to a temp directory so we never touch the production DB
_tmpdir = tempfile.mkdtemp(prefix="sakura_test_")
os.environ["MEMORY_DB_PATH"] = os.path.join(_tmpdir, "test.db")


@pytest.fixture(scope="session", autouse=True)
def load_capability_tables():
    from sakura_core.bridge import _load_capabilities

    _load_capabilities()


@pytest.fixture(autouse=True)
def deterministic_model_configuration(monkeypatch):
    import config

    main_model = "gemini-3.5-flash-lite"
    fallback_model = "gemini-3.1-flash-lite"
    chain = (main_model, fallback_model)

    monkeypatch.setattr(config, "MAIN_MODEL", main_model)
    monkeypatch.setattr(config, "FALLBACK_MODEL", fallback_model)
    for setting in (
        "MODEL_CHAIN",
        "VOICE_MODEL_CHAIN",
        "BACKGROUND_MODEL_CHAIN",
        "VISION_MODEL_CHAIN",
    ):
        monkeypatch.setattr(config, setting, chain)

    monkeypatch.setattr(config, "VOICE_HISTORY_LIMIT", 10)
    monkeypatch.setattr(config, "CHAT_HISTORY_LIMIT", 30)
    monkeypatch.setattr(config, "VOICE_MAX_TOKENS", 120)
    monkeypatch.setattr(config, "VOICE_MAX_TOKENS_OVERRIDE", False)
