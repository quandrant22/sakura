"""Общая настройка тестов desktop: без настоящего .env, данные во временной папке."""
import os
import tempfile

# До любого импорта desktop.core.config.
os.environ["SAKURA_NO_DOTENV"] = "1"
os.environ.setdefault("WS_TOKEN", "test-token")
os.environ.setdefault("SAKURA_DATA_DIR", tempfile.mkdtemp(prefix="sakura-test-"))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
