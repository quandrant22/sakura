import fs from "node:fs";
import os from "node:os";
import path from "node:path";
import { afterEach, beforeEach, expect, test } from "vitest";

import { readLayout, writeLayout } from "./layoutFile";

let dir = "";
let file = "";
beforeEach(() => {
  dir = fs.mkdtempSync(path.join(os.tmpdir(), "sakura-layout-"));
  file = path.join(dir, "Sakura", "layout.json");
});
afterEach(() => fs.rmSync(dir, { recursive: true, force: true }));

test("запись и чтение по device_id, другие устройства не затираются", () => {
  expect(readLayout(file, "pc-1")).toBeNull();
  expect(writeLayout(file, "pc-1", { theme: "night", chatWidth: 400 })).toBe(true);
  expect(writeLayout(file, "laptop", { theme: "sketch" })).toBe(true);
  expect(readLayout(file, "pc-1")).toEqual({ theme: "night", chatWidth: 400 });
  expect(readLayout(file, "laptop")).toEqual({ theme: "sketch" });
});

test("неверный device_id и данные отклоняются", () => {
  expect(writeLayout(file, "../evil", { a: 1 })).toBe(false);
  expect(writeLayout(file, "", { a: 1 })).toBe(false);
  expect(writeLayout(file, "pc", [1, 2])).toBe(false);
  expect(writeLayout(file, "pc", "x")).toBe(false);
  expect(readLayout(file, 42)).toBeNull();
  expect(writeLayout(file, "pc", { big: "x".repeat(300 * 1024) })).toBe(false);
});

test("повреждённый файл не роняет чтение", () => {
  fs.mkdirSync(path.dirname(file), { recursive: true });
  fs.writeFileSync(file, "{не json");
  expect(readLayout(file, "pc")).toBeNull();
  expect(writeLayout(file, "pc", { theme: "night" })).toBe(true);
  expect(readLayout(file, "pc")).toEqual({ theme: "night" });
});
