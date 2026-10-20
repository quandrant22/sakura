import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { act } from "react";
import { afterEach, expect, test } from "vitest";

import type { CoreClient } from "../api/client";
import { DemoClient } from "../api/demo";
import { createAppStore, StoreContext } from "../store";
import { Scenarios } from "./Scenarios";

afterEach(cleanup);

class ScenClient extends DemoClient {
  sent: Record<string, unknown>[] = [];
  list = [{ id: "s1", name: "Утро", enabled: true, conditions: [], actions: [{ type: "notify" }] }];
  override async server<T>(m: Record<string, unknown> & { type: string }): Promise<T> {
    this.sent.push(m);
    if (m.type === "scenarios_list") return { scenarios: this.list } as T;
    if (m.type === "scenario_run") return { run_id: "r7" } as T;
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
