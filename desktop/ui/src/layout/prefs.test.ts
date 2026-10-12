import { afterEach, beforeEach, expect, test, vi } from "vitest";

import { defaultLayout } from "./board";
import { CHAT, createPrefsStore, parsePersisted } from "./prefs";

function fakeApi(initial: Record<string, Record<string, unknown>> = {}) {
  const mem = new Map(Object.entries(initial));
  const set = vi.fn(async (id: string, e: Record<string, unknown>) => { mem.set(id, e); return true; });
  return { api: { get: async (id: string) => mem.get(id) ?? null, set }, mem, set };
}

beforeEach(() => vi.useFakeTimers());
afterEach(() => vi.useRealTimers());

test("по умолчанию: «Сакура-ночь», чат 350, раскладка наброска", () => {
  const p = parsePersisted(null);
  expect(p).toMatchObject({ theme: "night", chatWidth: 350, chatCollapsed: false, locked: false, mobility: "normal", preset: "soft" });
  expect(p.layout).toEqual(defaultLayout());
});

test("испорченные значения заменяются значениями по умолчанию", () => {
  const p = parsePersisted({ theme: "neon", chatWidth: 10, layout: "x", mobility: "turbo", locked: "yes" });
  expect(p).toMatchObject({ theme: "night", chatWidth: CHAT.min, locked: false, mobility: "normal" });
  expect(p.layout).toEqual(defaultLayout());
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

test("удалить, добавить, сбросить", async () => {
  const { api } = fakeApi();
  const s = createPrefsStore(() => api, 100);
  await s.getState().load("pc");
  s.getState().removeWidget("video");
  expect(s.getState().layout.map((it) => it.i)).not.toContain("video");
  s.getState().addWidget("video");
  expect(s.getState().layout.map((it) => it.i)).toContain("video");
  s.getState().set("layout", []);
  s.getState().resetLayout();
  expect(s.getState().layout).toEqual(defaultLayout());
});
