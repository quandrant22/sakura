"""desktop.core.ink — Экранные чернила (Screen Ink / Визуальная указка).

Позволяет Сакуре рисовать поверх экрана любые векторные фигуры,
пометки, стрелки, текст и контуры с эффектом киберпанк-неона (#FF2A85).
Поддерживает рисование абсолютно любых запросов пользователя без цензуры и морализаторства.
"""

from __future__ import annotations

import logging
import re
import time
from dataclasses import dataclass, field
from typing import Any, Callable, Optional

log = logging.getLogger("sakura.ink")

_DEFAULT_COLOR = "#FF2A85"  # Неоновый розовый стиль Сакуры

# ══════════════════════════════════════════════════════════════════════════════
# БИБЛИОТЕКА НЕОНОВЫХ ВЕКТОРНЫХ ФИГУР (viewBox 0 0 100 100)
# ══════════════════════════════════════════════════════════════════════════════
SHAPES_100: dict[str, tuple[str, str, str]] = {
    # key: (svg_path, display_label, emoji)
    "heart": (
        "M 50,85 C 10,60 0,35 15,18 C 30,2 45,15 50,28 C 55,15 70,2 85,18 C 100,35 90,60 50,85 Z",
        "сердечко",
        "❤️",
    ),
    "star": (
        "M 50,5 L 62,35 L 95,38 L 70,60 L 77,93 L 50,76 L 23,93 L 30,60 L 5,38 L 38,35 Z",
        "звезду",
        "⭐",
    ),
    "cat": (
        "M 25,75 C 20,70 18,55 20,40 L 20,20 L 38,32 C 45,30 55,30 62,32 L 80,20 L 80,40 C 82,55 80,70 75,75 C 65,85 35,85 25,75 Z M 35,50 A 4,6 0 1,0 35,50.1 M 65,50 A 4,6 0 1,0 65,50.1 M 50,62 L 46,58 L 54,58 Z M 50,62 Q 45,68 40,65 M 50,62 Q 55,68 60,65",
        "котика",
        "🐱",
    ),
    "dog": (
        "M 30,30 L 20,50 L 30,60 L 35,50 C 40,48 60,48 65,50 L 70,60 L 80,50 L 70,30 C 65,22 35,22 30,30 Z M 38,42 A 4,4 0 1,0 38,42.1 M 62,42 A 4,4 0 1,0 62,42.1 M 50,55 A 5,4 0 1,0 50,55.1 M 50,60 L 50,68 M 50,68 Q 42,75 38,70 M 50,68 Q 58,75 62,70",
        "собаку",
        "🐶",
    ),
    "skull": (
        "M 25,45 C 25,25 35,15 50,15 C 65,15 75,25 75,45 C 75,55 70,62 65,65 L 65,75 C 65,78 62,80 58,80 L 42,80 C 38,80 35,78 35,75 L 35,65 C 30,62 25,55 25,45 Z M 40,45 A 6,8 0 1,0 40,45.1 M 60,45 A 6,8 0 1,0 60,45.1 M 48,60 L 52,60 L 50,55 Z M 42,72 L 42,78 M 50,72 L 50,78 M 58,72 L 58,78 M 15,20 L 85,85 M 85,20 L 15,85",
        "череп",
        "💀",
    ),
    "sword": (
        "M 50,5 L 54,15 L 53,68 L 70,68 L 70,74 L 53,74 L 53,88 L 56,92 L 50,96 L 44,92 L 47,88 L 47,74 L 30,74 L 30,68 L 47,68 L 46,15 Z M 50,10 L 50,68",
        "меч",
        "⚔️",
    ),
    "gun": (
        "M 15,35 L 75,35 L 75,48 L 58,48 L 52,58 L 62,80 C 60,84 54,84 50,82 L 42,65 L 45,48 L 35,48 L 35,55 L 28,55 L 28,48 L 15,48 Z M 70,30 L 75,30 L 75,35 L 70,35 Z",
        "пистолет",
        "🔫",
    ),
    "dragon": (
        "M 20,40 Q 30,20 50,15 Q 60,5 75,10 Q 65,22 85,25 Q 92,30 82,38 Q 65,35 60,45 Q 80,48 78,55 Q 60,52 48,60 Q 55,75 45,88 Q 40,78 35,82 Q 38,68 32,65 Q 22,72 18,65 Q 28,55 20,40 Z M 68,24 A 2.5,2.5 0 1,0 68,24.1",
        "дракона",
        "🐉",
    ),
    "dick": (
        "M 42,75 C 32,75 25,65 28,52 C 30,42 40,44 42,52 L 42,28 C 42,20 46,14 50,14 C 54,14 58,20 58,28 L 58,52 C 60,44 70,42 72,52 C 75,65 68,75 58,75 C 55,75 52,70 50,65 C 48,70 45,75 42,75 Z M 47,18 L 53,18",
        "член",
        "🍆",
    ),
    "boobs": (
        "M 15,65 C 15,45 28,35 40,45 C 48,52 50,55 50,55 C 50,55 52,52 60,45 C 72,35 85,45 85,65 C 85,75 75,82 65,80 C 55,78 50,70 50,70 C 50,70 45,78 35,80 C 25,82 15,75 15,65 Z M 36,58 A 3,3 0 1,0 36,58.1 M 64,58 A 3,3 0 1,0 64,58.1",
        "грудь",
        "👙",
    ),
    "fuck": (
        "M 32,82 L 32,60 C 32,55 35,52 38,55 L 38,45 C 38,40 42,38 45,42 L 45,20 C 45,13 52,13 52,20 L 52,48 C 55,44 60,46 60,50 L 60,54 C 63,50 68,52 68,58 L 68,82 Z",
        "средний палец",
        "🖕",
    ),
    "lightning": (
        "M 55,5 L 25,48 L 46,48 L 38,95 L 75,42 L 54,42 Z",
        "молнию",
        "⚡",
    ),
    "fire": (
        "M 50,10 C 60,30 80,42 80,65 C 80,82 66,95 50,95 C 34,95 20,82 20,65 C 20,48 30,35 42,25 C 42,40 48,45 52,38 C 55,32 52,22 50,10 Z",
        "огонь",
        "🔥",
    ),
    "crown": (
        "M 15,75 L 18,35 L 35,52 L 50,22 L 65,52 L 82,35 L 85,75 Z M 15,75 L 85,75 L 85,82 L 15,82 Z",
        "корону",
        "👑",
    ),
    "ghost": (
        "M 25,85 L 25,45 C 25,25 35,15 50,15 C 65,15 75,25 75,45 L 75,85 Q 68,78 62,85 Q 56,78 50,85 Q 44,78 38,85 Q 31,78 25,85 Z M 40,42 A 4,6 0 1,0 40,42.1 M 60,42 A 4,6 0 1,0 60,42.1 M 48,58 Q 50,64 52,58",
        "привидение",
        "👻",
    ),
    "diamond": (
        "M 50,92 L 15,40 L 30,15 L 70,15 L 85,40 Z M 15,40 L 85,40 M 30,15 L 50,40 L 70,15 M 50,40 L 50,92",
        "алмаз",
        "💎",
    ),
    "car": (
        "M 10,65 L 12,55 Q 16,48 28,48 L 38,30 Q 42,25 50,25 L 70,25 Q 78,32 82,48 L 92,52 Q 95,55 95,65 L 90,65 A 10,10 0 0,1 70,65 L 40,65 A 10,10 0 0,1 20,65 Z M 30,65 A 6,6 0 1,0 30,65.1 M 80,65 A 6,6 0 1,0 80,65.1 M 40,32 L 68,32 L 72,46 L 36,46 Z",
        "машину",
        "🚗",
    ),
    "rocket": (
        "M 50,10 Q 65,30 65,65 L 78,75 L 68,78 L 62,70 L 38,70 L 32,78 L 22,75 L 35,65 Q 35,30 50,10 Z M 50,32 A 7,7 0 1,0 50,32.1 M 45,72 L 50,88 L 55,72",
        "ракету",
        "🚀",
    ),
    "plane": (
        "M 50,8 L 54,35 L 92,58 L 92,66 L 54,54 L 54,82 L 65,92 L 65,96 L 50,92 L 35,96 L 35,92 L 46,82 L 46,54 L 8,66 L 8,58 L 46,35 Z",
        "самолёт",
        "✈️",
    ),
    "house": (
        "M 50,12 L 88,44 L 80,44 L 80,88 L 20,88 L 20,44 L 12,44 Z M 40,88 L 40,58 L 60,58 L 60,88 Z M 65,30 L 72,30 L 72,38 L 65,32 Z",
        "домик",
        "🏠",
    ),
    "sakura": (
        "M 50,50 Q 50,22 42,15 Q 50,18 58,15 Q 50,22 50,50 M 50,50 Q 75,32 82,25 Q 82,35 88,38 Q 75,45 50,50 M 50,50 Q 65,75 75,82 Q 65,82 62,90 Q 55,75 50,50 M 50,50 Q 25,68 18,75 Q 18,65 12,62 Q 25,55 50,50 M 50,50 Q 35,25 25,18 Q 35,18 38,10 Q 45,25 50,50 M 50,50 A 6,6 0 1,0 50,50.1",
        "цветок сакуры",
        "🌸",
    ),
    "smile": (
        "M 50,12 A 38,38 0 1,0 50,88 A 38,38 0 1,0 50,12 Z M 36,40 A 5,7 0 1,0 36,40.1 M 64,40 A 5,7 0 1,0 64,40.1 M 34,60 Q 50,78 66,60",
        "смайлик",
        "😊",
    ),
    "spider": (
        "M 50,38 A 8,8 0 1,0 50,38.1 M 50,60 A 14,16 0 1,0 50,60.1 M 42,48 Q 20,35 15,22 M 58,48 Q 80,35 85,22 M 40,55 Q 15,50 10,48 M 60,55 Q 85,50 90,48 M 40,62 Q 18,68 12,78 M 60,62 Q 82,68 88,78 M 42,70 Q 25,85 22,95 M 58,70 Q 75,85 78,95",
        "паука",
        "🕷️",
    ),
    "butterfly": (
        "M 50,30 L 50,75 M 48,35 C 30,10 5,25 15,55 C 22,75 45,60 48,55 C 45,65 25,82 35,92 C 45,95 48,80 50,72 M 52,35 C 70,10 95,25 85,55 C 78,75 55,60 52,55 C 55,65 75,82 65,92 C 55,95 52,80 50,72 M 48,30 Q 38,15 30,18 M 52,30 Q 62,15 70,18",
        "бабочку",
        "🦋",
    ),
    "bomb": (
        "M 50,32 A 28,28 0 1,0 50,88 A 28,28 0 1,0 50,32 Z M 44,32 L 44,24 L 56,24 L 56,32 Z M 50,24 Q 52,12 62,16 Q 70,20 74,12 M 72,10 L 76,14 M 76,10 L 72,14 M 74,8 L 74,16",
        "бомбу",
        "💣",
    ),
    "pizza": (
        "M 15,25 Q 50,15 85,25 L 50,90 Z M 15,25 Q 50,22 85,25 M 38,42 A 5,5 0 1,0 38,42.1 M 62,42 A 5,5 0 1,0 62,42.1 M 50,62 A 5,5 0 1,0 50,62.1",
        "пиццу",
        "🍕",
    ),
    "alien": (
        "M 50,15 C 30,15 22,35 25,60 C 28,78 40,88 50,88 C 60,88 72,78 75,60 C 78,35 70,15 50,15 Z M 34,48 Q 42,50 44,58 Q 38,65 32,58 Q 30,52 34,48 Z M 66,48 Q 58,50 56,58 Q 62,65 68,58 Q 70,52 66,48 Z M 47,75 L 53,75",
        "пришельца",
        "👽",
    ),
    "sun": (
        "M 50,28 A 22,22 0 1,0 50,72 A 22,22 0 1,0 50,28 Z M 50,8 L 50,20 M 50,80 L 50,92 M 8,50 L 20,50 M 80,50 L 92,50 M 20,20 L 29,29 M 71,71 L 80,80 M 20,80 L 29,71 M 71,29 L 80,20",
        "солнце",
        "☀️",
    ),
    "lips": (
        "M 12,50 Q 32,32 50,40 Q 68,32 88,50 Q 68,58 50,54 Q 32,58 12,50 Z M 12,50 Q 35,75 50,75 Q 65,75 88,50 Q 50,60 12,50 Z",
        "губы",
        "💋",
    ),
    "glasses": (
        "M 12,42 L 38,42 L 38,62 Q 25,68 12,62 Z M 62,42 L 88,42 L 88,62 Q 75,68 62,62 Z M 38,46 Q 50,42 62,46 M 12,44 L 5,38 M 88,44 L 95,38",
        "очки",
        "👓",
    ),
    "music": (
        "M 35,75 A 10,8 0 1,0 35,59 L 35,25 L 75,15 L 75,55 A 10,8 0 1,0 75,39 L 75,15 M 35,35 L 75,25",
        "ноту",
        "🎵",
    ),
    "shield": (
        "M 50,12 L 85,25 L 85,55 C 85,75 68,88 50,94 C 32,88 15,75 15,55 L 15,25 Z M 50,20 L 50,86",
        "щит",
        "🛡️",
    ),
    "target": (
        "M 50,20 A 30,30 0 1,0 50,80 A 30,30 0 1,0 50,20 Z M 50,35 A 15,15 0 1,0 50,65 A 15,15 0 1,0 50,35 Z M 50,10 L 50,30 M 50,70 L 50,90 M 10,50 L 30,50 M 70,50 L 90,50",
        "прицел",
        "🎯",
    ),
    "moon": (
        "M 65,15 C 40,15 25,32 25,55 C 25,78 42,92 65,92 C 72,92 80,88 85,82 C 60,82 45,65 45,52 C 45,35 55,22 75,20 C 72,17 68,15 65,15 Z",
        "луну",
        "🌙",
    ),
    "gamepad": (
        "M 25,35 C 15,35 12,50 15,72 C 16,80 24,82 28,75 L 35,60 L 65,60 L 72,75 C 76,82 84,80 85,72 C 88,50 85,35 75,35 Z M 30,45 L 30,55 M 25,50 L 35,50 M 72,45 A 2,2 0 1,0 72,45.1 M 68,52 A 2,2 0 1,0 68,52.1",
        "геймпад",
        "🎮",
    ),
}

