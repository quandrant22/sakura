import { act, cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, expect, test } from "vitest";

import type { CoreClient } from "../api/client";
import { DemoClient } from "../api/demo";
import { MediaProvider } from "../media/MediaContext";
import { SecretsSection } from "./SecretsSection";

afterEach(cleanup);
const FAKE = "fake-secret-value";

class SecretsClient extends DemoClient {
  sent: Record<string, unknown>[] = [];
  keys: Record<string, boolean> = { WS_TOKEN: true, YANDEX_MUSIC_TOKEN: false };
  override async call<T>(type: string, payload: Record<string, unknown> = {}): Promise<T> {
    if (type === "secrets_status") return { env_file: "C:\\sakura-git\\agent\\.env", exists: true, keys: this.keys } as T;
    if (type === "secrets_set") {
      this.sent.push({ type, ...payload });
      this.keys = { ...this.keys, [String(payload.key)]: true };
      return { keys: this.keys, restart_suggested: true } as T;
    }
    if (type === "core_restart") { this.sent.push({ type }); return { restarting: true } as T; }
    return super.call<T>(type, payload);
  }
}

function setup() {
  const c = new SecretsClient("normal");
  render(<MediaProvider client={c as CoreClient}><SecretsSection /></MediaProvider>);
  return c;
}

test("показывает только «задан / не задан», значение никогда не выводится", async () => {
  setup();
  await waitFor(() => expect(screen.getByLabelText("WS_TOKEN: задан")).toBeTruthy());
  expect(screen.getByLabelText("YANDEX_MUSIC_TOKEN: не задан")).toBeTruthy();
  expect((screen.getByLabelText("Новое значение WS_TOKEN") as HTMLInputElement).type).toBe("password");
});

test("запись: значение уходит в ядро, поле сразу очищается, в разметке его нет; предлагается перезапуск", async () => {
  const c = setup();
  await waitFor(() => expect(screen.getByLabelText("YANDEX_MUSIC_TOKEN: не задан")).toBeTruthy());
  const input = screen.getByLabelText("Новое значение YANDEX_MUSIC_TOKEN") as HTMLInputElement;
  fireEvent.change(input, { target: { value: FAKE } });
  fireEvent.submit(input.closest("form")!);
  expect(input.value).toBe("");
  await waitFor(() => expect(screen.getByLabelText("YANDEX_MUSIC_TOKEN: задан")).toBeTruthy());
  expect(c.sent).toEqual([{ type: "secrets_set", key: "YANDEX_MUSIC_TOKEN", value: FAKE }]);
  expect(document.body.innerHTML).not.toContain(FAKE);
  fireEvent.click(screen.getByText("Перезапустить ядро"));
  await act(async () => {});
  expect(c.sent.at(-1)).toEqual({ type: "core_restart" });
});

test("пустое значение не отправляется", async () => {
  const c = setup();
  await waitFor(() => expect(screen.getByLabelText("WS_TOKEN: задан")).toBeTruthy());
  fireEvent.submit(screen.getByLabelText("Новое значение WS_TOKEN").closest("form")!);
  expect(screen.getByRole("alert").textContent).toBe("Введите значение");
  expect(c.sent).toEqual([]);
});
