import { act, cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, expect, test, vi } from "vitest";

import type { CoreClient } from "../api/client";
import { DemoClient } from "../api/demo";
import type { Message } from "../api/types";
import type { SakuraBridge } from "../bridge";
import { createAppStore, HISTORY_PAGE, StoreContext } from "../store";
import { Chat } from "./Chat";

afterEach(() => { cleanup(); delete window.sakura; });

const msg = (i: number): Message => ({ id: `m${i}`, ts: 1760000000 + i * 60, role: i % 2 ? "assistant" : "user",
  text: i === 3 ? "про погоду в Москве" : `сообщение ${i}`, channel: "text", device: "pc", source: "ui", turn_id: null } as Message);

class HistoryClient extends DemoClient {
  all = Array.from({ length: HISTORY_PAGE + 10 }, (_, i) => msg(i));
  sent: Record<string, unknown>[] = [];
  override async server<T>(m: Record<string, unknown> & { type: string }): Promise<T> {
    this.sent.push(m);
    if (m.type === "history_request") {
      const before = m.before_ts as number | undefined;
      const items = this.all.filter((x) => before === undefined || x.ts < before);
      return { messages: items.slice(-HISTORY_PAGE) } as T;
    }
    if (m.type === "chat_search") return { messages: this.all.filter((x) => x.text.includes(String(m.q))) } as T;
    if (m.type === "chat_delete") { this.all = this.all.filter((x) => x.id !== m.id); return { id: m.id } as T; }
    return super.server<T>(m);
  }
}

async function setup() {
  const c = new HistoryClient("normal");
  const store = createAppStore(c as CoreClient);
  render(<StoreContext.Provider value={store}><Chat onCollapse={() => {}} /></StoreContext.Provider>);
  await act(async () => { await store.getState().loadHistory(); });
  return { c, store };
}

test("подгрузка вверх: «Загрузить раньше» добавляет старые сообщения", async () => {
  const { c, store } = await setup();
  expect(store.getState().chat.data).toHaveLength(HISTORY_PAGE);
  fireEvent.click(screen.getByText("Загрузить раньше"));
  await waitFor(() => expect(store.getState().chat.data).toHaveLength(HISTORY_PAGE + 10));
  expect(c.sent.at(-1)).toMatchObject({ type: "history_request", before_ts: 1760000000 + 10 * 60 });
  expect(screen.queryByText("Загрузить раньше")).toBeNull(); // больше нечего
});

test("поиск по переписке и удаление только после подтверждения", async () => {
  const { c } = await setup();
  fireEvent.click(screen.getByLabelText("Поиск по переписке"));
  fireEvent.change(screen.getByLabelText("Искать в переписке"), { target: { value: "погод" } });
  fireEvent.click(screen.getByText("Найти"));
  await waitFor(() => expect(screen.getByLabelText("Результаты поиска").textContent).toContain("про погоду в Москве"));
  fireEvent.click(screen.getAllByLabelText("Удалить сообщение")[0]!);
  expect(c.sent.some((m) => m.type === "chat_delete")).toBe(false);
  fireEvent.click(screen.getByText("Да"));
  await waitFor(() => expect(c.sent.some((m) => m.type === "chat_delete" && m.id === "m3")).toBe(true));
  await waitFor(() => expect(screen.queryByText("про погоду в Москве")).toBeNull());
});

test("экспорт переписки в файл через диалог сохранения", async () => {
  const exportChat = vi.fn(async () => true);
  window.sakura = { exportChat } as unknown as SakuraBridge;
  await setup();
  fireEvent.click(screen.getByLabelText("Экспорт переписки"));
  await waitFor(() => expect(exportChat).toHaveBeenCalled());
  const text = (exportChat.mock.calls[0] as unknown as [string])[0];
  expect(text.split("\n")).toHaveLength(HISTORY_PAGE);
  expect(screen.getByRole("status").textContent).toContain("сохранена");
});