# ══════════════════════════════════════════════════════════════════════════════
# СЕМАНТИЧЕСКИЙ МАППИНГ КЛЮЧЕВЫХ СЛОВ (РУССКИЙ + АНГЛИЙСКИЙ)
# ══════════════════════════════════════════════════════════════════════════════
KEYWORD_MAP: list[tuple[tuple[str, ...], str]] = [
    (("сердечк", "сердц", "любов", "heart", "love"), "heart"),
    (("звезд", "звездочк", "star"), "star"),
    (("котик", "кот", "кошк", "кошечк", "cat", "kitty"), "cat"),
    (("собак", "пес", "пёс", "щенок", "dog", "puppy"), "dog"),
    (("череп", "скелет", "кости", "skull", "skeleton"), "skull"),
    (("меч", "клинок", "сабл", "sword", "blade"), "sword"),
    (("пистолет", "пушк", "автомат", "ак47", "ak47", "gun", "pistol"), "gun"),
    (("дракон", "виверн", "ящер", "dragon"), "dragon"),
    (("член", "хуй", "пенис", "фаллос", "писюн", "dick", "cock", "penis"), "dick"),
    (("грудь", "сиськ", "бубс", "boobs", "tits"), "boobs"),
    (("фак", "средний палец", "фак ю", "fuck", "middle finger"), "fuck"),
    (("молни", "гром", "гроз", "lightning", "thunder"), "lightning"),
    (("огонь", "плам", "костер", "fire", "flame"), "fire"),
    (("корон", "царь", "корол", "crown", "king"), "crown"),
    (("привидени", "призрак", "ghost"), "ghost"),
    (("алмаз", "бриллиант", "кристалл", "diamond", "crystal"), "diamond"),
    (("машин", "тачк", "авто", "car", "auto"), "car"),
    (("ракет", "космос", "rocket", "space"), "rocket"),
    (("самолет", "самолёт", "plane", "aircraft"), "plane"),
    (("дом", "домик", "здани", "house", "home"), "house"),
    (("сакур", "цветок", "роз", "flower", "rose"), "sakura"),
    (("смайл", "улыбк", "smile"), "smile"),
    (("паук", "паутин", "spider"), "spider"),
    (("бабочк", "мотылек", "butterfly"), "butterfly"),
    (("бомб", "гранат", "взрыв", "bomb"), "bomb"),
    (("пицц", "pizza"), "pizza"),
    (("пришелец", "инопланетян", "нло", "alien", "ufo"), "alien"),
    (("солнц", "солнышк", "sun"), "sun"),
    (("губ", "поцелу", "lips", "kiss"), "lips"),
    (("очк", "glasses"), "glasses"),
    (("нот", "музык", "music", "note"), "music"),
    (("щит", "защит", "shield"), "shield"),
    (("прицел", "мишен", "target", "aim"), "target"),
    (("лун", "месяц", "moon"), "moon"),
    (("геймпад", "джойстик", "приставк", "gamepad", "joystick"), "gamepad"),
]


