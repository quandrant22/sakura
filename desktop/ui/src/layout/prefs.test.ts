import { afterEach, beforeEach, expect, test, vi } from "vitest";

import { addWidgetTo, defaultBoard, getPage, migrateV1 } from "./boardModel";
import { CHAT, createPrefsStore, parsePersisted } from "./prefs";

function fakeApi(initial: Record<string, Record<string, unknown>> = {}) {
  const mem = new Map(Object.entries(initial));
  const set = vi.fn(async (id: string, e: Record<string, unknown>) => { mem.set(id, e); return true; });
  return { api: { get: async (id: string) => mem.get(id) ?? null, set, exportFile: async () => false, importFile: async () => null },
           mem, set };
}

beforeEach(() => vi.useFakeTimers());
afterEach(() => vi.useRealTimers());

test("по умолчанию: «Сакура-ночь», чат 350, доска v2 из трёх страниц", () => {
  const p = parsePersisted(null);
  expect(p).toMatchObject({ theme: "night", chatWidth: 350, chatCollapsed: false, locked: false, mobility: "normal",
                            preset: "soft", boardMode: "pack", autoGamePage: false });
  expect(p.board).toEqual(defaultBoard());
});

test("испорченные значения заменяются значениями по умолчанию", () => {
  const p = parsePersisted({ theme: "neon", chatWidth: 10, board: "x", mobility: "turbo", locked: "yes", boardMode: "chaos" });
  expect(p).toMatchObject({ theme: "night", chatWidth: CHAT.min, locked: false, mobility: "normal", boardMode: "pack" });
  expect(p.board).toEqual(defaultBoard());
});

test("старая запись (layout v1) мигрирует в v2", () => {
  const v1 = [{ i: "system", x: 0, y: 0, w: 9, h: 16 }, { i: "app", x: 0, y: 16, w: 24, h: 11 }];
  const p = parsePersisted({ layout: v1 });
  expect(p.board).toEqual(migrateV1(v1));
  expect(getPage(p.board).breakpoints.lg.map((it) => it.type)).toEqual(["system", "window"]);
});

test("загрузка по device_id и сохранение с задержкой", async () => {
  const { api, set, mem } = fakeApi({ pc: { theme: "sketch", chatWidth: 420 } });
  const s = createPrefsStore(() => api, 100);
  await s.getState().load("pc");
  expect(s.getState()).toMatchObject({ theme: "sketch", chatWidth: 420, loaded: true });
  expect(set).not.toHaveBeenCalled();

  s.getState().set("chatWidth", 500);
  s.getState().set("chatWidth", 510);
  vi.advanceTimersByTime(150);
  expect(set).toHaveBeenCalledTimes(1);
  expect(mem.get("pc")).toMatchObject({ chatWidth: 510, theme: "sketch" });
});

test("режим правки не сохраняется и недоступен под замком", async () => {
  const { api, set } = fakeApi();
  const s = createPrefsStore(() => api, 100);
  await s.getState().load("pc");
  s.getState().setEditing(true);
  vi.advanceTimersByTime(150);
  expect(set).not.toHaveBeenCalled();
  expect(s.getState().editing).toBe(true);

  s.getState().set("locked", true);
  s.getState().setEditing(false);
  s.getState().setEditing(true);
  expect(s.getState().editing).toBe(false);
});

test("изменения доски сохраняются в layout.json (version 2)", async () => {
  const { api, mem } = fakeApi();
  const s = createPrefsStore(() => api, 100);
  await s.getState().load("pc");
  s.getState().updateBoard((b) => addWidgetTo(b, "notes", "S").board);
  vi.advanceTimersByTime(150);
  const saved = mem.get("pc")?.board as { version: number; pages: { breakpoints: { lg: { type: string }[] } }[] };
  expect(saved.version).toBe(2);
  expect(saved.pages[0]!.breakpoints.lg.some((it) => it.type === "notes")).toBe(true);
});
