import { act, cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, expect, test, vi } from "vitest";

import type { CoreClient } from "../api/client";
import { DemoClient } from "../api/demo";
import type { SakuraBridge } from "../bridge";
import { MediaProvider } from "../media/MediaContext";
import { createAppStore, StoreContext } from "../store";
import { VoiceSection } from "./VoiceSection";

afterEach(() => { cleanup(); delete window.sakura; });

class C extends DemoClient {
  sets: Record<string, unknown>[] = [];
  override async call<T>(type: string, payload: Record<string, unknown> = {}): Promise<T> {
    if (type === "settings_set") { this.sets.push(payload); return { settings: {} } as T; }
    return super.call<T>(type, payload);
  }
}

test("голос: замены сохраняются, занятое сочетание «говорить» не сохраняется", async () => {
  const setTalkHotkey = vi.fn(async (combo: string) => combo !== "Control+Alt+Delete");
  window.sakura = { core: { setTalkHotkey, onTalk: () => () => {} } } as unknown as SakuraBridge;
  const c = new C("normal");
  const store = createAppStore(c as CoreClient);
  act(() => { store.getState().init(); });
  render(<MediaProvider client={c as CoreClient}><StoreContext.Provider value={store}><VoiceSection /></StoreContext.Provider></MediaProvider>);
  await waitFor(() => expect(screen.getByLabelText("Чувствительность слова Сакура")).toBeTruthy());
  fireEvent.click(screen.getByText("Добавить"));
  fireEvent.change(screen.getByLabelText("Распознано 1"), { target: { value: "вал хейм" } });
  fireEvent.change(screen.getByLabelText("Заменить на 1"), { target: { value: "Valheim" } });
  fireEvent.click(screen.getByText("Сохранить замены"));
  await waitFor(() => expect(c.sets).toContainEqual({ key: "stt_replacements", value: [["вал хейм", "Valheim"]] }));
  const hk = screen.getByLabelText("Клавиша говорить");
  fireEvent.change(hk, { target: { value: "Control+Alt+Delete" } });
  fireEvent.blur(hk);
  await waitFor(() => expect(screen.getByRole("status").textContent).toContain("занято"));
  expect(c.sets.some((s) => s.key === "hotkey_talk")).toBe(false);
  fireEvent.change(hk, { target: { value: "Control+Alt+K" } });
  fireEvent.blur(hk);
  await waitFor(() => expect(c.sets).toContainEqual({ key: "hotkey_talk", value: "Control+Alt+K" }));
  fireEvent.change(screen.getByLabelText("Чувствительность слова Сакура"), { target: { value: "low" } });
  await waitFor(() => expect(c.sets).toContainEqual({ key: "wake_sensitivity", value: "low" }));
});
