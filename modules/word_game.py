"""
modules/word_game.py — игры со словами: японский язык, объяснения, квизы.
Сакура учит японским словам в разговоре.
"""

import json
import logging
import os
import random
import time
from datetime import datetime

log = logging.getLogger(__name__)

WORDS_FILE = "memory/japanese_words.json"
SESSION_FILE = "memory/word_game_session.json"

# ── Словарь японских слов с объяснениями ───────────────────────────

JAPANESE_WORDS = [
    # Базовые фразы
    {"jp": "おはよう", "romaji": "ohayou", "ru": "Доброе утро", "category": "фразы",
     "note": "Неформальное. С друзьями, семьёй."},
    {"jp": "こんにちは", "romaji": "konnichiwa", "ru": "Здравствуйте", "category": "фразы",
     "note": "Днём. Универсальное приветствие."},
    {"jp": "ありがとう", "romaji": "arigatou", "ru": "Спасибо", "category": "фразы",
     "note": "Неформальное. Вежливо: arigatou gozaimasu."},
    {"jp": "すみません", "romaji": "sumimasen", "ru": "Извините / Простите", "category": "фразы",
     "note": "И «извините», и «простите», и «извините что беспокою»."},
    {"jp": "ごめんなさい", "romaji": "gomen nasai", "ru": "Прости", "category": "фразы",
     "note": "Более личное, чем sumimasen."},
    {"jp": "さようなら", "romaji": "sayounara", "ru": "До свидания", "category": "фразы",
     "note": "Надолго. С друзьями говорят «мата не» (またね)."},
    {"jp": "おやすみなさい", "romaji": "oyasumi nasai", "ru": "Спокойной ночи", "category": "фразы",
     "note": "Перед сном. Неформально: oyasumi."},
    {"jp": "はじめまして", "romaji": "hajimemashite", "ru": "Приятно познакомиться", "category": "фразы",
     "note": "Всегда в паре с «yoroshiku onegaishimasu»."},
    {"jp": "よろしくお願いします", "romaji": "yoroshiku onegaishimasu", "ru": "Прошу о сотрудничестве", "category": "фразы",
     "note": "Универсальное «будь добр». После знакомства."},
    {"jp": "いただきます", "romaji": "itadakimasu", "ru": "Приятного аппетита", "category": "фразы",
     "note": "Перед едой. Буквально «принимаю с благодарностью»."},
    {"jp": "ごちそうさまでした", "romaji": "gochisousama deshita", "ru": "Благодарю за трапезу", "category": "фразы",
     "note": "После еды. Буквально «это было угощением»."},
    {"jp": "がんばって", "romaji": "ganbatte", "ru": "Удачи! Держись!", "category": "фразы",
     "note": "Перед трудным делом. Универсальное пожелание."},
    {"jp": "ただいま", "romaji": "tadaima", "ru": "Я дома", "category": "фразы",
     "note": "Когда приходишь домой. Ответ: «okaerinasai» (с возвращением)."},
    {"jp": "いってきます", "romaji": "ittekimasu", "ru": "Я ухожу (до скорой встречи)", "category": "фразы",
     "note": "Когда уходишь из дома. Ответ: «itterasshai» (иди, бывай)."},

    # Природа
    {"jp": "桜", "romaji": "sakura", "ru": "Цветок вишни", "category": "природа",
     "note": "Символ Японии. Цветение сакуры — ханами (花見)."},
    {"jp": "空", "romaji": "sora", "ru": "Небо", "category": "природа",
     "note": "Часто в аниме и песнях."},
    {"jp": "海", "romaji": "umi", "ru": "Море", "category": "природа",
     "note": "Япония — островное государство, море везде."},
    {"jp": "山", "romaji": "yama", "ru": "Гора", "category": "природа",
     "note": "Фудзияма — символ Японии."},
    {"jp": "花", "romaji": "hana", "ru": "Цветок", "category": "природа",
     "note": "Hanami — любование цветами."},
    {"jp": "星", "romaji": "hoshi", "ru": "Звезда", "category": "природа",
     "note": "Хоси — также фамилия."},
    {"jp": "月", "romaji": "tsuki", "ru": "Луна", "category": "природа",
     "note": "Цуки-ями — любование луной."},
    {"jp": "雨", "romaji": "ame", "ru": "Дождь", "category": "природа",
     "note": "Амэ — также «конфета»."},
    {"jp": "雪", "romaji": "yuki", "ru": "Снег", "category": "природа",
     "note": "Юки-онна — снежная женщина из фольклора."},
    {"jp": "風", "romaji": "kaze", "ru": "Ветер", "category": "природа",
     "note": "Кадзэ — также фамилия."},
    {"jp": "火", "romaji": "hi", "ru": "Огонь", "category": "природа",
     "note": "Хикари — свет, хи — огонь."},
    {"jp": "水", "romaji": "mizu", "ru": "Вода", "category": "природа",
     "note": "Мидзу-дзёсуй — водопровод."},
    {"jp": "木", "romaji": "ki", "ru": "Дерево", "category": "природа",
     "note": "Также обозначает «дерево» как материал."},

    # Еда
    {"jp": "お茶", "romaji": "ocha", "ru": "Чай", "category": "еда",
     "note": "Японский чай — церемония чая (садо)."},
    {"jp": "ご飯", "romaji": "gohan", "ru": "Рис / Еда", "category": "еда",
     "note": "Гохан — также «обед», «ужин»."},
    {"jp": "魚", "romaji": "sakana", "ru": "Рыба", "category": "еда",
     "note": "Япония — страна рыбаков."},
    {"jp": "肉", "romaji": "niku", "ru": "Мясо", "category": "еда",
     "note": "Японцы едят мало мяса исторически."},
    {"jp": "寿司", "romaji": "sushi", "ru": "Суши", "category": "еда",
     "note": "Буквально «кислый рис». Изначально — консервирование."},

    # Чувства
    {"jp": "嬉しい", "romaji": "ureshii", "ru": "Я рад / Я счастлив", "category": "чувства",
     "note": "Урэсий — от сердца (урэси)."},
    {"jp": "悲しい", "romaji": "kanashii", "ru": "Я грустный", "category": "чувства",
     "note": "Канасий — глубокая грусть."},
    {"jp": "好き", "romaji": "suki", "ru": "Нравится / Люблю", "category": "чувства",
     "note": "Суки — мягче «аиситэру» (люблю)."},
    {"jp": "大好き", "romaji": "daisuki", "ru": "Очень люблю", "category": "чувства",
     "note": "Дай-суки — «большая любовь»."},
    {"jp": "愛してる", "romaji": "aishiteru", "ru": "Я тебя люблю", "category": "чувства",
     "note": "Говорят очень редко. Японцы стесняются."},
    {"jp": "会いたい", "romaji": "aitai", "ru": "Хочу тебя видеть", "category": "чувства",
     "note": "Аитай — тоска по кому-то."},
    {"jp": "可愛い", "romaji": "kawaii", "ru": "Милый / Милая", "category": "чувства",
     "note": "Кавай — культовый термин японской культуры."},
    {"jp": "すごい", "romaji": "sugoi", "ru": "Круто! Невероятно!", "category": "чувства",
     "note": "Сугой — универсальное восхищение."},
    {"jp": "酷い", "romaji": "hidoi", "ru": "Ужасно / Жестоко", "category": "чувства",
     "note": "Хидой — сильное негодование."},
    {"jp": "寂しい", "romaji": "sabishii", "ru": "Мне одиноко / скучно", "category": "чувства",
     "note": "Сабисий — одиночество."},
    {"jp": "恥ずかしい", "romaji": "hazukashii", "ru": "Мне стыдно", "category": "чувства",
     "note": "Хадзукэсий — смущение."},

    # Животные
    {"jp": "猫", "romaji": "neko", "ru": "Кошка", "category": "животные",
     "note": "Нэко-матэ — «маньяк кошек»."},
    {"jp": "犬", "romaji": "inu", "ru": "Собака", "category": "животные",
     "note": "Ину-моногатари — истории о собаках."},
    {"jp": "鳥", "romaji": "tori", "ru": "Птица", "category": "животные",
     "note": "Тори — также ворота синтоистского храма."},
    {"jp": "魚", "romaji": "uo", "ru": "Рыба (другое)", "category": "животные",
     "note": "Уо — разговорное."},

    # Дом и быт
    {"jp": "家", "romaji": "ie", "ru": "Дом", "category": "быт",
     "note": "Иэ — также «семья»."},
    {"jp": "部屋", "romaji": "heya", "ru": "Комната", "category": "быт",
     "note": "Хэйа — буквально «место для разговора»."},
    {"jp": "窓", "romaji": "mado", "ru": "Окно", "category": "быт",
     "note": "Мадо — также «дверь» в некоторых диалектах."},
    {"jp": "門", "romaji": "mon", "ru": "Ворота", "category": "быт",
     "note": "Мон — вход в храм, замок, парк."},

    # Время
    {"jp": "今日", "romaji": "kyou", "ru": "Сегодня", "category": "время",
     "note": "Кёу — также «сейчас»."},
    {"jp": "明日", "romaji": "ashita", "ru": "Завтра", "category": "время",
     "note": "Асита — также «утро» (аса)."},
    {"jp": "昨日", "romaji": "kinou", "ru": "Вчера", "category": "время",
     "note": "Киноу — также «вчерашний»."},
    {"jp": "今", "romaji": "ima", "ru": "Сейчас", "category": "время",
     "note": "Има — также «сейчас» в английском."},

    # Интересные слова
    {"jp": "木漏れ日", "romaji": "komorebi", "ru": "Свет через листву деревьев", "category": "красивые",
     "note": "Нет аналога в других языках. Одно из самых красивых слов."},
    {"jp": "花鳥風月", "romaji": "kachoufuugetsu", "ru": "Красота природы", "category": "красивые",
     "note": "Буквально: цветок, птица, ветер, луна. Эстетика природы."},
    {"jp": "物の哀れ", "romaji": "mono no aware", "ru": "Грусть по мимолётному", "category": "красивые",
     "note": "Ключевая концепция японской эстетики. Красота в увядании."},
    {"jp": "侘寂", "romaji": "wabi-sabi", "ru": "Красота в несовершенстве", "category": "красивые",
     "note": "Эстетика уединения и простоты. Треснувшая чашка."},
    {"jp": "木霊", "romaji": "kodama", "ru": "Эхо / Дух дерева", "category": "красивые",
     "note": "Кодама — духи деревьев в синтоизме."},
    {"jp": "夢", "romaji": "yume", "ru": "Сон / Мечта", "category": "красивые",
     "note": "Юмэ — и сон, и мечта одновременно."},
    {"jp": "運命", "romaji": "unmei", "ru": "Судьба", "category": "красивые",
     "note": "Унмей — то что предопределено."},
    {"jp": "絆", "romaji": "kizuna", "ru": "Связь / Узы", "category": "красивые",
     "note": "Кидзюна — невидимая связь между людьми."},
    {"jp": "切ない", "romaji": "setsunai", "ru": "Больно-сладко / Тоска", "category": "красивые",
     "note": "Сэцунай — нет аналога. Боль от красоты."},
    {"jp": "木枯らし", "romaji": "korogarashi", "ru": "Первый холодный ветер осени", "category": "красивые",
     "note": "Корогараси —seasonal wind. Осень."},
]


