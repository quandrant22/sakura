import fs from "node:fs";
import os from "node:os";
import path from "node:path";

import { expect, test } from "vitest";

import {
  CAPTURE_ID, describeDisplays, type DisplayLike, pickDisplay, readStagePrefs, toPhysical, writeStagePrefs,
} from "./displays";

const left: DisplayLike = { id: 2, bounds: { x: -1920, y: 0, width: 1920, height: 1080 },
                            workArea: { x: -1920, y: 0, width: 1920, height: 1040 }, scaleFactor: 1 };
const main: DisplayLike = { id: 1, bounds: { x: 0, y: 0, width: 1707, height: 960 },
                            workArea: { x: 0, y: 0, width: 1707, height: 912 }, scaleFactor: 1.5 };

test("мониторы слева направо, основной помечен, физический размер с учётом масштаба", () => {
  const list = describeDisplays([main, left], 1);
  expect(list.map((d) => d.id)).toEqual([2, 1]);
  expect(list[1]!.primary).toBe(true);
  expect(list[1]!.physical).toEqual({ x: 0, y: 0, width: 2561, height: 1440 });
  expect(list[1]!.label).toBe("Монитор 2 · 2561×1440 · основной");
  expect(list[0]!.label).toBe("Монитор 1 · 1920×1080");
});

test("dipToScreenRect (Windows) важнее расчёта", () => {
  const exact = { x: 0, y: 0, width: 2560, height: 1440 };
  expect(toPhysical(main, () => exact)).toEqual(exact);
  expect(toPhysical(main, () => { throw new Error("нет"); }).width).toBe(2561);
});

test("отключённый монитор → основной", () => {
  expect(pickDisplay([main, left], 2, main)).toBe(left);
  expect(pickDisplay([main], 2, main)).toBe(main);
  expect(pickDisplay([main, left], null, main)).toBe(main);
});

test("stage.json: запись, чтение, мусор → значения по умолчанию", () => {
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), "stage-"));
  const file = path.join(dir, "stage.json");
  expect(readStagePrefs(file)).toEqual({ displayId: null, enabled: true });
  writeStagePrefs(file, { displayId: 7, enabled: false });
  expect(readStagePrefs(file)).toEqual({ displayId: 7, enabled: false });
  fs.writeFileSync(file, "{не json");
  expect(readStagePrefs(file)).toEqual({ displayId: null, enabled: true });
});

test("захват: окна и мониторы, остальное — нет", () => {
  expect(CAPTURE_ID.test("window:132456:0")).toBe(true);
  expect(CAPTURE_ID.test("screen:1:0")).toBe(true);
  expect(CAPTURE_ID.test("webcontents:1:0")).toBe(false);
  expect(CAPTURE_ID.test("screen:1:0; rm")).toBe(false);
});
