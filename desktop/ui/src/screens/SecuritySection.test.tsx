import { act, cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, expect, test } from "vitest";

import type { CoreClient } from "../api/client";
import { DemoClient } from "../api/demo";
import { CoreError } from "../api/types";
import { MediaProvider } from "../media/MediaContext";
import { channelText, type SecureStatus, SecuritySection } from "./SecuritySection";

afterEach(cleanup);

const base: SecureStatus = {
  keys: { device_key: true, device_fp: "aaaa bbbb cccc dddd", storage: "dpapi", paired: false, server_fp: null, device_id: null },
  channel: { transport: "ws", secure: false, reason: "устройство не подключено", proto: 2 }, mode: "noise", pinned: false,
};

class C extends DemoClient {
  calls: { type: string; payload: Record<string, unknown> }[] = [];
  st = base;
  fail = false;
  override async call<T>(type: string, payload: Record<string, unknown> = {}): Promise<T> {
    this.calls.push({ type, payload });
    if (type === "secure_status") return this.st as T;
    if (type === "secure_pair") {
      if (this.fail) throw new CoreError("failed", "код спаривания не подошёл или истёк — получите новый в Telegram (/pair)");
      this.st = { ...this.st, keys: { ...this.st.keys, paired: true, server_fp: "1111 2222 3333 4444" } };
      return { server_fp: "1111 2222 3333 4444", device_fp: "aaaa bbbb cccc dddd" } as T;
    }
    if (type === "secure_reset") return { keys: {} } as T;
    if (type === "secure_devices") throw new CoreError("unsupported", "сервер ещё не поддерживает список устройств");
    return super.call<T>(type, payload);
  }
}

function setup(c = new C("normal")) {
  render(<MediaProvider client={c as CoreClient}><SecuritySection /></MediaProvider>);
  return c;
}

test("состояния канала понятным языком", () => {
  expect(channelText({ ...base, channel: { transport: "noise", secure: true } }).text).toBe("Зашифровано");
  const off = channelText(base);
  expect(off.text).toBe("Не защищено");
  expect(off.hint).toContain("устройство не подключено");
  expect(channelText({ ...base, mode: "ws" }).hint).toContain("VPN");
  expect(channelText({ ...base, channel: { transport: null, secure: false } }).text).toBe("Нет связи");
});

test("подключение по 8 словам: отпечаток сервера для сверки, кнопка недоступна без 8 слов", async () => {
  const c = setup();
  await waitFor(() => expect(screen.getByLabelText("Состояние канала").textContent).toContain("Не защищено"));
  expect(screen.getByText("aaaa bbbb cccc dddd")).toBeTruthy();
  const btn = screen.getByText("Подключить").closest("button") as HTMLButtonElement;
  fireEvent.change(screen.getByLabelText("8 слов"), { target: { value: "лес кот" } });
  expect(btn.disabled).toBe(true);
  fireEvent.change(screen.getByLabelText("8 слов"), { target: { value: "лес кот мост елка река гора снег луна" } });
  fireEvent.click(btn);
  await waitFor(() => expect(screen.getByRole("status").textContent).toContain("1111 2222 3333 4444"));
  expect(c.calls.find((x) => x.type === "secure_pair")?.payload).toEqual({ words: "лес кот мост елка река гора снег луна" });
});

test("неверный код — понятная ошибка; список устройств — «сервер ещё не поддерживает»; сброс с подтверждением", async () => {
  const c = new C("normal");
  c.fail = true;
  setup(c);
  await waitFor(() => expect(screen.getByLabelText("Состояние канала")).toBeTruthy());
  fireEvent.change(screen.getByLabelText("8 слов"), { target: { value: "один два три четыре пять шесть семь восемь" } });
  fireEvent.click(screen.getByText("Подключить"));
  await waitFor(() => expect(screen.getByRole("status").textContent).toContain("не подошёл"));
  fireEvent.click(screen.getByText("Показать"));
  await waitFor(() => expect(screen.getByText(/не поддерживает/)).toBeTruthy());
  fireEvent.click(screen.getByText("Сбросить"));
  expect(c.calls.some((x) => x.type === "secure_reset")).toBe(false);
  fireEvent.click(screen.getByText("Да"));
  await act(async () => {});
  expect(c.calls.some((x) => x.type === "secure_reset")).toBe(true);
});
