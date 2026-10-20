import { act, cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, expect, test } from "vitest";

import type { CoreClient } from "../api/client";
import { DemoClient } from "../api/demo";
import { MediaProvider } from "../media/MediaContext";
import { createAppStore, StoreContext } from "../store";
import { ConnectionWizard, findProblems } from "./ConnectionWizard";

afterEach(cleanup);

class C extends DemoClient {
  calls: { type: string; payload: Record<string, unknown> }[] = [];
  override async call<T>(type: string, payload: Record<string, unknown> = {}): Promise<T> {
    this.calls.push({ type, payload });
    if (type === "config_values") return { values: { DEVICE_ID: "mostech", VPS_WS_URL: "ws://h:8765", SERVER_TRANSPORT: "" },
                                           running: { DEVICE_ID: "mostech", VPS_WS_URL: "ws://h:8765", SERVER_TRANSPORT: "ws" } } as T;
    if (type === "secrets_status") return { keys: { WS_TOKEN: true, YANDEX_MUSIC_TOKEN: false } } as T;
    if (type === "config_set" || type === "secrets_set" || type === "sound_test") return { ok: true } as T;
    if (type === "mic_level") return { db: -48 } as T;
    return super.call<T>(type, payload);
  }
  push(ev: Record<string, unknown>) { this.emit(ev as never); }
}

function setup() {
  const c = new C("normal");
  const store = createAppStore(c as CoreClient);
  act(() => { store.getState().init(); });
  render(<MediaProvider client={c as CoreClient}><StoreContext.Provider value={store}><ConnectionWizard /></StoreContext.Provider></MediaProvider>);
  return c;
}

test("итог: проблемы с шагом «Исправить»", () => {
  const p = findProblems({ server: false, mic: true, wakeOk: false, ext: false, ymToken: true, secure: false });
  expect(p.map((x) => x.step)).toEqual([0, 1, 3, 4]);
  expect(findProblems({ server: true, mic: true, wakeOk: true, ext: true, ymToken: true, secure: true })).toEqual([]);
});

test("мастер: адрес сервера сохраняется, токен — маскированно и без следа в окне, «Исправить» ведёт на шаг", async () => {
  const c = setup();
  await waitFor(() => expect((screen.getByLabelText("Адрес сервера") as HTMLInputElement).value).toBe("ws://h:8765"));
  fireEvent.change(screen.getByLabelText("Адрес сервера"), { target: { value: "ws://31.76.80.5:8765" } });
  fireEvent.click(screen.getAllByText("Сохранить")[1]!);
  await waitFor(() => expect(c.calls).toContainEqual({ type: "config_set", payload: { key: "VPS_WS_URL", value: "ws://31.76.80.5:8765" } }));
  fireEvent.click(screen.getByText("6. Яндекс.Музыка"));
  const tok = screen.getByLabelText("Токен Яндекс.Музыки") as HTMLInputElement;
  expect(tok.type).toBe("password");
  fireEvent.change(tok, { target: { value: "secret-value" } });
  fireEvent.submit(tok.closest("form")!);
  expect(tok.value).toBe("");
  await waitFor(() => expect(screen.getByText("задан")).toBeTruthy());
  expect(document.body.innerHTML).not.toContain("secret-value");
  fireEvent.click(screen.getByText("7. Проверка"));
  const fix = screen.getAllByText("Исправить");
  expect(fix.length).toBeGreaterThan(0);
  fireEvent.click(fix[0]!);
  expect(screen.getByLabelText("Шаги мастера").querySelector("[aria-current=step]")?.textContent).toContain("2. Защищённый канал");  // демо-сервер на связи → первая проблема — канал
});

test("слово «Сакура»: слух перешёл в «слушаю» — успех", async () => {
  const c = setup();
  fireEvent.click(screen.getByText("4. Слово «Сакура»"));
  fireEvent.click(screen.getByText("Начать проверку"));
  expect(screen.getByText(/Скажите «Сакура»/)).toBeTruthy();
  act(() => c.push({ type: "state", value: "listening", level: 0 }));
  await waitFor(() => expect(screen.getByText(/Слышу!/)).toBeTruthy());
});
