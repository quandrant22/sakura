import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { act } from "react";
import { afterEach, expect, test } from "vitest";

import type { CoreClient } from "../api/client";
import { DemoClient } from "../api/demo";
import { CoreError } from "../api/types";
import { ConfirmDialog } from "../components/ControlSafety";
import { createAppStore, StoreContext } from "../store";
import { Scenarios } from "./Scenarios";

afterEach(cleanup);

class ScenClient extends DemoClient {
  sent: Record<string, unknown>[] = [];
  danger = false;
  list = [{ id: "s1", name: "Утро", enabled: true, conditions: [], actions: [{ type: "notify" }] }];
  override async server<T>(m: Record<string, unknown> & { type: string }): Promise<T> {
    this.sent.push(m);
    if (m.type === "scenarios_list") return { scenarios: this.list } as T;
    if (m.type === "scenario_run") {
      if (this.danger && m.confirm !== true) {
        throw new CoreError("confirm_required", "опасные действия: system.shutdown — запуск с confirm: true");
      }
      return { run_id: "r7" } as T;
    }
    if (m.type === "scenario_delete") { this.list = []; return { scenarios: [] } as T; }
    return super.server<T>(m);
  }
  push(ev: Record<string, unknown>) { this.emit(ev as never); }
}

test("сценарии: запуск, журнал по событиям сервера, удаление с подтверждением", async () => {
  const c = new ScenClient("normal");
  const store = createAppStore(c as CoreClient);
  act(() => { store.getState().init(); });
  await act(async () => { await store.getState().loadScenarios(); });
  render(<StoreContext.Provider value={store}><Scenarios /></StoreContext.Provider>);
  fireEvent.click(screen.getByLabelText("Запустить: Утро"));
  await waitFor(() => expect(screen.getByLabelText("Журнал запусков").textContent).toContain("запущен"));
  act(() => c.push({ type: "scenario_event", run_id: "r7", step: 0, status: "ok", detail: "notify" }));
  act(() => c.push({ type: "scenario_event", run_id: "r7", step: 1, status: "done", detail: "" }));
  expect(screen.getByLabelText("Журнал запусков").textContent).toContain("шаг 1: ok (notify)");
  expect(screen.getByLabelText("Журнал запусков").textContent).toContain("завершён");
  fireEvent.click(screen.getByLabelText("Удалить: Утро"));
  expect(c.sent.some((m) => m.type === "scenario_delete")).toBe(false);
  fireEvent.click(screen.getByText("Да"));
  await waitFor(() => expect(screen.queryByLabelText("Запустить: Утро")).toBeNull());
});

async function dangerous() {
  const c = new ScenClient("normal");
  c.danger = true;
  const store = createAppStore(c as CoreClient);
  act(() => { store.getState().init(); });
  await act(async () => { await store.getState().loadScenarios(); });
  render(<StoreContext.Provider value={store}><Scenarios /><ConfirmDialog /></StoreContext.Provider>);
  fireEvent.click(screen.getByLabelText("Запустить: Утро"));
  const dialog = await screen.findByRole("dialog", { name: "Разрешить действие?" });
  expect(dialog.textContent).toContain("опасные действия: system.shutdown");
  return { c, runs: () => c.sent.filter((m) => m.type === "scenario_run") };
}

test("confirm_required: «Разрешить?» с текстом сервера, «Да» — повтор с confirm: true", async () => {
  const { runs } = await dangerous();
  expect(runs()).toEqual([{ type: "scenario_run", id: "s1" }]);
  fireEvent.click(screen.getByText("Да, выполнить"));
  await waitFor(() => expect(runs()).toHaveLength(2));
  expect(runs()[1]).toEqual({ type: "scenario_run", id: "s1", confirm: true });
  await waitFor(() => expect(screen.getByLabelText("Журнал запусков").textContent).toContain("запущен"));
  expect(screen.queryByRole("dialog", { name: "Разрешить действие?" })).toBeNull();
});

test("confirm_required: «Нет» — ничего не запускается и ошибки нет", async () => {
  const { runs } = await dangerous();
  fireEvent.click(screen.getByText("Нет"));
  await act(async () => {});
  expect(runs()).toHaveLength(1);
  expect(screen.queryByRole("dialog", { name: "Разрешить действие?" })).toBeNull();
  expect(screen.queryByRole("alert")).toBeNull();
  expect(screen.queryByLabelText("Журнал запусков")).toBeNull();
});
