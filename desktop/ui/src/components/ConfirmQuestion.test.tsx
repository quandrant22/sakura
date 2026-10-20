import { act, cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, expect, test } from "vitest";

import type { CoreClient } from "../api/client";
import { DemoClient } from "../api/demo";
import type { Message } from "../api/types";
import { createAppStore, StoreContext } from "../store";
import { Chat, openQuestionId } from "./Chat";

afterEach(cleanup);

class C extends DemoClient {
  calls: { type: string; payload: Record<string, unknown> }[] = [];
  override async call<T>(type: string, payload: Record<string, unknown> = {}): Promise<T> {
    this.calls.push({ type, payload });
    if (type === "send_text") return undefined as T;
    return super.call<T>(type, payload);
  }
  push(ev: Record<string, unknown>) { this.emit(ev as never); }
}

const Q = "Выключить игровой компьютер? Да или нет?";
const msg = (id: string, o: Partial<Message>): Message =>
  ({ id, ts: 1000, role: "assistant", text: "x", channel: "voice", device: "pc", ...o });

test("вопрос kind=confirm — в чате с кнопками «Да»/«Нет»; нажатие шлёт обычный текст «да»", async () => {
  const c = new C("empty");
  const store = createAppStore(c as CoreClient);
  act(() => { store.getState().init(); });
  await act(async () => { await store.getState().loadHistory(); });   // пустая история загружена
  render(<StoreContext.Provider value={store}><Chat onCollapse={() => {}} /></StoreContext.Provider>);
  act(() => c.push({ type: "chat_message", message: msg("q1", { kind: "confirm", text: Q, ts: Date.now() / 1000 }) }));
  // Сервер прислал тот же вопрос своим chat_message — второго пузыря нет.
  act(() => c.push({ type: "chat_message", message: msg("srv-7", { kind: "llm", text: Q, ts: Date.now() / 1000 }) }));
  expect(screen.getAllByText(Q)).toHaveLength(1);
  const group = screen.getByRole("group", { name: "Ответ на вопрос" });
  fireEvent.click(within(group, "Да"));
  await waitFor(() => expect(c.calls).toContainEqual({ type: "send_text", payload: { text: "да", source: "ui" } }));
  // После ответа (реплика пользователя) кнопки пропадают.
  expect(screen.queryByRole("group", { name: "Ответ на вопрос" })).toBeNull();
});

function within(el: HTMLElement, text: string): HTMLElement {
  return Array.from(el.querySelectorAll("button")).find((b) => b.textContent === text)!;
}

test("кнопки — только у последнего неотвеченного вопроса", () => {
  expect(openQuestionId([msg("a", { kind: "confirm" }), msg("u", { role: "user" })])).toBeNull();
  expect(openQuestionId([msg("a", { kind: "confirm" }), msg("b", { kind: "llm" })])).toBe("a");
  expect(openQuestionId([msg("a", { kind: "confirm" }), msg("b", { kind: "confirm" })])).toBe("b");
  expect(openQuestionId([msg("a", { kind: "llm" })])).toBeNull();
});
