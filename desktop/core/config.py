"""desktop/core/config.py — все настройки ядра Сакуры в одном месте (порт agent/config.py).

Секреты берутся из .env (python-dotenv) или заданы здесь по умолчанию.
Единственное, что меняется между машинами — DEVICE_ID.

Где искать .env (первый найденный): SAKURA_ENV_FILE → desktop/.env → agent/.env
(пока новая версия не заменила agent/, оба используют один .env).
Данные (кэши приложений, индекс файлов, ключ чайника, settings.json) — в
SAKURA_DATA_DIR или %LOCALAPPDATA%\\Sakura.
"""

import os

from dotenv import load_dotenv

_HERE = os.path.dirname(os.path.abspath(__file__))
_DESKTOP_DIR = os.path.dirname(_HERE)
_REPO_DIR = os.path.dirname(_DESKTOP_DIR)
_AGENT_DIR = os.path.join(_REPO_DIR, "agent")


def _find_env_file() -> str | None:
    if os.getenv("SAKURA_NO_DOTENV"):  # тесты: настоящий .env не читаем
        return None
    for p in (os.getenv("SAKURA_ENV_FILE"), os.path.join(_DESKTOP_DIR, ".env"),
              os.path.join(_AGENT_DIR, ".env")):
        if p and os.path.isfile(p):
            return p
    return None


ENV_FILE = _find_env_file()
if ENV_FILE:
    load_dotenv(ENV_FILE, override=True)

# ── Подключение к VPS ───────────────────────────────────────────────
VPS_WS_URL   = os.getenv("VPS_WS_URL",   "ws://31.76.80.5:8765")
DEVICE_ID    = os.getenv("DEVICE_ID",     "laptop")
WS_TOKEN     = os.getenv("WS_TOKEN",      "")  # только из .env, без значения по умолчанию
PING_INTERVAL = int(os.getenv("PING_INTERVAL", "25"))
WINDOW_POLL   = int(os.getenv("WINDOW_POLL", "2"))
RECONNECT_SEC = int(os.getenv("RECONNECT_SEC", "3"))

# ── Аудио-выход (TTS) ───────────────────────────────────────────────
TTS_RATE  = int(os.getenv("TTS_RATE", "24000"))
TTS_SPEED = float(os.getenv("TTS_SPEED", "1.0"))
# Шаг «громче/тише» для музыки без числа, %
VOLUME_STEP = int(os.getenv("VOLUME_STEP", "10"))

# Предзаполнение плеера, мс звука до старта (0 — выключено)
PLAYER_PREROLL_MS = int(os.getenv("PLAYER_PREROLL_MS", "0"))

# Yandex SpeechKit (TTS) — опционально
YANDEX_API_KEY   = os.getenv("YANDEX_API_KEY", "")
YANDEX_FOLDER_ID = os.getenv("YANDEX_FOLDER_ID", "")
YANDEX_MUSIC_TOKEN = os.getenv("YANDEX_MUSIC_TOKEN", "")

# ── Локальный WS-сервер расширения браузера ─────────────────────────
# Агент занимает первый свободный порт из списка; расширение перебирает
# тот же список (agent/extension/background.js). Исторический 8766 может
# занять любая программа — VS Code держал его, и агент без паузы ретраил
# привязку каждые ~10 мс, сжигая ядро CPU. Переопределяется в .env:
#   EXTENSION_PORTS=8766,8767,8768,8769
EXTENSION_PORTS = tuple(
    int(p.strip())
    for p in os.getenv("EXTENSION_PORTS", "8766,8767,8768,8769").split(",")
    if p.strip()
)

# ── Пути ────────────────────────────────────────────────────────────
# BASE_DIR — ресурсы пакета (command_packs); DATA_DIR — изменяемые данные пользователя.
BASE_DIR  = _HERE
DATA_DIR  = os.getenv("SAKURA_DATA_DIR") or os.path.join(
    os.getenv("LOCALAPPDATA") or os.path.expanduser("~"), "Sakura")
LOG_DIR   = os.path.join(DATA_DIR, "logs")
APPS_FILE = os.path.join(DATA_DIR, "apps.json")

# Папки с играми
GAME_DIRS = [d.strip() for d in os.getenv("GAME_DIRS", r"C:\Games").split(";") if d.strip()]

# ── Wake word (Vosk) ────────────────────────────────────────────────
def _find_model(name: str) -> str:
    # Модели большие и не в git: ищем рядом с desktop/, затем в agent/ (уже скачана там).
    for d in (os.getenv("SAKURA_MODELS_DIR"), _DESKTOP_DIR, _AGENT_DIR):
        if d and os.path.isdir(os.path.join(d, name)):
            return os.path.join(d, name)
    return os.path.join(_DESKTOP_DIR, name)


VOSK_MODEL_PATH = _find_model("vosk-model-small-ru-0.22")
WAKE_WORDS      = ("сакура", "сакуру", "сакуре", "сакурой", "сакур", "sakura")

# ── Vosk STT (фолбэк, если GigaAM недоступен) ────────────────────────
VOSK_STT_MODEL  = os.getenv("VOSK_STT_MODEL", "vosk-model-small-ru-0.22")
if VOSK_STT_MODEL and not os.path.isabs(VOSK_STT_MODEL):
    VOSK_STT_MODEL = _find_model(VOSK_STT_MODEL)
