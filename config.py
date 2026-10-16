from dotenv import load_dotenv
import os
import json
import time
import logging
from datetime import date

load_dotenv()

log = logging.getLogger(__name__)

TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
MASTER_ID      = int(os.getenv("MASTER_ID"))
HIMARI_ID      = int(os.getenv("HIMARI_ID", "0")) or None
GROUP_CHAT_ID  = int(os.getenv("GROUP_CHAT_ID", "0")) or None
UNSPLASH_KEY  = os.getenv("UNSPLASH_KEY", "")

# ── Координаты Мастера (для погоды) ───────────────────────────────
# Москва по умолчанию. Можно переопределить через .env
MASTER_LAT = float(os.getenv("MASTER_LAT", "55.7558"))
MASTER_LON = float(os.getenv("MASTER_LON", "37.6173"))
MASTER_CITY = os.getenv("MASTER_CITY", "Москва")

# ── Discord интеграция ────────────────────────────────────────────
DISCORD_TOKEN     = os.getenv("DISCORD_TOKEN", "")
DISCORD_MASTER_ID = os.getenv("DISCORD_MASTER_ID", "0")  # твой Discord user ID

# ── Steam интеграция (№28) ────────────────────────────────────────
# Получить: steamcommunity.com/dev/apikey
STEAM_KEY = os.getenv("STEAM_KEY", "")
# Твой Steam ID64 (steamid.io чтобы найти)
STEAM_ID  = os.getenv("STEAM_ID", "")

# ── WebSocket аутентификация (Фаза 0) ─────────────────────────────
# Генерация: python generate_token.py
WS_SECRET = os.getenv("WS_SECRET", "")
MASTER_DEVICES = set(
    d.strip() for d in os.getenv("MASTER_DEVICES", "laptop,pc").split(",") if d.strip()
)
CONFIRM_LISTEN_SEC = float(os.getenv("CONFIRM_LISTEN_SEC", "10"))
# Шлюз «классификатор ∥ голосовой стрим»: без вердикта дольше этого —
# считаем «не команда» (adapters/voice.py VoiceGate).
VOICE_GATE_WAIT_S = float(os.getenv("VOICE_GATE_WAIT_S", "4.0"))
# Голосовые подтверждения команд агента (modules/acks.py): включены,
# доля «сухих» реплик, через сколько без command_result сказать «Выполняю.».
# computer.do / computer_step (агент сам управляет компьютером по шагам):
# 1 — включено; по умолчанию выключено. До 20 шагов на задачу, кадр ≤ 400 КБ.
COMPUTER_USE = os.getenv("COMPUTER_USE", "0").strip().lower() in ("1", "true", "yes")
COMPUTER_MAX_STEPS = 20
COMPUTER_MAX_SHOT_BYTES = 400 * 1024
# Защищённый канал Noise поверх WebSocket (securechannel/, docs/security):
# off — только старый протокол (JSON + token); optional — Noise и токен;
# required — только Noise. Ключ сервера и реестр устройств — SECURE_DIR (600).
SECURE_CHANNEL = os.getenv("SECURE_CHANNEL", "off").strip().lower()
SECURE_DIR = os.getenv("SECURE_DIR", "memory/secure")
SECURE_BACKEND = os.getenv("SECURE_BACKEND", "lib").strip().lower()   # lib | edu
# Чат, история, память, профиль, кадры экрана — только по secure-соединению.
PRIVATE_REQUIRES_SECURE = os.getenv("PRIVATE_REQUIRES_SECURE", "1").strip().lower() not in ("0", "false", "no")
# Протокол v2 настольного клиента (sakura_core/proto_v2.py): 0 — сервер
# ведёт себя как v1 (нет registered, запросы v2 — error/unsupported).
PROTO_V2 = os.getenv("PROTO_V2", "1").strip().lower() not in ("0", "false", "no", "")
# Сторож зависшего голосового хода (sakura_core/voice_turns.py): не
# завершился за TURN_TIMEOUT_S — «Не получилось ответить, повтори» и
# tts_end; пока звук идёт (сообщения моложе TURN_ACTIVE_GRACE_S) — не
# зависание, но не дольше TURN_TIMEOUT_MAX_S. 0 — сторож выключен.
TURN_TIMEOUT_S = float(os.getenv("TURN_TIMEOUT_S", "30"))
TURN_ACTIVE_GRACE_S = 5.0
TURN_TIMEOUT_MAX_S = 120.0
# «на рабочем ноутбуке» в команде → это устройство (feat/pc-control).
WORK_LAPTOP_DEVICE = os.getenv("WORK_LAPTOP_DEVICE", "mostech").strip()
ACKS_ENABLED = os.getenv("ACKS_ENABLED", "1").strip().lower() not in ("0", "false", "no", "")
ACK_WIT_PROB = float(os.getenv("ACK_WIT_PROB", "0.1"))
ACK_PENDING_S = float(os.getenv("ACK_PENDING_S", "2.0"))
# Кэш озвученных фраз (modules/tts_cache.py), вне git.
TTS_CACHE_DIR = os.getenv("TTS_CACHE_DIR", "memory/tts_cache")

