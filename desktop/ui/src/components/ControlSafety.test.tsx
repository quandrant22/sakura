import { act, cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, expect, test } from "vitest";

import type { CoreClient } from "../api/client";
import { DemoClient } from "../api/demo";
import { MediaProvider } from "../media/MediaContext";
import { createAppStore, StoreContext } from "../store";
import { ActionCenter, ConfirmDialog, ControlBanner } from "./ControlSafety";

afterEach(cleanup);

class C extends DemoClient {
  calls: { type: string; payload: Record<string, unknown> }[] = [];
  override async call<T>(type: string, payload: Record<string, unknown> = {}): Promise<T> {
    this.calls.push({ type, payload });
    if (type === "actions_recent") return { actions: [{ action: "window.list", status: "done", ts: 1760000000 }], pending: [], paused: false } as T;
    if (type === "update_status") return { behind: 2 } as T;
    if (type === "panic" || type === "confirm_answer") return { ok: true } as T;
    return super.call<T>(type, payload);
  }
  push(ev: Record<string, unknown>) { this.emit(ev as never); }
}

function setup() {
  const c = new C("normal");
  const store = createAppStore(c as CoreClient);
  render(
    <MediaProvider client={c as CoreClient}><StoreContext.Provider value={store}>
      <ControlBanner /><ConfirmDialog /><ActionCenter />
    </StoreContext.Provider></MediaProvider>);
  act(() => { store.getState().init(); });
  return { c, store };
}

test("во время действия — баннер и «Стоп» (аварийная остановка), потом «Возобновить»", async () => {
  const { c } = setup();
  act(() => c.push({ type: "pc_action", active: true }));
  expect(screen.getByLabelText("Сакура управляет компьютером")).toBeTruthy();
  fireEvent.click(screen.getByText("Стоп"));
  await waitFor(() => expect(screen.getByRole("alert").textContent).toContain("остановлено аварийной кнопкой"));
  expect(c.calls.find((x) => x.type === "panic")?.payload).toEqual({ on: true });
  fireEvent.click(screen.getByText("Возобновить"));
  await waitFor(() => expect(screen.queryByRole("alert")).toBeNull());
});

test("опасное действие без подтверждения — окно «Разрешить?», ответ уходит в ядро", async () => {
  const { c } = setup();
  act(() => c.push({ type: "confirm_request", id: "c1", action: "files.delete", label: "Удалить в корзину: C:\\x\\a.txt", ts: 1, expires: 61 }));
  expect(screen.getByRole("dialog", { name: "Разрешить действие?" }).textContent).toContain("C:\\x\\a.txt");
  fireEvent.click(screen.getByText("Да, выполнить"));
  await act(async () => {});
  expect(c.calls.find((x) => x.type === "confirm_answer")?.payload).toEqual({ id: "c1", yes: true });
  expect(screen.queryByRole("dialog", { name: "Разрешить действие?" })).toBeNull();
});

test("центр действий: последние действия без содержимого, обновление, счётчик ожидающих", async () => {
  const { c } = setup();
  act(() => c.push({ type: "confirm_request", id: "c2", action: "process.kill", label: "Завершить процесс 42", ts: 1, expires: 61 }));
  fireEvent.click(screen.getByLabelText("Центр действий"));
  await waitFor(() => expect(screen.getByLabelText("Последние действия").textContent).toContain("window.list"));
  expect(screen.getByText(/Доступно обновление: 2/)).toBeTruthy();
  expect(screen.getAllByText("Завершить процесс 42").length).toBeGreaterThan(0);
});
