import { act, cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, expect, test } from "vitest";

import type { CoreClient } from "../api/client";
import { DemoClient } from "../api/demo";
import { MediaProvider } from "../media/MediaContext";
import { createAppStore, StoreContext } from "../store";
import { parsePrivate, VisionSection } from "./VisionSection";

afterEach(cleanup);

class C extends DemoClient {
  sets: Record<string, unknown>[] = [];
  override async call<T>(type: string, payload: Record<string, unknown> = {}): Promise<T> {
    if (type === "settings_set") { this.sets.push(payload); return { settings: {} } as T; }
    return super.call<T>(type, payload);
  }
}

test("список приватных окон: пустые строки и повторы убираются", () => {
  expect(parsePrivate("telegram.exe\n\n Личное ,TELEGRAM.EXE; банк")).toEqual(["telegram.exe", "Личное", "банк"]);
  expect(parsePrivate("")).toEqual([]);
});

test("зрение: разрешение и список уходят в settings_set", async () => {
  const c = new C("normal");
  const store = createAppStore(c as CoreClient);
  act(() => { store.getState().init(); });
  render(<MediaProvider client={c as CoreClient}><StoreContext.Provider value={store}><VisionSection /></StoreContext.Provider></MediaProvider>);
  const box = screen.getByLabelText("Разрешить Сакуре поглядывать") as HTMLInputElement;
  expect(box.checked).toBe(false);
  fireEvent.click(box);
  await waitFor(() => expect(c.sets).toContainEqual({ key: "vision_glance_allowed", value: true }));
  fireEvent.change(screen.getByLabelText("Приватные окна"), { target: { value: "telegram.exe\nПереписка" } });
  fireEvent.click(screen.getByText("Сохранить список"));
  await waitFor(() => expect(c.sets).toContainEqual({ key: "vision_private", value: ["telegram.exe", "Переписка"] }));
});
