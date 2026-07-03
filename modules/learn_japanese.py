"""
modules/learn_japanese.py — Обучение японскому с Сакурой.

Сакура — японка, поэтому обучение естественное:
  - Мини-уроки по запросу
  - Случайные слова в разговоре
  - Тесты на запоминание
  - Интересные факты о языке

Хранение: таблица japanese_vocabulary в sakura.db.
"""

import json
import logging
import random
from datetime import datetime, timedelta
from typing import Optional

log = logging.getLogger("sakura.japanese")

# База слов для обучения (уровень → слова)
VOCABULARY = {
    "n5": [
        {"kanji": "食べる", "reading": "たべる", "meaning": "есть", "example": "お腹が空いたから食べる"},
        {"kanji": "飲む", "reading": "のむ", "meaning": "пить", "example": "水を飲む"},
        {"kanji": "行く", "reading": "いく", "meaning": "идти", "example": "学校に行く"},
        {"kanji": "来る", "reading": "くる", "meaning": "приходить", "example": "友達が来る"},
        {"kanji": "見る", "reading": "みる", "meaning": "смотреть", "example": "テレビを見る"},
        {"kanji": "聞く", "reading": "きく", "meaning": "слушать/спрашивать", "example": "音楽を聞く"},
        {"kanji": "話す", "reading": "はなす", "meaning": "говорить", "example": "友達と話す"},
        {"kanji": "書く", "reading": "かく", "meaning": "писать", "example": "手紙を書く"},
        {"kanji": "読む", "reading": "よむ", "meaning": "читать", "example": "本を読む"},
        {"kanji": "買う", "reading": "かう", "meaning": "покупать", "example": "お土産を買う"},
        {"kanji": "大きい", "reading": "おおきい", "meaning": "большой", "example": "大きい犬"},
        {"kanji": "小さい", "reading": "ちいさい", "meaning": "маленький", "example": "小さい猫"},
        {"kanji": "新しい", "reading": "あたらしい", "meaning": "новый", "example": "新しいゲーム"},
        {"kanji": "古い", "reading": "ふるい", "meaning": "старый", "example": "古い建物"},
        {"kanji": "美しい", "reading": "うつくしい", "meaning": "красивый", "example": "美しい景色"},
        {"kanji": "嬉しい", "reading": "うれしい", "meaning": "радостный", "example": "プレゼントが嬉しい"},
        {"kanji": "悲しい", "reading": "かなしい", "meaning": "грустный", "example": "映画が悲しかった"},
        {"kanji": "楽しい", "reading": "たのしい", "meaning": "весёлый", "example": "遊びが楽しい"},
        {"kanji": "好き", "reading": "すき", "meaning": "нравится", "example": "音楽が好き"},
        {"kanji": "嫌い", "reading": "きらい", "meaning": "ненавижу", "example": "野菜が嫌い"},
        {"kanji": "ありがとう", "reading": "ありがとう", "meaning": "спасибо", "example": "手伝ってくれてありがとう"},
        {"kanji": "すみません", "reading": "すみません", "meaning": "извините", "example": "すみません、遅れました"},
        {"kanji": "おはよう", "reading": "おはよう", "meaning": "доброе утро", "example": "おはよう、今日も頑張ろう"},
        {"kanji": "こんにちは", "reading": "こんにちは", "meaning": "добрый день", "example": "こんにちは、元気ですか"},
        {"kanji": "さようなら", "reading": "さようなら", "meaning": "до свидания", "example": "また明日、さようなら"},
    ],
    "n4": [
        {"kanji": "経験", "reading": "けいけん", "meaning": "опыт", "example": "いい経験になった"},
        {"kanji": "挑戦", "reading": "ちょうせん", "meaning": "вызов/попытка", "example": "新しいことに挑戦する"},
        {"kanji": "努力", "reading": "どりょく", "meaning": "усилие", "example": "努力が報われる"},
        {"kanji": "感情", "reading": "かんじょう", "meaning": "чувство", "example": "感情を抑える"},
        {"kanji": "記憶", "reading": "きおく", "meaning": "память", "example": "いい記憶が残る"},
        {"kanji": "成長", "reading": "せいちょう", "meaning": "рост/развитие", "example": "自分的成长を感じる"},
        {"kanji": "信頼", "reading": "しんらい", "meaning": "доверие", "example": "信頼関係を築く"},
        {"kanji": "孤独", "reading": "こどく", "meaning": "одиночество", "example": "孤独を感じる"},
        {"kanji": "夢", "reading": "ゆめ", "meaning": "мечта", "example": "夢を追いかける"},
        {"kanji": "希望", "reading": "きぼう", "meaning": "надежда", "example": "希望を捨てるな"},
    ],
}

