import { describe, expect, test } from "vitest";

import {
  addWidget, boardScale, defaultLayout, hiddenWidgets, itemRect, layoutHeight, removeWidget, sanitizeLayout, WIDGETS,
} from "./board";

// Блоки наброска (кадр 1440x1024) относительно левого верхнего угла доски (350, 104).
const SKETCH = {
  system: { left: 0, top: 0, width: 248, height: 450 },
  video: { left: 268, top: 0, width: 422, height: 450 },
  app: { left: 0, top: 470, width: 690, height: 300 },
  music: { left: 0, top: 790, width: 690, height: 100 },
};

describe("раскладка по умолчанию", () => {
  test("совпадает с наброском ±10 px", () => {
    for (const it of defaultLayout()) {
      const r = itemRect(it);
      const s = SKETCH[it.i];
      for (const k of ["left", "top", "width", "height"] as const) expect(Math.abs(r[k] - s[k])).toBeLessThanOrEqual(10);
    }
  });

  test("помещается в высоту доски наброска (890 px) без прокрутки", () => {
    expect(layoutHeight(defaultLayout())).toBeLessThanOrEqual(890);
    expect(layoutHeight(defaultLayout())).toBeGreaterThan(880);
    expect(layoutHeight([])).toBe(0);
  });

  test("музыка не меньше 480x100", () => {
    const m = WIDGETS.music;
    const r = itemRect({ x: 0, y: 0, w: m.minW, h: m.minH });
    expect(r.width).toBeGreaterThanOrEqual(480);
    expect(r.height).toBeGreaterThanOrEqual(97);
  });
});

describe("sanitizeLayout", () => {
  test("мусор, дубли и неизвестные виджеты отбрасываются, размеры ограничиваются", () => {
    const out = sanitizeLayout([
      { i: "system", x: 0, y: 0, w: 9, h: 16 },
      { i: "system", x: 5, y: 5, w: 9, h: 16 },
      { i: "evil", x: 0, y: 0, w: 1, h: 1 },
      { i: "music", x: 30, y: -4, w: 2, h: 1 },
      { i: "video", x: "a", y: 0, w: 1, h: 1 },
      null,
    ]);
    expect(out).toEqual([
      { i: "system", x: 0, y: 0, w: 9, h: 16 },
      { i: "music", x: 7, y: 16, w: 17, h: 4 }, // перекрывала «Систему» — опущена под неё
    ]);
    expect(sanitizeLayout("x")).toBeNull();
  });
});

test("перекрытия из сохранённого файла раздвигаются (случай с mostech 12.10)", () => {
  const out = sanitizeLayout([
    { i: "system", x: 15, y: 40, w: 9, h: 16 },
    { i: "video", x: 0, y: 0, w: 15, h: 16 },
    { i: "app", x: 0, y: 32, w: 24, h: 11 },
    { i: "music", x: 0, y: 38, w: 24, h: 4 },
  ])!;
  const by = Object.fromEntries(out.map((it) => [it.i, it]));
  expect(by.app).toMatchObject({ y: 32 });
  expect(by.music).toMatchObject({ y: 43 });
  expect(by.system).toMatchObject({ y: 47 });
  for (const a of out) for (const b of out) {
    if (a === b) continue;
    const hit = a.x < b.x + b.w && b.x < a.x + a.w && a.y < b.y + b.h && b.y < a.y + a.h;
    expect(hit).toBe(false);
  }
});

describe("добавить / удалить", () => {
  test("удалённый виджет возвращается на своё место, если оно свободно", () => {
    const l = removeWidget(defaultLayout(), "video");
    expect(hiddenWidgets(l)).toEqual(["video"]);
    expect(addWidget(l, "video").find((it) => it.i === "video")).toMatchObject({ x: 9, y: 0 });
  });

  test("если место занято — под всеми виджетами", () => {
    const l = removeWidget(defaultLayout(), "video").map((it) => (it.i === "system" ? { ...it, w: 24 } : it));
    expect(addWidget(l, "video").find((it) => it.i === "video")).toMatchObject({ x: 9, y: 31 });
  });

  test("повторное добавление ничего не меняет", () => {
    const l = defaultLayout();
    expect(addWidget(l, "music")).toBe(l);
  });
});

test("масштаб доски", () => {
  expect(boardScale(690)).toBe(1);
  expect(boardScale(1200)).toBe(1);
  expect(boardScale(460)).toBeCloseTo(0.667, 2);
});
