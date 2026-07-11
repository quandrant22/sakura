"""Shared setup for smoke tests: env stubs, temp DB path, pytest markers."""
import os
import sys
import tempfile

# Must run before any project imports
os.environ.setdefault("MASTER_ID", "123456789")
os.environ.setdefault("TELEGRAM_TOKEN", "test:fake-token")
os.environ.setdefault("GEMINI_KEY_1", "fake-gemini-key")
os.environ.setdefault("WS_SECRET", "test-secret-minimum-16-chars")
os.environ.setdefault("MASTER_DEVICES", "laptop,pc")

# Put project root on sys.path
_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _root not in sys.path:
    sys.path.insert(0, _root)

# Point memory DB to a temp directory so we never touch the production DB
_tmpdir = tempfile.mkdtemp(prefix="sakura_test_")
os.environ["MEMORY_DB_PATH"] = os.path.join(_tmpdir, "test.db")
