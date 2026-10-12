import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, expect, test } from "vitest";

import { DemoClient } from "../../api/demo";
import type { SakuraBridge } from "../../bridge";
import { MediaProvider } from "../../media/MediaContext";
import { AppWindowWidget } from "./AppWindowWidget";

afterEach(() => { cleanup(); delete (window as { sakura?: unknown }).sakura; });

function withWindows(list: { id: string; name: string }[], blocklist: string[] = []) {
  const selected: string[] = [];
  (window as { sakura?: Partial<SakuraBridge> }).sakura = {
    capture: {
      sources: async () => list, blocklist: async () => blocklist,
      select: async (id: string) => { selected.push(id); return true; },
      openMini: async () => {}, closeMini: async () => {}, miniSelect: async () => {}, onMiniClosed: () => () => {},
    },
  } as Partial<SakuraBridge>;
  render(<MediaProvider client={new DemoClient("normal")}><AppWindowWidget /></MediaProvider>);
  return selected;
}

test("показ начинается только по явному действию; чёрный список и окна Сакуры не предлагаются", async () => {
  withWindows([{ id: "window:1:0", name: "Блокнот" }, { id: "window:2:0", name: "KeePassXC" },
               { id: "window:3:0", name: "Sakura" }]);
  expect(screen.queryByLabelText("Показ окна")).toBeNull();
  fireEvent.click(screen.getByText("Выбрать окно"));
  await waitFor(() => expect(screen.getByRole("list", { name: "Окна" })).toBeTruthy());
  const names = screen.getAllByRole("button").map((b) => b.textContent);
  expect(names).toContain("Блокнот");
  expect(names).not.toContain("KeePassXC");
  expect(names).not.toContain("Sakura");
});

test("WINDOW_BLOCKLIST владельца заменяет список по умолчанию", async () => {
  withWindows([{ id: "window:1:0", name: "Блокнот" }, { id: "window:4:0", name: "Steam" }], ["steam"]);
  fireEvent.click(screen.getByText("Выбрать окно"));
  await waitFor(() => expect(screen.getByText("Блокнот")).toBeTruthy());
  expect(screen.queryByText("Steam")).toBeNull();
});

test("нет окон — честная надпись", async () => {
  withWindows([]);
  fireEvent.click(screen.getByText("Выбрать окно"));
  await waitFor(() => expect(screen.getByText("Нет окон для показа")).toBeTruthy());
});
