import { act, cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, expect, test } from "vitest";

import type { CoreClient } from "../api/client";
import { DemoClient } from "../api/demo";
import { MediaProvider } from "../media/MediaContext";
import { AppsSection, appStatusText } from "./AppsSection";

afterEach(cleanup);
const base = { running: true, with_flag: false, store: false, exe_found: true, a11y: false, enabled: true,
               args: ["--force-renderer-accessibility"] };

class AppsClient extends DemoClient {
  calls: string[] = [];
  st = { ...base };
  override async call<T>(type: string, payload: Record<string, unknown> = {}): Promise<T> {
    if (type === "apps_state") return { yandex_music: this.st } as T;
    if (type === "app_restart") { this.calls.push(type); this.st = { ...this.st, with_flag: true, a11y: true };
      return { ok: true, detail: "перезапустила Яндекс.Музыка с поддержкой кнопок окна" } as T; }
    return super.call<T>(type, payload);
  }
}

test("тексты состояния", () => {
  expect(appStatusText({ ...base })).toBe("Запущено без ключа — кнопки окна недоступны");
  expect(appStatusText({ ...base, with_flag: true, a11y: true })).toBe("Кнопки окна доступны");
  expect(appStatusText({ ...base, store: true })).toContain("Microsoft Store");
  expect(appStatusText({ ...base, running: false })).toBe("Не запущено");
});

test("запущено без ключа — кнопка перезапуска, после неё «Кнопки окна доступны»", async () => {
  const c = new AppsClient("normal");
  render(<MediaProvider client={c as CoreClient}><AppsSection /></MediaProvider>);
  await waitFor(() => expect(screen.getByLabelText("Состояние Яндекс.Музыки").textContent).toContain("без ключа"));
  fireEvent.click(screen.getByText("Перезапустить с поддержкой кнопок"));
  await act(async () => {});
  expect(c.calls).toEqual(["app_restart"]);
  await waitFor(() => expect(screen.getByLabelText("Состояние Яндекс.Музыки").textContent).toBe("Кнопки окна доступны"));
});
