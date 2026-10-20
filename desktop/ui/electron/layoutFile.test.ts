import fs from "node:fs";
import os from "node:os";
import path from "node:path";
import { afterEach, beforeEach, expect, test } from "vitest";

import { createPrefsStore } from "../src/layout/prefs";
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
  expect(readLayout(file, "pc")).toBeNull();
  // повреждённый файл сохранён копией — ровно одной
  const copies = fs.readdirSync(path.dirname(file)).filter((n) => n.startsWith("layout.json.corrupt-"));
  expect(copies).toHaveLength(1);
  expect(fs.readFileSync(path.join(path.dirname(file), copies[0]!), "utf-8")).toBe("{не json");
  expect(writeLayout(file, "pc", { theme: "night" })).toBe(true);
  expect(readLayout(file, "pc")).toEqual({ theme: "night" });
});

test("смена DEVICE_ID в окне не затирает раскладку другого устройства в layout.json", async () => {
  writeLayout(file, "pc", { theme: "sketch", chatWidth: 420 });
  const api = { get: async (id: string) => readLayout(file, id), set: async (id: string, e: Record<string, unknown>) => writeLayout(file, id, e),
                exportFile: async () => false, importFile: async () => null };
  const s = createPrefsStore(() => api, 20);
  await s.getState().load("pc");
  s.getState().set("chatWidth", 444);        // не успело сохраниться
  await s.getState().load("laptop");         // DEVICE_ID сменился
  s.getState().set("chatWidth", 333);
  await new Promise((r) => setTimeout(r, 80));
  expect(readLayout(file, "pc")).toMatchObject({ theme: "sketch", chatWidth: 444 });
  expect(readLayout(file, "laptop")).toMatchObject({ chatWidth: 333 });
});
