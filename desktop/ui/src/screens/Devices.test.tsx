import { act, cleanup, render, screen, within } from "@testing-library/react";
import { afterEach, expect, test } from "vitest";

import type { CoreClient } from "../api/client";
import { DemoClient } from "../api/demo";
import type { Device } from "../api/types";
import { pcChoices, withAllPcs } from "../devices";
import { createAppStore, StoreContext } from "../store";
import { Devices } from "./Devices";

afterEach(cleanup);

const dev = (id: string, o: Partial<Device> = {}): Device =>
  ({ id, name: id, kind: "pc", online: true, last_seen: 1, focus: false, stats: {}, ...o });

test("все три ПК, даже если сервер их ещё не видел; активный отмечен", async () => {
  const c = new DemoClient("normal");
  const store = createAppStore(c as CoreClient);
  act(() => { store.getState().init(); });
  await act(async () => { await store.getState().loadDevices(); });   // фикстура: mostech (в фокусе), phone, pc
  render(<StoreContext.Provider value={store}><Devices /></StoreContext.Provider>);
  const rows = within(screen.getByLabelText("Список устройств")).getAllByRole("listitem");
  expect(rows.map((r) => r.textContent?.split(" (")[0])).toEqual(["Компьютер", "Ноутбук", "Ноутбук", "Телефон"]);
  expect(rows[1]!.textContent).toContain("ещё не подключался");       // laptop — сервер его не знает
  const active = rows.filter((r) => r.getAttribute("aria-current") === "true");
  expect(active).toHaveLength(1);
  expect(active[0]!.textContent).toContain("активный");
  expect(active[0]!.textContent).toContain("это устройство");          // демо: device_id = mostech
});

test("presence переносит отметку «активный» на новый ПК", () => {
  const list = withAllPcs([dev("pc", { focus: true }), dev("mostech")]);
  expect(list.map((d) => d.id)).toEqual(["pc", "laptop", "mostech"]);
  expect(pcChoices([dev("pc", { name: "Игровой" })], "office").map((c) => c.id)).toEqual(["pc", "laptop", "mostech", "office"]);
  expect(pcChoices([dev("pc", { name: "Игровой" })])[0]!.name).toBe("Игровой");
  expect(pcChoices([dev("phone", { kind: "phone" })]).map((c) => c.id)).toEqual(["pc", "laptop", "mostech"]);
});