@dataclass
class InkShape:
    kind: str  # "circle", "arrow", "box", "line", "text", "path", "heart", "star", "smile", "cat"
    points: list[float]  # координаты точек [x1, y1, x2, y2, ...]
    text: str = ""
    color: str = _DEFAULT_COLOR
    width: float = 3.0


@dataclass
class InkDrawing:
    shapes: list[InkShape] = field(default_factory=list)
    created_at: float = field(default_factory=time.time)
    duration: float = 10.0  # Авто-исчезновение через 10 секунд (0 = вечно)


def parse_ink_shapes(shapes_text: str, default_color: str = _DEFAULT_COLOR) -> list[InkShape]:
    """Парсит текстовые инструкции рисования вида:
    'circle 100 100 200 200; arrow 50 50 100 100; text 100 80 Нажми сюда; path 960 480 180 M 50,85...'
    """
    shapes: list[InkShape] = []
    lines = [line.strip() for line in re.split(r"[;\n]", shapes_text) if line.strip()]

    for line in lines:
        parts = line.split(maxsplit=1)
        if not parts:
            continue
        kind = parts[0].lower()
        rest = parts[1] if len(parts) > 1 else ""

        if kind in ("circle", "box", "arrow", "line"):
            nums = [float(n) for n in re.findall(r"[-+]?(?:\d*\.\d+|\d+)", rest)]
            if len(nums) >= 4:
                shapes.append(InkShape(kind=kind, points=nums[:4], color=default_color))

        elif kind == "path":
            # path [cx cy size] d="..." or path d="..."
            m = re.match(r"^([-+]?\d+(?:\.\d+)?)\s+([-+]?\d+(?:\.\d+)?)\s+([-+]?\d+(?:\.\d+)?)\s+(.*)$", rest)
            if m:
                cx = float(m.group(1))
                cy = float(m.group(2))
                sz = float(m.group(3))
                d_str = m.group(4).strip()
                shapes.append(InkShape(kind="path", points=[cx, cy, sz], text=d_str, color=default_color))
            else:
                shapes.append(InkShape(kind="path", points=[], text=rest.strip(), color=default_color))

        elif kind in ("heart", "star", "smile", "cat"):
            nums = [float(n) for n in re.findall(r"[-+]?(?:\d*\.\d+|\d+)", rest)]
            if len(nums) == 0:
                nums = [960.0, 480.0, 140.0]
            elif len(nums) == 2:
                nums.append(140.0)
            shapes.append(InkShape(kind=kind, points=nums[:3], color=default_color))

        elif kind == "text":
            match = re.match(r"^([-+]?(?:\d*\.\d+|\d+))\s+([-+]?(?:\d*\.\d+|\d+))\s+(.*)$", rest)
            if match:
                x = float(match.group(1))
                y = float(match.group(2))
                txt = match.group(3).strip()
                shapes.append(InkShape(kind="text", points=[x, y], text=txt, color=default_color))

    return shapes


