"""desktop.core.ink — Экранные чернила (Screen Ink / Визуальная указка).

Вдохновлен capri-desktop Ink.cs:
Позволяет Сакуре или пользователю рисовать поверх экрана:
- Обвести кнопку или область (circle left top right bottom)
- Указать стрелкой на элемент (arrow x1 y1 x2 y2)
- Нарисовать прямоугольник/рамку (box left top right bottom)
- Добавить текстовую метку на экран (text x y «текст»)
- Нарисовать произвольный путь (path x1 y1 x2 y2... или path d="...")
- Нарисовать сердечко (heart x y [size])
- Нарисовать звезду (star x y [size])
- Нарисовать смайлик (smile x y [size])
- Нарисовать котика (cat x y [size])
- Очистить экран (action: clear)

Команды сериализуются в структуры для UI-оверлея (SVG/Canvas) с эффектом неонового свечения (Neon Pink #FF2A85 / Sakura Blossom).
"""

from __future__ import annotations

import logging
import re
import time
from dataclasses import dataclass, field
from typing import Any, Callable, Optional

log = logging.getLogger("sakura.ink")

_DEFAULT_COLOR = "#FF2A85"  # Неоновый розовый стиль Сакуры


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
    'circle 100 100 200 200; arrow 50 50 100 100; text 100 80 Нажми сюда; heart 500 400 120'
    """
    shapes: list[InkShape] = []
    lines = [line.strip() for line in re.split(r"[;\n]", shapes_text) if line.strip()]

    for line in lines:
        parts = line.split(maxsplit=1)
        if not parts:
            continue
        kind = parts[0].lower()
        rest = parts[1] if len(parts) > 1 else ""

        if kind in ("circle", "box", "arrow", "line", "path", "heart", "star", "smile", "cat"):
            nums = [float(n) for n in re.findall(r"[-+]?(?:\d*\.\d+|\d+)", rest)]
            if kind in ("circle", "box") and len(nums) >= 4:
                shapes.append(InkShape(kind=kind, points=nums[:4], color=default_color))
            elif kind in ("arrow", "line") and len(nums) >= 4:
                shapes.append(InkShape(kind=kind, points=nums[:4], color=default_color))
            elif kind == "path":
                shapes.append(InkShape(kind=kind, points=nums, text=rest.strip(), color=default_color))
            elif kind in ("heart", "star", "smile", "cat"):
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
    Работает без нравоучений и морализаторства — исполняет любое желание пользователя.
    """
    clean = raw_text.lower().replace("ё", "е").strip()
    clean = re.sub(r"^(?:сакура|sakura)[,!\s]+", "", clean).strip()

    # Проверка на очистку
    if any(w in clean for w in ("сотри", "очисти экран", "убери рисунок", "удали рисунок", "сотри чернила")):
        return "clear", "Стёрла рисунок с экрана."

    # Проверка на просьбу нарисовать / показать
    prefixes = ("нарисуй", "начерти", "изобрази", "покажи на экране", "нарисуй на экране", "отметь на экране")
    is_draw_req = any(clean.startswith(p) for p in prefixes) or "нарисуй" in clean or "на экране" in clean
    if not is_draw_req and not any(w in clean for w in ("сердечко", "котика", "смайлик", "звездочку")):
        return None

    # 1. Сердечко
    if any(w in clean for w in ("сердечк", "сердц", "heart", "любов")):
        return "heart 960 480 160; text 960 630 ❤️ Сердечко", "Нарисовала сердечко на экране."

    # 2. Котик / кошка
    if any(w in clean for w in ("кот", "котик", "кошечк", "кошк", "cat")):
        return "cat 960 480 170; text 960 630 🐱 Котик", "Нарисовала котика на экране."

    # 3. Звезда
    if any(w in clean for w in ("звезд", "star")):
        return "star 960 480 160; text 960 630 ⭐ Звезда", "Нарисовала звезду на экране."

    # 4. Смайлик / улыбка
    if any(w in clean for w in ("смайл", "улыбк", "smile")):
        return "smile 960 480 160; text 960 630 😊 Смайлик", "Нарисовала смайлик на экране."

    # 5. Сакура / цветок
    if any(w in clean for w in ("сакур", "цветок", "розочк", "flower")):
        return "heart 960 430 75; heart 960 530 75; heart 910 480 75; heart 1010 480 75; circle 960 480 30 30; text 960 630 🌸 Сакура", "Нарисовала цветок сакуры на экране."

    # 6. Дом / домик
    if any(w in clean for w in ("дом", "домик", "здание", "house")):
        return "box 860 440 200 180; line 850 440 960 340; line 960 340 1070 440; box 930 520 60 100; text 960 660 🏠 Домик", "Нарисовала домик на экране."

    # 7. Солнце
    if any(w in clean for w in ("солнц", "солнышк", "sun")):
        return "circle 960 480 120 120; line 960 340 960 390; line 960 570 960 620; line 820 480 870 480; line 1050 480 1100 480; text 960 650 ☀️ Солнце", "Нарисовала солнце на экране."

    # 8. Стрелка
    if any(w in clean for w in ("стрелк", "указк", "arrow")):
        return "arrow 820 580 1080 400; text 960 630 Указка", "Нарисовала стрелку на экране."

    # 9. Круг
    if any(w in clean for w in ("круг", "окружност", "circle")):
        return "circle 960 480 180 180; text 960 630 Круг", "Нарисовала круг на экране."

    # 10. Квадрат / рамка / бокс
    if any(w in clean for w in ("квадрат", "прямоугольник", "рамк", "бокс", "box")):
        return "box 860 380 200 200; text 960 630 Рамка", "Нарисовала рамку на экране."

    # 11. Любой другой объект («нарисуй X»)
    match = re.search(r"(?:нарисуй|начерти|изобрази|покажи на экране)\s+(?:мне\s+)?(.+)", clean)
    obj = match.group(1).strip() if match else clean
    obj = re.sub(r"\b(?:на экране|пожалуйста|мне|что-нибудь|быстро)\b", "", obj).strip()
    if not obj:
        obj = "рисунок"

    shapes = f"circle 960 480 150 150; arrow 820 380 930 450; text 960 630 ✦ {obj.capitalize()}"
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
