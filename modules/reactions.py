"""
modules/reactions.py — эмоциональные реакции Сакуры.

Отправляет GIF/стикеры как реакции на сообщения Мастера.
Интегрирован с mood_vector — реакции учитывают настроение.
"""

import logging
import random
import time

log = logging.getLogger(__name__)

# ── Rate limiting ───────────────────────────────────────────────────

_last_reaction_time: float = 0.0
REACTION_COOLDOWN = 10  # секунд между реакциями

# ── GIF-реакции по эмоциям ─────────────────────────────────────────
# Используем надёжные источники: tenor, giphy, inline видео

REACTIONS = {
    "happy": {
        "trigger_words": [
            "хаха", "ахах", "лол", "смешно", "весело", "класс", "круто",
            "супер", "отлично", "здорово", "ура", "йес", "кайф",
        ],
        "gifs": [
            "https://media.tenor.com/lUNYI7D3bD8AAAAM/happy-cat.gif",
            "https://media.tenor.com/VDaMVlWnEdgAAAAM/anime-happy.gif",
            "https://media.tenor.com/rlYpHPFbqMcAAAAM/anime-cute.gif",
        ],
        "stickers": [],  # добавить file_id после настройки
        "emoji": "😄",
        "mood_filter": None,  # работает при любом настроении
    },
    "love": {
        "trigger_words": [
            "люблю", "любовь", "милая", "красавица", "сладкая", "дорогая",
            "обнимаю", "чмок", "сердечко", "милый",
        ],
        "gifs": [
            "https://media.tenor.com/LewQNHs3pGAAAAAM/anime-love.gif",
            "https://media.tenor.com/uGzYij9z0GkAAAAM/anime-kiss.gif",
            "https://media.tenor.com/6SfV3xOKFq0AAAAM/love-heart.gif",
        ],
        "stickers": [],
        "emoji": "❤️",
        "mood_filter": lambda v, a: v > 0.2,  # только в хорошем настроении
    },
    "surprise": {
        "trigger_words": [
            "ого", "вау", "неожиданно", "удивительно", "серьёзно",
            "неймоверно", "невероятно", "вауу",
        ],
        "gifs": [
            "https://media.tenor.com/3GhFZbqGfG0AAAAM/anime-surprised.gif",
            "https://media.tenor.com/sS4PNqnMiKYAAAAM/anime-shock.gif",
        ],
        "stickers": [],
        "emoji": "😮",
        "mood_filter": None,
    },
    "sad": {
        "trigger_words": [
            "грустно", "печально", "плохо", "устал", "тяжело", "сложно",
            "одиноко", "хуже", "сил нет",
        ],
        "gifs": [
            "https://media.tenor.com/RHfgHdEEqjkAAAAM/sad-anime.gif",
            "https://media.tenor.com/AQ7yw4YPvqsAAAAM/cry-anime.gif",
        ],
        "stickers": [],
        "emoji": "😢",
        "mood_filter": lambda v, a: v < 0.2,  # только когда грустно
    },
    "angry": {
        "trigger_words": [
            "злюсь", "бесит", "раздражает", "ненавижу", "хватит",
            "достало", "надоело",
        ],
        "gifs": [
            "https://media.tenor.com/l6U2VY0Q0q0AAAAM/anime-angry.gif",
        ],
        "stickers": [],
        "emoji": "😤",
        "mood_filter": None,
    },
    "playful": {
        "trigger_words": [
            "шучу", "пошутил", "дразню", "попался", "подкол", "тролль",
        ],
        "gifs": [
            "https://media.tenor.com/UxDQkH2U1-8AAAAM/anime-wink.gif",
            "https://media.tenor.com/xA0KBq6D3h0AAAAM/anime-smirk.gif",
        ],
        "stickers": [],
        "emoji": "😏",
        "mood_filter": lambda v, a: v > 0.1,
    },
    "confused": {
        "trigger_words": [
            "непонятно", "что?", "как?", "не понимаю", "странный",
            "запутался", "не ясно",
        ],
        "gifs": [
            "https://media.tenor.com/UkU8-irzqMAAAAAM/confused-anime.gif",
        ],
        "stickers": [],
        "emoji": "🤔",
        "mood_filter": None,
    },
    "tired": {
        "trigger_words": [
            "спать", "сон", "устал", "вырубаюсь", "доброй ночи",
            "спокойной", "ложусь", "отдыхаю",
        ],
        "gifs": [
            "https://media.tenor.com/ypq9WwOqMbYAAAAM/sleepy-anime.gif",
            "https://media.tenor.com/NxPDSMuqaQwAAAAM/yawn-anime.gif",
        ],
        "stickers": [],
        "emoji": "😴",
        "mood_filter": None,
    },
    "wave": {
        "trigger_words": [
            "привет", "здравствуй", "хай", "хей", "доброе утро",
            "добрый вечер", "приветик",
        ],
        "gifs": [
            "https://media.tenor.com/XfHkJ0MQc-0AAAAM/wave-anime.gif",
        ],
        "stickers": [],
        "emoji": "👋",
        "mood_filter": None,
    },
    "think": {
        "trigger_words": [
            "думаю", "интересно", "задумался", "вопрос", "мне кажется",
            "по-моему", "как думаешь",
        ],
        "gifs": [
            "https://media.tenor.com/5VwVhBBDj_QAAAAM/thinking-anime.gif",
        ],
        "stickers": [],
        "emoji": "💭",
        "mood_filter": None,
    },
}