def resolve_drawing_request(raw_text: str) -> Optional[tuple[str, str]]:
    """Распознаёт просьбу нарисовать что-либо на экране.
    Возвращает (shapes_instructions, voice_response) или None.
    РАБОТАЕТ БЕЗ ЦЕНЗУРЫ, БЕЗ МОРАЛИ И БЕЗ НРАВОУЧЕНИЙ.
    """
    clean = raw_text.lower().replace("ё", "е").strip()
    clean = re.sub(r"^(?:сакура|sakura)[,!\s]+", "", clean).strip()

    # 1. Проверка на очистку
    if any(w in clean for w in ("сотри", "очисти экран", "убери рисунок", "удали рисунок", "сотри чернила")):
        return "clear", "Стёрла рисунок с экрана."

    # 2. Проверка: является ли фраза запросом на рисование
    prefixes = ("нарисуй", "начерти", "изобрази", "покажи на экране", "нарисуй на экране", "отметь на экране", "рисуй")
    is_draw = any(clean.startswith(p) for p in prefixes) or "нарисуй" in clean or "на экране" in clean

    # Если прямо назван предмет из словаря даже без слова «нарисуй»
    matched_key: Optional[str] = None
    for kw_tuple, shape_key in KEYWORD_MAP:
        if any(kw in clean for kw in kw_tuple):
            matched_key = shape_key
            break

    if not is_draw and not matched_key:
        return None

    # Если нашли в словаре силуэтов 100x100
    if matched_key and matched_key in SHAPES_100:
        svg_d, label, emoji = SHAPES_100[matched_key]
        shapes = f"path 960 460 220 {svg_d}; text 960 620 {emoji} {label.capitalize()}"
        return shapes, f"Нарисовала {label} на экране."

    # 3. Если просят нарисовать текст или надпись
    m_text = re.search(r"(?:надпись|текст|слово|фразу)\s+[\"«']?(.+?)[\"»']?$", clean)
    if m_text:
        phrase = m_text.group(1).strip()
        shapes = f"box 760 410 400 120; text 960 475 ✦ {phrase}"
        return shapes, f"Вывела надпись «{phrase}» на экран."

    # 4. Любой произвольный объект («нарисуй дракона / меч / танк / космический корабль»)
    match = re.search(r"(?:нарисуй|начерти|изобрази|покажи на экране)\s+(?:мне\s+)?(.+)", clean)
    obj = match.group(1).strip() if match else clean
    obj = re.sub(r"\b(?:на экране|пожалуйста|мне|что-нибудь|быстро)\b", "", obj).strip()
    if not obj:
        obj = "рисунок"

    # Создаём процедурный киберпанк-чертёж/голограмму для запрошенного объекта
    # Включает голографический контур, маркеры прицеливания и неоновый бейдж с объектом
    shapes = (
        f"circle 960 450 160 160; "
        f"circle 960 450 180 180; "
        f"line 960 320 960 350; line 960 550 960 580; line 830 450 860 450; line 1060 450 1090 450; "
        f"box 860 590 200 45; "
        f"text 960 620 ✦ {obj.capitalize()}"
    )
    return shapes, f"Нарисовала {obj} на экране."


