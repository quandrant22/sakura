import fs from "node:fs";
import os from "node:os";
import path from "node:path";
import { expect, test } from "vitest";

import { clampToArea, minSize, presetSize, readBounds, snapToCorner, writeBounds } from "./miniWindow";

const AREA = { x: 0, y: 0, width: 1920, height: 1040 };

test("пресеты S/M/L 16:9 и минимум 240×135", () => {
  expect(presetSize("S")).toEqual({ width: 320, height: 180 });
  expect(presetSize("M")).toEqual({ width: 480, height: 270 });
  expect(presetSize("L")).toEqual({ width: 640, height: 360 });
  expect(minSize()).toEqual({ width: 240, height: 135 });
  expect(presetSize("M", 4 / 3)).toEqual({ width: 480, height: 360 }); // окно приложения 4:3
});

test("привязка к углам только у угла", () => {
  expect(snapToCorner({ x: 1580, y: 850, width: 320, height: 180 }, AREA)).toEqual(
    { x: 1588, y: 848, width: 320, height: 180 });
  expect(snapToCorner({ x: 10, y: 5, width: 320, height: 180 }, AREA)).toEqual({ x: 12, y: 12, width: 320, height: 180 });
  const mid = { x: 800, y: 400, width: 320, height: 180 };
  expect(snapToCorner(mid, AREA)).toEqual(mid);
  expect(snapToCorner({ x: 5, y: 400, width: 320, height: 180 }, AREA).y).toBe(400); // у края, но не у угла
});

test("окно не выходит за рабочую область и не меньше минимума", () => {
  expect(clampToArea({ x: 3000, y: 2000, width: 480, height: 270 }, AREA)).toEqual({ x: 1440, y: 770, width: 480, height: 270 });
  expect(clampToArea({ x: 0, y: 0, width: 100, height: 50 }, AREA)).toEqual({ x: 0, y: 0, width: 240, height: 135 });
});

test("позиция и размер сохраняются по ключу", () => {
  const f = path.join(fs.mkdtempSync(path.join(os.tmpdir(), "mini-")), "mini.json");
  expect(readBounds(f, "video")).toBeNull();
  writeBounds(f, "video", { x: 1.4, y: 2.6, width: 480, height: 270 });
  writeBounds(f, "window", { x: 5, y: 6, width: 640, height: 480 });
  expect(readBounds(f, "video")).toEqual({ x: 1, y: 3, width: 480, height: 270 });
  expect(readBounds(f, "window")?.width).toBe(640);
});