# ── perf/voice-2: скорость голосового ответа ─────────────────────────
def _flag(name: str, default: str) -> bool:
    return os.getenv(name, default).strip().lower() not in ("0", "false", "no", "")

# Предсинтез: стадия TTS синтезируется сразу, звук держится до вердикта.
VOICE_PRESYNTH = _flag("VOICE_PRESYNTH", "1")
# Ранний шлюз: вопрос без командных глаголов — звук не ждёт вердикта.
VOICE_EARLY_GATE = _flag("VOICE_EARLY_GATE", "1")
# Профиль системного промпта голоса: light — без тяжёлых контекстных
# блоков (персона не меняется; блоки возвращаются по словам запроса),
# full — как в чате. По умолчанию full, пока brain_eval --online не
# покажет, что light не хуже (docs/perf-voice-2.md).
VOICE_PROMPT_PROFILE = os.getenv("VOICE_PROMPT_PROFILE", "full").strip().lower()
# Предел длины голосового ответа (символов, по границе предложения); 0 — нет.
VOICE_MAX_CHARS = max(0, int(os.getenv("VOICE_MAX_CHARS", "320") or 0))
# Сводка [turn] p50/p90 — раз в столько секунд.
TURN_STATS_PERIOD_S = float(os.getenv("TURN_STATS_PERIOD_S", "3600"))

def _history_limit(name, default):
    try:
        return max(0, int(os.getenv(name, str(default))))
    except (TypeError, ValueError):
        log.warning("Invalid %s; using default %s", name, default)
        return default

VOICE_HISTORY_LIMIT = _history_limit("VOICE_HISTORY_LIMIT", 10)
CHAT_HISTORY_LIMIT = _history_limit("CHAT_HISTORY_LIMIT", 30)

# ── Основная текстовая LLM ────────────────────────────────────────
# ЕДИНАЯ точка задания основной модели для всего кода (main.py и modules/*).
# Переопределяется через .env: MAIN_MODEL=gemini-3.1-flash-lite
# НЕ трогать здесь: TTS Live API (modules/tts_server.py TTS_MODEL) и
# эмбеддинги — у них свои модели.
MAIN_MODEL     = os.getenv("MAIN_MODEL", "gemini-3.5-flash-lite")
FALLBACK_MODEL = os.getenv("FALLBACK_MODEL", "gemini-3.1-flash-lite")


def _parse_model_chain(name, default):
    value = os.getenv(name, "")
    configured = tuple(model.strip() for model in value.split(",") if model.strip())
    return tuple(dict.fromkeys(configured or default))


MODEL_CHAIN = _parse_model_chain("MODEL_CHAIN", (MAIN_MODEL, FALLBACK_MODEL))
VOICE_MODEL_CHAIN = _parse_model_chain("VOICE_MODEL_CHAIN", MODEL_CHAIN)
BACKGROUND_MODEL_CHAIN = _parse_model_chain("BACKGROUND_MODEL_CHAIN", MODEL_CHAIN)
VISION_MODEL_CHAIN = _parse_model_chain("VISION_MODEL_CHAIN", MODEL_CHAIN)