class InkManager:
    """Управление текущими чернилами на экране и отправка в UI."""

    def __init__(self, on_render: Optional[Callable[[list[dict[str, Any]]], None]] = None):
        self.on_render = on_render or (lambda shapes: log.debug("Ink render %d shapes", len(shapes)))
        self.current_drawing = InkDrawing()

    def draw(
        self,
        shapes_text: str = "",
        action: str = "replace",
        duration: float = 10.0,
        color: str = _DEFAULT_COLOR,
    ) -> list[dict[str, Any]]:
        """Выполнить операцию рисования."""
        action = action.lower().strip()

        if action == "clear":
            self.current_drawing.shapes.clear()
            self._dispatch()
            return []

        parsed = parse_ink_shapes(shapes_text, default_color=color)

        if action == "add":
            self.current_drawing.shapes.extend(parsed)
        else:  # replace
            self.current_drawing.shapes = parsed

        self.current_drawing.duration = duration
        self.current_drawing.created_at = time.time()
        self._dispatch()
        return self.to_payload()

    def clear(self):
        self.draw(action="clear")

    def to_payload(self) -> list[dict[str, Any]]:
        return [
            {
                "kind": s.kind,
                "points": s.points,
                "text": s.text,
                "color": s.color,
                "width": s.width,
            }
            for s in self.current_drawing.shapes
        ]

    def _dispatch(self):
        self.on_render(self.to_payload())
