import { act, cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, expect, test } from "vitest";

import type { CoreClient } from "../api/client";
import { DemoClient } from "../api/demo";
import type { Settings } from "../api/types";
import { BrowserTaskBanner } from "../components/ControlSafety";
import { MediaProvider } from "../media/MediaContext";
import { createAppStore, StoreContext } from "../store";
import { ExtensionSection } from "./SettingsExtra";

afterEach(cleanup);

const CONNECTED = "abcdefghijklmnopabcdefghijklmnop";
const OTHER = "ponmlkjihgfedcbaponmlkjihgfedcba";

class C extends DemoClient {
  calls: { type: string; payload: Record<string, unknown> }[] = [];
  override async call<T>(type: string, payload: Record<string, unknown> = {}): Promise<T> {
    this.calls.push({ type, payload });
    if (type === "extension_set" || type === "browser_resume") return { ok: true } as T;
    return super.call<T>(type, payload);
  }
  push(ev: Record<string, unknown>) { this.emit(ev as never); }
}

function setup(settings: Partial<Settings>) {
  const c = new C("normal");
  const store = createAppStore(c as CoreClient);
  render(
    <MediaProvider client={c as CoreClient}><StoreContext.Provider value={store}>
      <BrowserTaskBanner /><ExtensionSection />
    </StoreContext.Provider></MediaProvider>);
  act(() => { store.getState().init(); });
  act(() => c.push({ type: "settings", settings: { quick_prompts: [], language: "ru", theme: "sakura-night", ...settings } }));
  return { c, store };
}

test("версия расширения и предупреждение о старой версии", () => {
  setup({ extension_connected: true, extension_version: "3.1.0", extension_connected_id: CONNECTED });
  const v = screen.getByLabelText("Версия расширения");
  expect(v.textContent).toContain("3.1.0");
  expect(v.textContent).toContain("ожидается 3.2.0");
});

test("закрепить ID подключённого расширения — SAKURA_EXTENSION_ID", async () => {
  const { c } = setup({ extension_connected: true, extension_version: "3.2.0", extension_connected_id: CONNECTED, extension_id: "" });
  expect(screen.getByLabelText("Версия расширения").textContent).not.toContain("ожидается");
  expect(screen.getByText(/не закреплено/)).toBeTruthy();
  fireEvent.click(screen.getByText("Закрепить подключённое"));
  await waitFor(() => expect(screen.getByRole("status").textContent).toContain("Закреплён ID"));
  expect(c.calls.find((x) => x.type === "extension_set")?.payload).toEqual({ key: "SAKURA_EXTENSION_ID", value: CONNECTED });
});

test("ввод ID вручную, снятие закрепления, папка загрузок", async () => {
  const { c } = setup({ extension_connected: true, extension_connected_id: CONNECTED, extension_id: OTHER, browser_upload_dir: "" });
  expect(screen.getByText(/закреплён другой ID/)).toBeTruthy();
  expect((screen.getByLabelText("ID расширения") as HTMLInputElement).value).toBe(OTHER);
  fireEvent.change(screen.getByLabelText("ID расширения"), { target: { value: ` ${CONNECTED} ` } });
  fireEvent.click(screen.getAllByText("Сохранить")[0]!);
  fireEvent.click(screen.getByText("Снять закрепление"));
  fireEvent.change(screen.getByLabelText("Папка для загрузок"), { target: { value: "C:\\Uploads " } });
  fireEvent.click(screen.getAllByText("Сохранить")[1]!);
  await waitFor(() => expect(c.calls.filter((x) => x.type === "extension_set")).toHaveLength(3));
  expect(c.calls.filter((x) => x.type === "extension_set").map((x) => x.payload)).toEqual([
    { key: "SAKURA_EXTENSION_ID", value: CONNECTED },
    { key: "SAKURA_EXTENSION_ID", value: "" },
    { key: "BROWSER_UPLOAD_DIR", value: "C:\\Uploads" },
  ]);
});

test("задача в браузере: баннер, пауза с «Готово» → browser_resume, конец — баннер скрыт", async () => {
  const { c } = setup({});
  expect(screen.queryByLabelText("Сакура работает в браузере")).toBeNull();
  act(() => c.push({ type: "browser_task", task_id: "t1", state: "running", text: "" }));
  expect(screen.getByLabelText("Сакура работает в браузере")).toBeTruthy();
  act(() => c.push({ type: "browser_task", task_id: "t1", state: "paused", text: "капча" }));
  expect(screen.getByLabelText("Задача в браузере ждёт").textContent).toContain("капча");
  fireEvent.click(screen.getByText("Готово"));
  await waitFor(() => expect(screen.getByLabelText("Сакура работает в браузере")).toBeTruthy());
  expect(c.calls.find((x) => x.type === "browser_resume")?.payload).toEqual({ task_id: "t1" });
  act(() => c.push({ type: "browser_task", task_id: "t1", state: "done", text: "готово" }));
  expect(screen.queryByLabelText("Сакура работает в браузере")).toBeNull();
});
