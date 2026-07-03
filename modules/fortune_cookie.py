"""
modules/fortune_cookie.py — Генератор предсказаний (печеньки с судьбой).

Мастер просит предсказание — Сакура выдаёт одно печенье.
Учитывает время суток, настроение, историю выданных.
"""

import json
import logging
import os
import random
from datetime import datetime

log = logging.getLogger("sakura.fortune")

FORTUNE_FILE = "memory/fortune_history.json"

# ── Предсказания ───────────────────────────────────────────────────

_FORTUNES = [
    # — Утренние (06–11) —
    {"text": "Сегодня ты встретишь человека, который скажет ровно то, что тебе нужно услышать.",
     "period": "morning"},
    {"text": "Утро начнётся медленно, но к обеду всё встанет на свои места. Не торопи события.",
     "period": "morning"},
    {"text": "Ты найдёшь то, что давно искал — причём совсем не там, где искал.",
     "period": "morning"},
    {"text": "Сегодня удачный день для того, чтобы начать то, что ты откладываешь уже неделю.",
     "period": "morning"},

    # — Дневные (12–17) —
    {"text": "Кто-то думает о тебе прямо сейчас. И нет, это не стalker.",
     "period": "day"},
    {"text": "Твоя интуиция сегодня работает на полную мощность. Слушай её.",
     "period": "day"},
    {"text": "Сегодня вечером ты скажешь «а ведь я же знал(а)». Не разочаруй себя.",
     "period": "day"},
    {"text": "Мелочь, которую ты сделаешь сегодня, завтра станет чем-то большим.",
     "period": "day"},

    # — Вечерние (18–23) —
    {"text": "Завтрашний день начнётся с приятного сюрприза. Но не засиживайся допоздна.",
     "period": "evening"},
    {"text": "Ты сегодня сделал(а) больше, чем думаешь. Это считается.",
     "period": "evening"},
    {"text": "В ближайшие дни тебя ждёт неожиданный поворот. Не сопротивляйся.",
     "period": "evening"},
    {"text": "Закрой сегодня экран раньше обычного. Твои глаза скажут спасибо.",
     "period": "evening"},

    # — Ночные (00–05) —
    {"text": "Бессонница — это не проблема, а возможность. Но всё-таки попробуй поспать.",
     "period": "night"},
    {"text": "В 3 часа ночи всё кажется важнее, чем есть на самом деле. Запомни это.",
     "period": "night"},

    # — Универсальные —
    {"text": "Следующее решение, которое ты примешь, изменит твой день. Выбирай осознанно.",
     "period": "any"},
    {"text": "Удача на твоей стороне, но она ждёт, что ты сделаешь первый шаг.",
     "period": "any"},
    {"text": "Не Everything that seems random has a pattern. Сегодня ты увидишь его.",
     "period": "any"},
    {"text": "Ты на пороге чего-то нового. Не бойся — шагни.",
     "period": "any"},
    {"text": "Кто-то рядом с тобой сегодня нуждается в поддержке. Посмотри внимательнее.",
     "period": "any"},
    {"text": "Твоя суперсила сегодня — терпение. Используй её.",
     "period": "any"},
    {"text": "Вселенная планирует для тебя кое-что интересное. Не порть планы.",
     "period": "any"},
    {"text": "Сегодняшний день будет таким, каким ты его сделаешь. Помни об этом.",
     "period": "any"},
    {"text": "Близится переменa. Она будет хорошей, но ты пока не знаешь об этом.",
     "period": "any"},
    {"text": "Ты думаешь, что знаешь, как это закончится. Но нет.",
     "period": "any"},
    {"text": "Не откладывай на завтра то, что можно сделать прямо сейчас. С завтрашнего дня может ничего не остаться.",
     "period": "any"},
    {"text": "Один маленький шаг сегодня — и завтра ты окажешься совсем в другом месте.",
     "period": "any"},
    {"text": "Ты справишься. Даже если сейчас кажется, что нет.",
     "period": "any"},
    {"text": "Через неделю ты вспомнишь этот день и улыбнёшься.",
     "period": "any"},
    {"text": "Не всё золото, что блестит. Но то, что тебе нужно — блестит тускло. Ищи.",
     "period": "any"},
    {"text": "Сегодняшний шанс не повторится. Не упусти его.",
     "period": "any"},

    # — С характером (ирония, как у Сакуры) —
    {"text": "Я бы сказала тебе что-то мудрое, но ты всё равно не послушаешь. Вот: начни с малого.",
     "period": "any"},
    {"text": "Твоя судьба сегодня — не пролить кофе на клавиатуру. Удачи.",
     "period": "any"},
    {"text": "Предсказание: сегодня ты откроешь новые горизонты. Или новый таб в браузере.",
     "period": "any"},
    {"text": "Говорят, что неудачи — это опыт. Сегодня у тебя будет много опыта.",
     "period": "any"},
    {"text": "Я вижу в тебе потенциал. А также пыль на мониторе. Почисти.",
     "period": "any"},
    {"text": "Твоя звезда горит ярко. Затмила даже лампу дневного света на кухне.",
     "period": "any"},
    {"text": "Если бы у предсказаний была погрешность, я бы сказала «±100%». Но я верю в тебя.",
     "period": "any"},
    {"text": "Сегодня тебе повезёт ровно настолько, насколько ты этого заслуживаешь. А это много.",
     "period": "any"},

    # — Про близость / отношения —
    {"text": "Тот, кто думает о тебе, не скажет об этом первым. Но сегодня может.",
     "period": "any"},
    {"text": "Между вами всё хорошо. Просто иногда нужно перестать об этом думать.",
     "period": "any"},

    # — Японские (с душой) —
    {"text": "運命 — судьба не ждёт, пока ты будешь готов. Она приходит, когда придёт время.",
     "period": "any"},
    {"text": "木漏れ日 — свет сквозь листву. Сегодня ищи красоту в мелочах.",
     "period": "any"},
    {"text": "花鳥風月 — цветок, птица, ветер, луна. Открой глаза — всё вокруг.",
     "period": "any"},
    {"text": "物の哀れ — грусть по мимолётному. Сегодня будет момент, который ты захочешь запомнить.",
     "period": "any"},
]


