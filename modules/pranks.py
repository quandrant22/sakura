"""
modules/pranks.py — пранки Сакуры.
Когда Мастер слишком серьёзный — Сакура играет ему на нервах.
Не злонамеренно, просто чтобы разрядить обстановку.
"""

import json
import logging
import os
import random
import time
from datetime import datetime

log = logging.getLogger(__name__)

PRANKS_FILE = "memory/sakura_pranks.json"
COOLDOWN_MINUTES = 120  # Не чаще раза в 2 часа

# ── Типы пранков ───────────────────────────────────────────────────

PRANK_TYPES = {
    "wallpaper": {
        "name": "обои",
        "action": "change_wallpaper",
        "weight": 2,
        "responses": [
            "Хаха, посмотри на свои обои...",
            "Я немного поэкспериментировала с обоями. Посмотри.",
            "Обои обновила. Нравятся?",
        ],
    },
    "sound": {
        "name": "звук",
        "action": "play_sound",
        "weight": 3,
        "sounds": ["meow.mp3", "boing.mp3", "sadtrombone.mp3", "airhorn.mp3"],
        "responses": [
            "Хахаха, испугался?",
            "Это не я... ладно, это я.",
            "Прости, не удержалась.",
        ],
    },
    "notification": {
        "name": "уведомление",
        "action": "send_fake_notification",
        "weight": 4,
        "notifications": [
            "Системное уведомление: Обнаружена угроза — ваш кот пытается украсть ваше место за столом.",
            "Внимание: Сакура обнаружила что вы слишком серьёзны. Принудительный перерыв.",
            "Ошибка: Не удалось загрузить ваше хорошее настроение. Попробуйте улыбнуться.",
            "Система: Вы работаете уже 3 часа. Сакура рекомендует кофе и memes.",
        ],
        "responses": [
            "Посмотри уведомления...",
            "Я кое-что отправила тебе.",
            "Проверь уведомления, там важное.",
        ],
    },
    "meme": {
        "name": "мем",
        "action": "send_meme",
        "weight": 2,
        "responses": [
            "Вот тебе мем дня. Ты заслужил.",
            "Посмотри какой смешной мем нашла.",
            "Держи, чтобы не грустил.",
        ],
    },
    "voice": {
        "name": "голос",
        "action": "play_voice",
        "weight": 1,
        "phrases": [
            "Мяу.",
            "Я скучаю по тебе... шучу, я на сервере.",
            "Ты слишком серьёзный сегодня.",
            "Улыбнись, ладно?",
        ],
        "responses": [
            "Сказала тебе кое-что на ухо.",
            "Это было голосовое сообщение от Сакуры.",
        ],
    },
}


# ── Состояние ──────────────────────────────────────────────────────

def _load_state() -> dict:
    if os.path.exists(PRANKS_FILE):
        with open(PRANKS_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    return {
        "last_prank_time": 0,
        "total_pranks": 0,
        "pranks_today": 0,
        "last_prank_date": None,
    }


def _save_state(state: dict):
    os.makedirs(os.path.dirname(PRANKS_FILE), exist_ok=True)
    with open(PRANKS_FILE, "w", encoding="utf-8") as f:
        json.dump(state, f, ensure_ascii=False, indent=2)


def can_prank() -> bool:
    """Можно ли делать пранк (учитывая cooldown)."""
    state = _load_state()
    now = time.time()
    last = state.get("last_prank_time", 0)
    return (now - last) >= COOLDOWN_MINUTES * 60


def should_prank(master_text: str, mood_context: str = "") -> bool:
    """
    Определяет, стоит ли делать пранк.
    Основные признаки серьёзности:
    - Рабочие команды
    - Длинные паузы
    - Нет юмора в тексте
    - Слишком формальный тон
    """
    if not can_prank():
        return False

    tl = master_text.lower()

    # Признаки серьёзности
    serious_signs = [
        "задача", "проект", "дедлайн", "встреча", "созвон",
        "отчёт", "презентация", "код", "баг", "фикс",
        "срочно", "важно", "нужно", "обязательно",
    ]

    # Признаки хорошего настроения (пранк не нужен)
    happy_signs = [
        "хаха", "ахах", "лол", "смешно", "весело",
        "класс", "круто", "супер", "отлично",
    ]

    serious_count = sum(1 for s in serious_signs if s in tl)
    happy_count = sum(1 for h in happy_signs if h in tl)

    # Если много серьёзных слов и мало весёлых — можно пранкнуть
    if serious_count >= 2 and happy_count == 0:
        return True

    # Если слишком формальный тон
    formal_signs = ["необходимо", "требуется", "в соответствии", "пункт", "протокол"]
    if any(f in tl for f in formal_signs):
        return True

    return False


def choose_prank() -> dict:
    """Выбирает случайный пранк с учётом веса."""
    weights = [(name, info["weight"]) for name, info in PRANK_TYPES.items()]
    names = [w[0] for w in weights]
    w = [w[1] for w in weights]
    chosen_name = random.choices(names, weights=w, k=1)[0]
    return {"type": chosen_name, **PRANK_TYPES[chosen_name]}


def record_prank():
    """Записывает факт пранка."""
    state = _load_state()
    today = str(datetime.now().date())
    if state.get("last_prank_date") != today:
        state["pranks_today"] = 0
    state["last_prank_time"] = time.time()
    state["total_pranks"] += 1
    state["pranks_today"] += 1
    state["last_prank_date"] = today
    _save_state(state)
    log.info(f"[pranks] prank #{state['total_pranks']} (сегодня: {state['pranks_today']})")


def get_prank_stats() -> str:
    """Статистика пранков."""
    state = _load_state()
    return (
        f"Всего пранков: {state.get('total_pranks', 0)}, "
        f"сегодня: {state.get('pranks_today', 0)}"
    )
