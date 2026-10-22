import { describe, expect, test } from "vitest";

import { fitRect } from "./videoFit";

// Тело виджета = размер виджета минус заголовок (44) и панель управления (~44): здесь сам box.
describe("вписывание 16:9 (contain) — таблица размеров виджета", () => {
  test.each([
    // box W×H          ожидаемое видео            letterbox
    [422, 450, { left: 0, top: 107, width: 422, height: 237 }],   // узкий высокий — полосы сверху и снизу
    [300, 350, { left: 0, top: 91, width: 300, height: 168 }],
    [690, 300, { left: 79, top: 0, width: 533, height: 300 }],    // широкий низкий — полосы по бокам
    [1000, 600, { left: 0, top: 19, width: 1000, height: 562 }],
    [1920, 1080, { left: 0, top: 0, width: 1920, height: 1080 }], // ровно 16:9 — без полос
  ])("%i×%i", (w, h, exp) => {
    const r = fitRect(w, h);
    expect(r).toEqual(exp);
    expect(r.width).toBeLessThanOrEqual(w);
    expect(r.height).toBeLessThanOrEqual(h);
    expect(Math.abs(r.width / r.height - 16 / 9)).toBeLessThan(0.01);
  });

  test("заполнить (cover) — покрывает box, лишнее обрезается", () => {
    const r = fitRect(422, 450, 16 / 9, "fill");
    expect(r.height).toBe(450);
    expect(r.width).toBeGreaterThanOrEqual(422);
    expect(r.left).toBeLessThan(0);
  });

  test("пропорции источника (4:3) и пустой box", () => {
    expect(fitRect(800, 300, 4 / 3)).toEqual({ left: 200, top: 0, width: 400, height: 300 });
    expect(fitRect(0, 300)).toEqual({ left: 0, top: 0, width: 0, height: 0 });
  });
});