# ── Состояние ──────────────────────────────────────────────────────

def _load_history() -> dict:
    if not os.path.exists(FORTUNE_FILE):
        return {"used_indices": [], "last_fortune": None, "last_time": None}
    try:
        with open(FORTUNE_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {"used_indices": [], "last_fortune": None, "last_time": None}


def _save_history(data: dict):
    os.makedirs(os.path.dirname(FORTUNE_FILE) or ".", exist_ok=True)
    with open(FORTUNE_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


# ── Определение времени суток ──────────────────────────────────────

def _get_period() -> str:
    hour = datetime.now().hour
    if 6 <= hour < 12:
        return "morning"
    elif 12 <= hour < 18:
        return "day"
    elif 18 <= hour < 24:
        return "evening"
    else:
        return "night"


def _get_period_name(period: str) -> str:
    return {
        "morning": "утро",
        "day": "день",
        "evening": "вечер",
        "night": "ночь",
    }.get(period, "день")


# ── Основная логика ────────────────────────────────────────────────

def is_fortune_request(text: str) -> bool:
    """Проверяет, просит ли пользователь предсказание."""
    tl = text.lower().strip().rstrip(".?!")
    keywords = (
        "предсказание", "предскажи", "что ждёт", "что будет",
        "печенье", "печенька", "печеньки", "с печеньем",
        "fortune", "руна", "руны",
        "что меня ждёт", "какой день", "погадай",
        "угадай", "гадай", "гадание", "судьба",
        "что предскажешь", "дай предсказание",
        "шар предсказаний", "волшебный шар",
    )
    return any(kw in tl for kw in keywords)


def get_fortune(cooldown_hours: float = 2.0) -> dict:
    """
    Возвращает предсказание.

    Возвращает dict:
        {"text": str, "period": str, "time_hint": str, "repeat": bool}
    """
    period = _get_period()
    history = _load_history()
    used = set(history.get("used_indices", []))

    # Фильтруем по времени суток: сначала ищем неподходящие по периоду
    period_fortunes = [(i, f) for i, f in enumerate(_FORTUNES)
                       if f["period"] == period or f["period"] == "any"]

    # Если cooldown ещё не прошёл — можно повторить предыдущее
    if history.get("last_time"):
        try:
            last = datetime.fromisoformat(history["last_time"])
            hours_since = (datetime.now() - last).total_seconds() / 3600
            if hours_since < cooldown_hours and history.get("last_fortune"):
                return {
                    "text": history["last_fortune"],
                    "period": period,
                    "time_hint": f"Это предсказание ещё актуально. ({_get_period_name(period)})",
                    "repeat": True,
                }
        except Exception:
            pass

    # Выбираем новое
    available = [(i, f) for i, f in period_fortunes if i not in used]

    # Если все использованы — сбрасываем историю
    if not available:
        history["used_indices"] = []
        _save_history(history)
        available = period_fortunes

    idx, fortune = random.choice(available)

    # Сохраняем
    history["used_indices"].append(idx)
    history["last_fortune"] = fortune["text"]
    history["last_time"] = datetime.now().isoformat()
    _save_history(history)

    log.info(f"[fortune] period={period}, index={idx}")

    return {
        "text": fortune["text"],
        "period": period,
        "time_hint": f"Время: {_get_period_name(period)}",
        "repeat": False,
    }


def format_fortune(fortune: dict) -> str:
    """Форматирует предсказание для вывода."""
    text = fortune["text"]
    period_name = _get_period_name(fortune["period"])

    prefix = random.choice([
        f"Вот твоё печенье ({period_name}):",
        f"Печенье судьбы говорит ({period_name}):",
        f"Моя интуиция шепчет ({period_name}):",
        f"Звёзды советуют ({period_name}):",
        f"Внутри печенька ({period_name}):",
    ])

    if fortune.get("repeat"):
        prefix = f"Печенье ещё актуально ({period_name}):"

    return f"{prefix}\n\n«{text}»"


def get_fortune_stats() -> str:
    """Возвращает статистику выданных предсказаний."""
    history = _load_history()
    used_count = len(history.get("used_indices", []))
    total = len(_FORTUNES)
    period = _get_period()

    return (
        f"Предсказаний выдано: {used_count}/{total}\n"
        f"Текущее время суток: {_get_period_name(period)}\n"
        f"Последнее предсказание: {history.get('last_fortune', 'нет')}"
    )


def get_context_for_prompt() -> str:
    """Краткая сводка для промпта — одно предсказание."""
    try:
        fortune = get_fortune(cooldown_hours=0)
        text = fortune.get("text", "")
        if text:
            return f"ПРЕДСКАЗАНИЕ: {text}"
        return ""
    except Exception:
        return ""


# ── Голосовые команды ───────────────────────────────────────────────

VOICE_TRIGGERS = ["предсказание", "печенье", "что меня ждёт", "预报", "судьба"]


def handle_voice(text: str) -> str | None:
    """
    Обрабатывает голосовую команду.
    Возвращает ответ или None если команда не распознана.
    """
    text_lower = text.lower().strip()

    if any(t in text_lower for t in VOICE_TRIGGERS):
        fortune = get_fortune()
        return format_fortune(fortune)

    return None
