"""Общая настройка тестов desktop: без настоящего .env, данные во временной папке."""
import os
import sys
import tempfile
from pathlib import Path

# Корень репозитория: пакет desktop и серверный securechannel/ должны находиться
# и при запуске из папки desktop/, и в дочерних процессах тестов (PYTHONPATH).
_REPO_ROOT = str(Path(__file__).resolve().parents[2])
if _REPO_ROOT not in sys.path:
    sys.path.insert(0, _REPO_ROOT)
os.environ["PYTHONPATH"] = os.pathsep.join(
    p for p in (_REPO_ROOT, os.environ.get("PYTHONPATH", "")) if p)

# До любого импорта desktop.core.config.
os.environ["SAKURA_NO_DOTENV"] = "1"
os.environ.setdefault("WS_TOKEN", "test-token")
os.environ.setdefault("SAKURA_DATA_DIR", tempfile.mkdtemp(prefix="sakura-test-"))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
