"""config.py — все настройки агента Сакуры в одном месте.

Секреты берутся из .env (python-dotenv) или заданы здесь по умолчанию.
Единственное, что меняется между машинами — DEVICE_ID.
"""

import os
from dotenv import load_dotenv

load_dotenv(override=True)

# ── Подключение к VPS ───────────────────────────────────────────────
VPS_WS_URL   = os.getenv("VPS_WS_URL",   "ws://144.31.47.139:8765")
DEVICE_ID    = os.getenv("DEVICE_ID",     "laptop")
WS_TOKEN     = os.getenv("WS_TOKEN",      "ae89231d100bd2adf5981a079e2c7de8e5ae7c35dbfc58347ad30c97df69fe20")
PING_INTERVAL = int(os.getenv("PING_INTERVAL", "25"))
WINDOW_POLL   = int(os.getenv("WINDOW_POLL", "2"))
RECONNECT_SEC = int(os.getenv("RECONNECT_SEC", "3"))

# ── Аудио-выход (TTS) ───────────────────────────────────────────────
TTS_RATE  = int(os.getenv("TTS_RATE", "24000"))
TTS_SPEED = float(os.getenv("TTS_SPEED", "1.0"))

# Yandex SpeechKit (TTS) — опционально
YANDEX_API_KEY   = os.getenv("YANDEX_API_KEY", "")
YANDEX_FOLDER_ID = os.getenv("YANDEX_FOLDER_ID", "")

# ── Пути ────────────────────────────────────────────────────────────
BASE_DIR  = os.path.dirname(os.path.abspath(__file__))
APPS_FILE = os.path.join(BASE_DIR, "apps.json")

# Папки с играми
GAME_DIRS = [d.strip() for d in os.getenv("GAME_DIRS", r"C:\Games").split(";") if d.strip()]

# ── Wake word (Vosk) ────────────────────────────────────────────────
VOSK_MODEL_PATH = os.path.join(BASE_DIR, "vosk-model-small-ru-0.22")
WAKE_WORDS      = ("сакура", "сакуру", "сакуре", "сакурой", "сакур", "sakura")

# ── Vosk STT (основная модель для распознавания речи) ────────────────
VOSK_STT_MODEL  = os.getenv("VOSK_STT_MODEL", "vosk-model-ru-0.42")
VOSK_STT_RATE   = 16000

# ── Захват микрофона ────────────────────────────────────────────────
MIC_RATE        = 16000
MIC_BLOCK       = 512
MAX_UTTER_SEC   = 60
FOLLOWUP_SEC    = 4.0
VAD_THRESHOLD   = 0.45     # Снижен — ловит тихую речь в тихой комнате
VAD_END_SILENCE = 1.0      # Возврат к 1.0 — стабильнее для разговора
VAD_START_TIMEOUT = 2.0

# ── Распознавание речи (备用 — не используется, основное через Vosk) ───
# WHISPER_MODEL       = os.getenv("WHISPER_MODEL", "small")
# WHISPER_DEVICE      = os.getenv("WHISPER_DEVICE", "cpu")
# WHISPER_COMPUTE     = os.getenv("WHISPER_COMPUTE", "int8")
# WHISPER_IDLE_UNLOAD = int(os.getenv("WHISPER_IDLE_UNLOAD", "60"))
# WHISPER_PROMPT      = "Привет, как дела, хорошо, спасибо"

# ── Оверлей ─────────────────────────────────────────────────────────
OVERLAY_WIDTH  = int(os.getenv("OVERLAY_WIDTH", "360"))
OVERLAY_HEIGHT = int(os.getenv("OVERLAY_HEIGHT", "440"))
OVERLAY_MARGIN = int(os.getenv("OVERLAY_MARGIN", "24"))
TRANSCRIPT_MAX = int(os.getenv("TRANSCRIPT_MAX", "12"))

# ── Аудио-устройство вывода ─────────────────────────────────────────
AUDIO_OUTPUT_DEVICE = os.getenv("AUDIO_OUTPUT_DEVICE", "default")