import { describe, expect, test } from "vitest";

import { dominantColor, extrapolate, fmt, prevAction, visibleControls } from "./barLogic";

describe("панель музыки — логика", () => {
  test("позиция экстраполируется, пока играет, и не выходит за длительность", () => {
    const st = { status: "ok" as const, playing: true, position_s: 10, duration_s: 200, updated_age_s: 0.5 };
    expect(extrapolate(st, 0)).toBe(10.5);
    expect(extrapolate(st, 1.25)).toBe(11.75);
    expect(extrapolate({ ...st, playing: false }, 5)).toBe(10);
    expect(extrapolate({ ...st, position_s: 199 }, 5)).toBe(200);
    expect(extrapolate(null, 1)).toBe(0);
  });

  test("элементы скрываются по приоритету при узкой ширине", () => {
    expect(visibleControls(480)).toEqual({ modes: false, rating: false, volume: false, extras: false });
    expect(visibleControls(600)).toEqual({ modes: true, rating: false, volume: false, extras: false });
    expect(visibleControls(690)).toEqual({ modes: true, rating: true, volume: false, extras: false });
    expect(visibleControls(1000)).toEqual({ modes: true, rating: true, volume: true, extras: true });
  });

  test("доминирующий цвет обложки, прозрачные пиксели не считаются, затемнение", () => {
    const px = new Uint8ClampedArray([200, 100, 0, 255, 100, 100, 100, 255, 0, 0, 255, 0]);
    expect(dominantColor(px, 0)).toEqual([150, 100, 50]);
    expect(dominantColor(px, 0.5)).toEqual([75, 50, 25]);
    expect(dominantColor(new Uint8ClampedArray([1, 2, 3, 0]))).toBeNull();
  });

  test("«Предыдущий»: одинарный — в начало после 3 с, иначе назад; двойной — назад", () => {
    expect(prevAction(1, 10)).toBe("restart");
    expect(prevAction(1, 1)).toBe("prev");
    expect(prevAction(2, 0.2)).toBe("prev");
    expect(fmt(125)).toBe("2:05");
  });
});