# ── Сессия игры ────────────────────────────────────────────────────

def _load_session() -> dict:
    if os.path.exists(SESSION_FILE):
        with open(SESSION_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    return {"active": False, "used_words": [], "score": 0, "started_at": None}


def _save_session(session: dict):
    os.makedirs(os.path.dirname(SESSION_FILE), exist_ok=True)
    with open(SESSION_FILE, "w", encoding="utf-8") as f:
        json.dump(session, f, ensure_ascii=False, indent=2)


# ── Парсинг команд ────────────────────────────────────────────────

def is_word_game_request(text: str) -> dict | None:
    """
    Проверяет, является ли текст запросом на игру в слова.
    Возвращает {"action": ...} или None.
    """
    tl = text.lower().strip()

    # "давай в слова" / "играй в слова" / "поиграем в слова"
    if any(w in tl for w in ("давай в слова", "играй в слова", "поиграем в слова",
                              "игра в слова", "игру в слова")):
        return {"action": "start_game"}

    # "придумай слово" / "новое слово" / "научи слову"
    if any(w in tl for w in ("придумай слово", "новое слово", "научи слову",
                              "японское слово", "слово на японском")):
        return {"action": "teach_word"}

    # "что значит X" / "как по-японски X"
    # (обрабатывается переводчиком, но можно перехватить и здесь)

    return None


# ── Логика игры ────────────────────────────────────────────────────

def start_game() -> str:
    """Начинает игру в слова."""
    session = _load_session()
    session["active"] = True
    session["used_words"] = []
    session["score"] = 0
    session["started_at"] = datetime.now().isoformat()
    _save_session(session)
    log.info("[word_game] started")
    return "Давай! Я буду учить тебя японским словам. Готов?"


def get_random_word(category: str = None) -> dict:
    """Возвращает случайное слово (не использованное в этой сессии)."""
    session = _load_session()
    used = set(session.get("used_words", []))

    candidates = JAPANESE_WORDS
    if category:
        candidates = [w for w in candidates if w["category"] == category]

    # Исключаем использованные
    available = [w for w in candidates if w["jp"] not in used]
    if not available:
        # Если все использованы — сброс
        session["used_words"] = []
        _save_session(session)
        available = candidates

    word = random.choice(available)

    # Запоминаем использование
    session["used_words"].append(word["jp"])
    _save_session(session)

    return word


def format_word_teach(word: dict) -> str:
    """Форматирует слово для обучения."""
    return (
        f"Новое слово: {word['jp']} ({word['romaji']})\n"
        f"Значение: {word['ru']}\n"
        f"Категория: {word['category']}\n"
        f"Примечание: {word['note']}"
    )


def format_word_quiz(word: dict) -> str:
    """Форматирует вопрос-викторину."""
    return (
        f"Угадай перевод: {word['jp']} ({word['romaji']})\n"
        f"Категория: {word['category']}\n"
        "Ответь одним словом на русском."
    )


def check_answer(user_text: str, word: dict) -> bool:
    """Проверяет ответ пользователя."""
    tl = user_text.lower().strip()
    target = word["ru"].lower()
    # Проверяем по ключевым словам из ответа
    target_words = target.split()
    return any(w in tl for w in target_words if len(w) > 2)


def record_score(correct: bool):
    """Записывает результат."""
    session = _load_session()
    if correct:
        session["score"] = session.get("score", 0) + 1
    _save_session(session)


def get_score() -> str:
    """Возвращает текущий счёт."""
    session = _load_session()
    score = session.get("score", 0)
    used = len(session.get("used_words", []))
    return f"Счёт: {score} из {used}. Слов изучено: {used}"


def end_game() -> str:
    """Завершает игру."""
    session = _load_session()
    score = session.get("score", 0)
    used = len(session.get("used_words", []))
    session["active"] = False
    _save_session(session)
    log.info(f"[word_game] ended: score={score}/{used}")
    return f"Игра окончена! Правильных ответов: {score} из {used}. Молодец!"


def is_game_active() -> bool:
    """Проверяет, активна ли игра."""
    session = _load_session()
    return session.get("active", False)


# ── Поиск по словарю ──────────────────────────────────────────────

def find_word(query: str) -> dict | None:
    """Ищет слово по запросу (японское или русское)."""
    q = query.lower().strip()
    for word in JAPANESE_WORDS:
        if q in word["jp"] or q in word["romaji"] or q in word["ru"].lower():
            return word
    return None


def get_word_of_the_day() -> dict:
    """Возвращает «слово дня» на основе даты."""
    today = datetime.now().day
    idx = today % len(JAPANESE_WORDS)
    return JAPANESE_WORDS[idx]


def format_word_of_the_day() -> str:
    """Форматирует слово дня."""
    word = get_word_of_the_day()
    return (
        f"Слово дня: {word['jp']} ({word['romaji']})\n"
        f"Значение: {word['ru']}\n"
        f"{word['note']}"
    )
