import { cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { act } from "react";
import { afterEach, expect, test } from "vitest";

import type { CoreClient } from "../api/client";
import { DemoClient } from "../api/demo";
import { CoreError } from "../api/types";
import { createAppStore, StoreContext } from "../store";
import { Scenarios } from "./Scenarios";

afterEach(cleanup);

class ScenClient extends DemoClient {
  sent: Record<string, unknown>[] = [];
  list: Record<string, unknown>[] = [
    { id: "s1", name: "Утро", enabled: true, conditions: [{ type: "time", value: "07:30", days: [0, 1, 2, 3, 4] }],
      actions: [{ type: "notify", value: "Доброе утро" }], last_run: Date.now() / 1000 - 120, last_status: "ok", run_count: 3 },
    { id: "s2", name: "Отбой", enabled: true, conditions: [],
      actions: [{ type: "action", value: "power.sleep" }] },
  ];
  override async server<T>(m: Record<string, unknown> & { type: string }): Promise<T> {
    this.sent.push(m);
    if (m.type === "scenarios_list") return { scenarios: this.list } as T;
    if (m.type === "scenario_run") {
      if (m.id === "s2" && !m.confirm) throw new CoreError("confirm_required", "опасные действия: power.sleep");
      return { run_id: "r7" } as T;
    }
    if (m.type === "scenario_delete") { this.list = this.list.filter((x) => x.id !== m.id); return { scenarios: this.list } as T; }
    if (m.type === "scenario_toggle") {
      this.list = this.list.map((x) => (x.id === m.id ? { ...x, enabled: m.enabled } : x));
      return { scenario: this.list.find((x) => x.id === m.id) } as T;
    }
    if (m.type === "scenario_save") {
      const sc = { ...(m.scenario as Record<string, unknown>), id: (m.scenario as { id?: string }).id ?? "s9" };
      return { scenario: sc, warnings: ["Условий нет — запуск кнопкой ▶"] } as T;
    }
    return super.server<T>(m);
  }
  push(ev: Record<string, unknown>) { this.emit(ev as never); }
}

async function setup() {
  const c = new ScenClient("normal");
  const store = createAppStore(c as CoreClient);
  act(() => { store.getState().init(); });
  await act(async () => { await store.getState().loadScenarios(); });
  render(<StoreContext.Provider value={store}><Scenarios /></StoreContext.Provider>);
  await waitFor(() => expect(store.getState().catalog.status).toBe("ready"));
  return { c, store };
}

test("список: условия словами, итог последнего запуска, журнал с автозапуском, удаление", async () => {
  const { c } = await setup();
  expect(screen.getByText("07:30, по будням")).toBeTruthy();
  expect(screen.getByText(/выполнен 2 мин назад · 3 раз/)).toBeTruthy();
  expect(screen.getByText("Сон компьютера")).toBeTruthy();   // id команды → название из каталога
  fireEvent.click(screen.getByLabelText("Запустить: Утро"));
  await waitFor(() => expect(screen.getByLabelText("Журнал запусков").textContent).toContain("Утро (вручную) — запущен"));
  act(() => c.push({ type: "scenario_event", run_id: "r7", step: 0, status: "ok", detail: "уведомление" }));
  act(() => c.push({ type: "scenario_event", run_id: "r7", step: 1, status: "done", detail: "" }));
  const journal = screen.getByLabelText("Журнал запусков").textContent ?? "";
  expect(journal).toContain("шаг 1: готово — уведомление");
  expect(journal).toContain("завершён");
  act(() => c.push({ type: "scenario_run_started", run_id: "r8", id: "s1", name: "Утро", trigger: "по времени" }));
  expect(screen.getByLabelText("Журнал запусков").textContent).toContain("Утро (по времени) — запущен");
  fireEvent.click(screen.getByLabelText("Удалить: Утро"));
  expect(c.sent.some((m) => m.type === "scenario_delete")).toBe(false);
  fireEvent.click(screen.getByText("Да"));
  await waitFor(() => expect(screen.queryByLabelText("Запустить: Утро")).toBeNull());
});

test("опасный сценарий — запуск только после подтверждения; переключатель", async () => {
  const { c } = await setup();
  fireEvent.click(screen.getByLabelText("Запустить: Отбой"));
  await waitFor(() => expect(screen.getByText(/Есть опасные действия/)).toBeTruthy());
  fireEvent.click(screen.getByText("Запустить"));
  await waitFor(() => expect(c.sent.some((m) => m.type === "scenario_run" && m.confirm === true)).toBe(true));
  fireEvent.click(screen.getByLabelText("Включён: Утро"));
  await waitFor(() => expect(screen.getByLabelText("Включён: Утро").getAttribute("aria-checked")).toBe("false"));
  expect(c.sent).toContainEqual(expect.objectContaining({ type: "scenario_toggle", id: "s1", enabled: false }));
});

test("конструктор: условия и команда с параметром → scenario_save; проверка до отправки", async () => {
  const { c } = await setup();
  fireEvent.click(screen.getByText("Собрать с нуля"));
  fireEvent.click(screen.getByText("Сохранить"));
  const problems = screen.getByLabelText("Что поправить").textContent ?? "";
  expect(problems).toContain("Впиши название");
  expect(problems).toContain("Действие 1: выбери команду");
  expect(c.sent.some((m) => m.type === "scenario_save")).toBe(false);

  fireEvent.change(screen.getByLabelText("Название сценария"), { target: { value: "Вечер" } });
  fireEvent.click(screen.getByText("Добавить условие"));
  fireEvent.change(screen.getByLabelText("Тип условия"), { target: { value: "time" } });
  fireEvent.change(screen.getByLabelText("Время"), { target: { value: "21:15" } });
  fireEvent.click(screen.getByText("выходные"));
  fireEvent.click(screen.getByLabelText("Команда"));
  fireEvent.change(screen.getByLabelText("Поиск команды"), { target: { value: "трек" } });
  fireEvent.click(within(screen.getByRole("listbox")).getByText("Включить трек"));
  fireEvent.click(screen.getByText("Сохранить"));
  expect(screen.getByLabelText("Что поправить").textContent).toContain("какой трек включить");
  fireEvent.change(screen.getByLabelText("Параметр"), { target: { value: "Кино" } });
  fireEvent.click(screen.getByText("Добавить действие"));
  fireEvent.change(screen.getAllByLabelText("Тип действия")[1] as HTMLElement, { target: { value: "telegram" } });
  fireEvent.change(screen.getByLabelText("Текст"), { target: { value: "Включила Кино" } });
  fireEvent.click(screen.getAllByLabelText("Выше")[1] as HTMLElement);
  fireEvent.click(screen.getByText("Сохранить"));
  await waitFor(() => expect(c.sent.some((m) => m.type === "scenario_save")).toBe(true));
  const saved = c.sent.find((m) => m.type === "scenario_save")?.scenario;
  expect(saved).toEqual({
    id: null, name: "Вечер", enabled: true,
    conditions: [{ type: "time", value: "21:15", days: [5, 6] }],
    actions: [{ type: "telegram", value: "Включила Кино" }, { type: "action", value: "music.play_track", arg: "Кино" }],
  });
  await waitFor(() => expect(screen.getByText(/Сохранено: «Вечер»/)).toBeTruthy());
});

test("шаблон и правка открывают редактор; фраза → черновик", async () => {
  const { c } = await setup();
  fireEvent.click(screen.getByText("Игровой вечер"));
  expect((screen.getByLabelText("Название сценария") as HTMLInputElement).value).toBe("Игровой вечер");
  expect((screen.getByLabelText("Приложение") as HTMLInputElement).value).toBe("Steam");
  expect((screen.getByLabelText("Параметр") as HTMLInputElement).value).toBe("Discord");
  fireEvent.click(screen.getByText("Отмена"));
  fireEvent.click(screen.getByLabelText("Изменить: Утро"));
  expect(screen.getByText("Изменение сценария")).toBeTruthy();
  expect(screen.getByLabelText("День: Сб").getAttribute("aria-pressed")).toBe("false");
  fireEvent.click(screen.getByText("Отмена"));
  fireEvent.change(screen.getByLabelText("Сценарий словами"), { target: { value: "вечером включи волну" } });
  fireEvent.click(screen.getByText("Собрать"));
  await waitFor(() => expect((screen.getByLabelText("Название сценария") as HTMLInputElement).value).toBe("вечером включи волну"));
  expect(c.sent.some((m) => m.type === "scenario_from_text")).toBe(true);
});
