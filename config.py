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