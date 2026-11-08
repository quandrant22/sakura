"""desktop.core.ink — Экранные чернила (Screen Ink / Визуальная указка).

Вдохновлен capri-desktop Ink.cs:
Позволяет Сакуре или пользователю рисовать поверх экрана:
- Обвести кнопку или область (circle left top right bottom)
- Указать стрелкой на элемент (arrow x1 y1 x2 y2)
- Нарисовать прямоугольник/рамку (box left top right bottom)
- Добавить текстовую метку на экран (text x y «текст»)
- Нарисовать произвольный путь (path x1 y1 x2 y2...)
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
    kind: str  # "circle", "arrow", "box", "line", "text", "path"
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
    'circle 100 100 200 200; arrow 50 50 100 100; text 100 80 Нажми сюда'
    """
    shapes: list[InkShape] = []
    lines = [line.strip() for line in re.split(r"[;\n]", shapes_text) if line.strip()]

    for line in lines:
        parts = line.split(maxsplit=1)
        if not parts:
            continue
        kind = parts[0].lower()
        rest = parts[1] if len(parts) > 1 else ""

        if kind in ("circle", "box", "arrow", "line", "path"):
            nums = [float(n) for n in re.findall(r"[-+]?(?:\d*\.\d+|\d+)", rest)]
            if kind in ("circle", "box") and len(nums) >= 4:
                shapes.append(InkShape(kind=kind, points=nums[:4], color=default_color))
            elif kind in ("arrow", "line") and len(nums) >= 4:
                shapes.append(InkShape(kind=kind, points=nums[:4], color=default_color))
            elif kind == "path" and len(nums) >= 4:
                shapes.append(InkShape(kind=kind, points=nums, color=default_color))

        elif kind == "text":
            match = re.match(r"^([-+]?(?:\d*\.\d+|\d+))\s+([-+]?(?:\d*\.\d+|\d+))\s+(.*)$", rest)
            if match:
                x = float(match.group(1))
                y = float(match.group(2))
                txt = match.group(3).strip()
                shapes.append(InkShape(kind="text", points=[x, y], text=txt, color=default_color))

    return shapes


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