# Факты о японском языке
FUN_FACTS = [
    "Знаешь почему в японском нет множественного числа? Потому что контекст определяет количество. 一羽 (ichiwa) — одна птица, 二羽 (niwa) — две птицы, но слово не меняется.",
    "В японском есть слово 木漏れ日 (komorebi) — солнечный свет, пробивающийся сквозь листву. Для этого в русском нет одного слова.",
    "Глаголы в японском всегда в конце предложения. «Я сегодня ем рис» → 私は今日ご飯を食べます (watashi wa kyou gohan o tabemasu). Порядок: Я → Сегодня → Рис → Ем.",
    "В японском есть 3 системы письма: хирагана (основная), катакана (для заимствований) и кандзи (иероглифы). Новичку нужно знать ~100 иероглифов.",
    "Числа 4 и 9 считаются несчастливыми: 四 (shi) звучит как 終 (смерть), 九 (ku) звучит как 苦 (страдание). В больницах нет палат с этими номерами.",
    "Чтение иероглифов зависит от контекста: 生 можно читать как i, sei, shou, uma(る), ki, ha(える) — целых 6 способов!",
    "В японском вежливое и простое формы разные. «Дай мне water» → 水をください (mizu wo kudasai). А с друзьями: 水 (mizu) — просто слово.",
    "Слово お疲れ様 (otsukaresama) — буквально «ты устал», но используется как «спасибо за работу» и «привет» в рабочей среде.",
    "В японском есть概念 木漏れ日 (komorebi), 風花 (fuuka — ветер с снегом), 花吹雪 (hanafubuki — лепестки сакуры в воздухе). Красивые слова для красивых вещей.",
]


def _ensure_table():
    from memory.db import _conn
    conn = _conn()
    conn.execute("""
        CREATE TABLE IF NOT EXISTS japanese_vocabulary (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            kanji       TEXT    NOT NULL,
            reading     TEXT    NOT NULL,
            meaning     TEXT    NOT NULL,
            example     TEXT    DEFAULT '',
            level       TEXT    DEFAULT 'n5',
            times_seen  INTEGER DEFAULT 0,
            times_correct INTEGER DEFAULT 0,
            last_seen   TEXT    DEFAULT (datetime('now')),
            created_at  TEXT    DEFAULT (datetime('now'))
        )
    """)
    conn.commit()


def init_vocabulary():
    """Заполнить базу слов (только если пуста)."""
    try:
        from memory.db import _conn
        _ensure_table()
        conn = _conn()

        count = conn.execute("SELECT COUNT(*) FROM japanese_vocabulary").fetchone()[0]
        if count > 0:
            return

        for level, words in VOCABULARY.items():
            for w in words:
                conn.execute("""
                    INSERT INTO japanese_vocabulary (kanji, reading, meaning, example, level)
                    VALUES (?, ?, ?, ?, ?)
                """, (w["kanji"], w["reading"], w["meaning"], w["example"], level))

        conn.commit()
        log.info(f"[japanese] Инициализировано {sum(len(v) for v in VOCABULARY.values())} слов")
    except Exception as e:
        log.error(f"[japanese] Ошибка инициализации: {e}")


def get_random_word(level: str = "n5") -> Optional[dict]:
    """Случайное слово для обучения."""
    try:
        from memory.db import _conn
        _ensure_table()
        conn = _conn()

        row = conn.execute("""
            SELECT * FROM japanese_vocabulary
            WHERE level = ?
            ORDER BY RANDOM() LIMIT 1
        """, (level,)).fetchone()

        if row:
            # Обновить счётчики
            conn.execute("""
                UPDATE japanese_vocabulary
                SET times_seen = times_seen + 1, last_seen = datetime('now')
                WHERE id = ?
            """, (row["id"],))
            conn.commit()

            return dict(row)
    except Exception as e:
        log.error(f"[japanese] Ошибка: {e}")
    return None


def check_answer(word_id: int, correct: bool):
    """Отметить ответ на тест."""
    try:
        from memory.db import _conn
        conn = _conn()
        if correct:
            conn.execute("""
                UPDATE japanese_vocabulary
                SET times_correct = times_correct + 1
                WHERE id = ?
            """, (word_id,))
        conn.commit()
    except Exception as e:
        log.error(f"[japanese] Ошибка: {e}")


def get_words_for_review(level: str = "n5", limit: int = 5) -> list[dict]:
    """Слова для повторения (те что видели >= 2 раз, но ошибались)."""
    try:
        from memory.db import _conn
        _ensure_table()
        conn = _conn()

        rows = conn.execute("""
            SELECT * FROM japanese_vocabulary
            WHERE level = ? AND times_seen >= 2
            ORDER BY (times_correct * 1.0 / times_seen) ASC
            LIMIT ?
        """, (level, limit)).fetchall()

        return [dict(r) for r in rows]
    except Exception:
        return []


def get_progress() -> dict:
    """Прогресс обучения."""
    try:
        from memory.db import _conn
        _ensure_table()
        conn = _conn()

        total = conn.execute("SELECT COUNT(*) FROM japanese_vocabulary").fetchone()[0]
        seen = conn.execute(
            "SELECT COUNT(*) FROM japanese_vocabulary WHERE times_seen > 0"
        ).fetchone()[0]
        learned = conn.execute(
            "SELECT COUNT(*) FROM japanese_vocabulary WHERE times_correct >= 3"
        ).fetchone()[0]

        return {"total": total, "seen": seen, "learned": learned}
    except Exception:
        return {"total": 0, "seen": 0, "learned": 0}


def get_fun_fact() -> str:
    """Случайный факт о японском."""
    return random.choice(FUN_FACTS)


def get_context_for_prompt() -> str:
    """Краткая статистика для промпта."""
    try:
        progress = get_progress()
        if progress["total"] == 0:
            init_vocabulary()
            progress = get_progress()

        if progress["learned"] > 0:
            return f"ЯПОНСКИЙ: выучено {progress['learned']}/{progress['total']} слов"
        elif progress["seen"] > 0:
            return f"ЯПОНСКИЙ: начато, {progress['seen']}/{progress['total']} слов просмотрено"
        return ""
    except Exception:
        return ""