try:
    VOICE_MAX_TOKENS = max(1, int(os.getenv("VOICE_MAX_TOKENS", "120")))
except (TypeError, ValueError):
    log.warning("Invalid VOICE_MAX_TOKENS; using default 120")
    VOICE_MAX_TOKENS = 120
VOICE_MAX_TOKENS_OVERRIDE = "VOICE_MAX_TOKENS" in os.environ

# ── Поиск в интернете через Gemini Search grounding ─────────────────────
# Имя модели — по решению Мастера: gemini-2.5-flash (категория «Gemini 2.5»,
# квота 1.5K/день). НЕ менять на другое. ЖИВАЯ ПРОВЕРКА 2026-09: вызов с
# именованными аргументами доходит до API, но на обоих ключах пула Google
# отвечает 404 «models/gemini-2.5-flash is no longer available to new
# users» (модель числится в ListModels, но не обслуживается на этих
# аккаунтах). До изменения ситуации на стороне Google — честный отказ
# (ok=False). Переопределяется через .env: SEARCH_MODEL=...
SEARCH_MODEL = os.getenv("SEARCH_MODEL", "gemini-2.5-flash")

GEMINI_KEYS = []
i = 1
while True:
    key = os.getenv(f"GEMINI_KEY_{i}")
    if not key:
        break
    GEMINI_KEYS.append(key)
    i += 1

KEYS_FILE = "memory/api_keys.json"


def load_keys_state():
    if not os.path.exists(KEYS_FILE):
        state = {
            "keys":       [{"key": k, "used_today": 0, "exhausted": False, "cooldown_until": 0} for k in GEMINI_KEYS],
            "last_reset": str(date.today()),
        }
        save_keys_state(state)
        return state
    with open(KEYS_FILE, "r") as f:
        state = json.load(f)
    # Миграция: добавить cooldown_until если нет
    changed = False
    for k in state["keys"]:
        if "cooldown_until" not in k:
            k["cooldown_until"] = 0
            changed = True
    if changed:
        save_keys_state(state)
    return state


def save_keys_state(state):
    with open(KEYS_FILE, "w") as f:
        json.dump(state, f, indent=2)


def get_active_key():
    state = load_keys_state()
    now = time.time()
    if state["last_reset"] != str(date.today()):
        for k in state["keys"]:
            k["used_today"] = 0
            k["exhausted"]  = False
            k["cooldown_until"] = 0
        state["last_reset"] = str(date.today())
        save_keys_state(state)
    for k in state["keys"]:
        if not k["exhausted"] and now >= k.get("cooldown_until", 0):
            return k["key"]
    return None


def mark_key_used(key: str):
    if not key:
        return
    state = load_keys_state()
    for k in state["keys"]:
        if k["key"] == key:
            k["used_today"] += 1
    save_keys_state(state)


def mark_key_rate_limited(key: str, cooldown_seconds: int = 60):
    """Временная блокировка ключа при 429 — через cooldown_seconds снова доступен."""
    state = load_keys_state()
    for k in state["keys"]:
        if k["key"] == key:
            k["cooldown_until"] = time.time() + cooldown_seconds
            log.info(f"[keys] {key[:12]}... в cooldown {cooldown_seconds}с")
    save_keys_state(state)


def mark_key_exhausted(key: str):
    """Полная блокировка ключа (например, невалидный ключ). До следующего дня."""
    state = load_keys_state()
    for k in state["keys"]:
        if k["key"] == key:
            k["exhausted"] = True
    save_keys_state(state)


# Эпизоды «Выполнила команду: …» (executor) — служебный след, не память:
# 199 из 199 эпизодов были такими. 0 — не писать (по умолчанию).
EPISODES_LOG_COMMANDS = os.getenv("EPISODES_LOG_COMMANDS", "0").strip().lower() in ("1", "true", "yes")