VOSK_STT_RATE   = 16000

# ── GigaAM STT (основной; проверено вживую на машине Мастера) ───────
# pip install gigaam ставит torch<=2.5.1 (откатывает новее) — так и надо:
# Silero VAD на 2.5.1 работает, слух не ломается.
# Модель v2_ctc (~444 МБ, из кэша ~1.4с), ТОЛЬКО device='cpu'.
# transcribe() требует ffmpeg — НЕ использовать; аудио из памяти идёт
# прямым путём model.forward + decoding.decode (см. core/hearing.py).
# Откат на Vosk одной строкой в .env: STT_ENGINE=vosk
STT_ENGINE    = os.getenv("STT_ENGINE", "gigaam").strip().lower()  # gigaam | vosk
GIGAAM_MODEL  = os.getenv("GIGAAM_MODEL", "v2_ctc")
GIGAAM_DEVICE = os.getenv("GIGAAM_DEVICE", "cpu").strip().lower()  # НЕ cuda
# Легаси-переключатель (старый .env): GIGAAM_ENABLED=0 тоже отключает GigaAM.
GIGAAM_ENABLED = os.getenv("GIGAAM_ENABLED", "1").strip().lower() not in ("0", "false", "no", "off")

# ── Захват микрофона ────────────────────────────────────────────────
MIC_RATE        = 16000
MIC_BLOCK       = 512    # кадр для Silero VAD — менять нельзя
WAKE_BLOCK      = 1024   # блок цикла вейк-ворда: 64 мс звука вместо 32
MAX_UTTER_SEC   = 60
FOLLOWUP_SEC    = 4.0
VAD_THRESHOLD   = 0.45     # Снижен — ловит тихую речь в тихой комнате
VAD_END_SILENCE = 1.0      # Возврат к 1.0 — стабильнее для разговора
VAD_START_TIMEOUT = 2.0
# Короткая фраза («сделай потише») — конец по укороченной тишине:
# речь от начала VAD до последнего голосового кадра < VAD_SHORT_UTTER_SEC
VAD_END_SILENCE_SHORT = float(os.getenv("VAD_END_SILENCE_SHORT", "0.7"))
VAD_SHORT_UTTER_SEC   = float(os.getenv("VAD_SHORT_UTTER_SEC", "1.5"))

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
# «Уход» фокуса на другое устройство: до какой прозрачности гасить окно
# (1.0 — не затемнять) и сколько секунд без ввода нужно, чтобы гасить вообще.
OVERLAY_DEPARTURE_OPACITY = float(os.getenv("OVERLAY_DEPARTURE_OPACITY", "0.7"))
OVERLAY_DEPART_IDLE_S = float(os.getenv("OVERLAY_DEPART_IDLE_S", "120"))
# Непрозрачность фона панели, 0..255
OVERLAY_PANEL_ALPHA = int(os.getenv("OVERLAY_PANEL_ALPHA", "235"))

# ── Медиа (встроенные плееры, desktop/docs/media.md) ─────────────────
# Папки по умолчанию (через «;»); в интерфейсе меняются в Настройки → Медиа.
MUSIC_FOLDERS = [p.strip() for p in os.getenv("MUSIC_FOLDERS", "").split(";") if p.strip()]
VIDEO_FOLDERS = [p.strip() for p in os.getenv("VIDEO_FOLDERS", "").split(";") if p.strip()]
CROSSFADE_S = float(os.getenv("CROSSFADE_S", "0"))          # плавный переход между треками, с
PLAYER_DUCK_PCT = int(os.getenv("PLAYER_DUCK_PCT", "30"))   # громкость плееров, пока Сакура слушает/говорит
YOUTUBE_MODE = os.getenv("YOUTUBE_MODE", "embedded").strip().lower()  # embedded | remote
YOUTUBE_PROXY = os.getenv("YOUTUBE_PROXY", "").strip()      # прокси только для плеера YouTube
MUSIC_YANDEX = os.getenv("MUSIC_YANDEX", "0").strip().lower() in ("1", "true", "yes", "on")

# ── Аудио-устройство вывода ─────────────────────────────────────────
AUDIO_OUTPUT_DEVICE = os.getenv("AUDIO_OUTPUT_DEVICE", "default")

# ── Скриншот ────────────────────────────────────────────────────────
# Кадр смотрит Gemini Vision, а не человек, и все три промпта просят общее
# описание (что на экране / игра или нет / чем занят человек); название
# активного окна уходит в промпт текстом. Поэтому длинная сторона ужимается
# до 1280 — на 2К это ~70 КиБ вместо ~174 КиБ в обычном интерфейсе и ~43 КиБ
# вместо ~375 КиБ в тёмной игре. Полное 2К-разрешение даёт до ~2.6 МБ base64
# в одном WS-кадре, и пока он не дописан, голосовые команды стоят в очереди.
# Только вниз: экран меньше лимита не растягивается.
SCREENSHOT_MAX_SIDE  = int(os.getenv("SCREENSHOT_MAX_SIDE", "1280"))
SCREENSHOT_QUALITY   = int(os.getenv("SCREENSHOT_QUALITY", "70"))