def _check_cooldown() -> bool:
    """Проверяет кулдаун между реакциями."""
    global _last_reaction_time
    now = time.monotonic()
    if now - _last_reaction_time < REACTION_COOLDOWN:
        return False
    return True


def _mark_reaction():
    """Отмечает время последней реакции."""
    global _last_reaction_time
    _last_reaction_time = time.monotonic()


def detect_reaction(text: str, mood_valence: float = 0.0,
                    mood_arousal: float = 0.3) -> dict | None:
    """
    Определяет эмоциональную реакцию на текст с учётом настроения.

    text: сообщение пользователя
    mood_valence: текущий valence Сакуры (-1..+1)
    mood_arousal: текущий arousal Сакуры (0..1)

    Возвращает {"emotion": str, "gifs": list, "stickers": list, "emoji": str}
    или None если реакция не нужна.
    """
    if not _check_cooldown():
        return None

    tl = text.lower()
    candidates = []

    for emotion, data in REACTIONS.items():
        # Проверяем триггерные слова
        matched = False
        for word in data["trigger_words"]:
            if word in tl:
                matched = True
                break

        if not matched:
            continue

        # Проверяем mood filter
        mood_filter = data.get("mood_filter")
        if mood_filter and not mood_filter(mood_valence, mood_arousal):
            continue

        candidates.append({
            "emotion": emotion,
            "gifs": data["gifs"],
            "stickers": data.get("stickers", []),
            "emoji": data["emoji"],
        })

    if not candidates:
        return None

    # Выбираем случайную из кандидатов
    chosen = random.choice(candidates)
    _mark_reaction()
    return chosen


def get_random_gif(emotion: str) -> str | None:
    """Возвращает случайный GIF для эмоции."""
    data = REACTIONS.get(emotion)
    if data and data["gifs"]:
        return random.choice(data["gifs"])
    return None


def get_random_sticker(emotion: str) -> str | None:
    """Возвращает случайный sticker file_id для эмоции."""
    data = REACTIONS.get(emotion)
    stickers = data.get("stickers") if data else []
    if stickers:
        return random.choice(stickers)
    return None


def get_reaction_emoji(text: str) -> str | None:
    """Возвращает эмодзи-реакцию на текст."""
    reaction = detect_reaction(text)
    if reaction:
        return reaction["emoji"]
    return None


def should_react(text: str, mood_valence: float = 0.0,
                 mood_arousal: float = 0.3) -> bool:
    """
    Определяет, стоит ли реагировать на сообщение.
    Учитывает: настроение, кулдаун, длину сообщения, контекст.
    """
    if not _check_cooldown():
        return False

    # Не реагируем на очень короткие сообщения
    if len(text.strip()) < 5:
        return False

    # Не реагируем на команды (начинаются с глагола)
    cmd_starts = ("включи", "открой", "закрой", "сделай", "поставь",
                  "найди", "запусти", "выключи", "переключи")
    if any(text.lower().startswith(w) for w in cmd_starts):
        return False

    # Вероятность реакции зависит от настроения
    # Чем веселее — тем чаще реагирует
    base_prob = 0.25
    if mood_valence > 0.3:
        base_prob = 0.35
    elif mood_valence < -0.2:
        base_prob = 0.15

    return random.random() < base_prob
