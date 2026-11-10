import { expect, test } from "vitest";

import {
  arrowHead, EMPTY_STAGE, hasContent, MAX_TOASTS, prune, scalePoints, subtitleMs, withInk, withSubtitle, withToast,
} from "./stageLogic";

test("пустая сцена прячется; ядро видно только в игре и только когда Сакура занята", () => {
  expect(hasContent(EMPTY_STAGE, 0)).toBe(false);
  expect(hasContent({ ...EMPTY_STAGE, coreState: "speaking" }, 0)).toBe(false);
  expect(hasContent({ ...EMPTY_STAGE, coreState: "speaking", gameMode: true }, 0)).toBe(true);
  expect(hasContent({ ...EMPTY_STAGE, coreState: "idle", gameMode: true }, 0)).toBe(false);
});

test("рисование живёт duration секунд; 0 — до очистки; пустой список — очистка", () => {
  const m = withInk(EMPTY_STAGE, [{ kind: "circle", points: [1, 2, 3, 4] }], { w: 1280, h: 720 }, 5, 1000);
  expect(hasContent(m, 5999)).toBe(true);
  expect(hasContent(m, 6001)).toBe(false);
  expect(withInk(EMPTY_STAGE, [{ kind: "box", points: [0, 0, 1, 1] }], undefined, 0, 0).ink!.until).toBe(3_600_000);
  expect(withInk(m, [], undefined, 5, 0).ink).toBeNull();
});

test("субтитры: в игре всегда, вне игры — по настройке; длина реплики → время", () => {
  expect(withSubtitle(EMPTY_STAGE, "привет", 0).subtitle).toBeNull();
  expect(withSubtitle({ ...EMPTY_STAGE, gameMode: true }, "привет", 0).subtitle?.text).toBe("привет");
  expect(withSubtitle({ ...EMPTY_STAGE, subtitlesAlways: true }, "привет", 0).subtitle).not.toBeNull();
  expect(subtitleMs("а")).toBe(2500);
  expect(subtitleMs("а".repeat(1000))).toBe(12_000);
});

test("всплывашек не больше трёх, просроченные уходят", () => {
  let m = EMPTY_STAGE;
  for (let i = 0; i < 5; i++) m = withToast(m, "t", String(i), "game", 0);
  expect(m.toasts).toHaveLength(MAX_TOASTS);
  expect(m.toasts.map((t) => t.text)).toEqual(["2", "3", "4"]);
  expect(prune(m, 10_000).toasts).toHaveLength(0);
});

test("координаты снимка → пиксели сцены; без системы координат — как есть", () => {
  expect(scalePoints([640, 360, 1280, 720], { w: 1280, h: 720 }, { w: 2560, h: 1440 })).toEqual([1280, 720, 2560, 1440]);
  expect(scalePoints([5, 6], { w: 0, h: 0 }, { w: 100, h: 100 })).toEqual([5, 6]);
});

test("наконечник стрелки смотрит назад от конца", () => {
  const [ax, , bx] = arrowHead(0, 0, 100, 0);
  expect(ax).toBeLessThan(100);
  expect(bx).toBeLessThan(100);
});
