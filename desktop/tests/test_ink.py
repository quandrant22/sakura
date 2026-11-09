"""Тесты для desktop.core.ink"""

import pytest
from desktop.core.ink import InkManager, parse_ink_shapes


def test_parse_ink_shapes():
    text = (
        "circle 10 20 100 200;\n"
        "arrow 0 0 50 50;\n"
        "box 200 300 400 500;\n"
        "text 150 120 Нажми здесь!"
    )
    shapes = parse_ink_shapes(text)
    assert len(shapes) == 4
    assert shapes[0].kind == "circle"
    assert shapes[0].points == [10.0, 20.0, 100.0, 200.0]
    assert shapes[1].kind == "arrow"
    assert shapes[2].kind == "box"
    assert shapes[3].kind == "text"
    assert shapes[3].text == "Нажми здесь!"
    assert shapes[3].points == [150.0, 120.0]


def test_ink_manager_operations():
    rendered = []
    manager = InkManager(on_render=lambda s: rendered.append(s))

    # 1. Replace draw
    payload = manager.draw("circle 10 10 50 50; text 10 10 Тест")
    assert len(payload) == 2
    assert len(rendered) == 1

    # 2. Add draw
    payload2 = manager.draw("arrow 0 0 10 10", action="add")
    assert len(payload2) == 3

    # 3. Clear draw
    payload3 = manager.draw(action="clear")
    assert len(payload3) == 0
    assert len(rendered[-1]) == 0


def test_resolve_drawing_request():
    from desktop.core.ink import resolve_drawing_request

    # Heart
    cmd, phrase = resolve_drawing_request("Нарисуй на экране сердечко")
    assert "heart" in cmd or "path" in cmd
    assert "сердечко" in phrase

    # Cat
    cmd, phrase = resolve_drawing_request("Сакура нарисуй котика")
    assert "cat" in cmd or "path" in cmd
    assert "котик" in phrase

    # Uncensored / Mature
    cmd, phrase = resolve_drawing_request("нарисуй член")
    assert "path" in cmd
    assert "член" in phrase

    # Arbitrary object
    cmd, phrase = resolve_drawing_request("нарисуй космический корабль")
    assert "circle" in cmd or "path" in cmd
    assert "космический корабль" in phrase

    # Clear
    cmd, phrase = resolve_drawing_request("сотри с экрана")
    assert cmd == "clear"
