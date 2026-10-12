import { act, cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, expect, test } from "vitest";

import type { CoreClient } from "../../../api/client";
import { DemoClient } from "../../../api/demo";
import { MediaProvider } from "../../../media/MediaContext";
import { YandexBar } from "./YandexBar";

afterEach(cleanup);

/** Клиент с подставным пультом Яндекс.Музыки. */
class RemoteClient extends DemoClient {
  ops: { op: string; value?: unknown }[] = [];
  state: Record<string, unknown> = { status: "ok", title: "Песня", artist: "Певица", playing: true,
    position_s: 10, duration_s: 200, updated_age_s: 0, shuffle: false, repeat: "none", volume: 40,
    can_like: false, like_hint: "нужен YANDEX_MUSIC_TOKEN", cover: null };
  override async call<T>(type: string, payload: Record<string, unknown> = {}): Promise<T> {
    if (type === "media_ymremote") {
      if (payload.op === "state") return this.state as T;
      this.ops.push({ op: String(payload.op), value: payload.value });
      return { ok: true, status: "done", detail: "ok" } as T;
    }
    return super.call<T>(type, payload);
  }
}

function setup(state?: Record<string, unknown>) {
  const c = new RemoteClient("normal");
  if (state) c.state = state;
  render(<MediaProvider client={c as CoreClient}><YandexBar /></MediaProvider>);
  return c;
}

test("трек: название, большая «Пауза», кнопки шлют операции пульта", async () => {
  const c = setup();
  await waitFor(() => expect(screen.getByText("Песня")).toBeTruthy());
  fireEvent.click(screen.getByLabelText("Пауза"));
  fireEvent.click(screen.getByLabelText("Следующий"));
  await act(async () => {});
  expect(c.ops.map((o) => o.op)).toEqual(["play_pause", "next"]);
});

test("«Предыдущий»: на 10 с одинарный клик — в начало, двойной — предыдущий трек", async () => {
  const c = setup();
  await waitFor(() => expect(screen.getByText("Песня")).toBeTruthy());
  fireEvent.click(screen.getByLabelText("Предыдущий"), { detail: 1 });
  fireEvent.click(screen.getByLabelText("Предыдущий"), { detail: 2 });
  await act(async () => {});
  expect(c.ops.map((o) => o.op)).toEqual(["restart", "prev"]);
});

test("лайк без токена неактивен с подсказкой", async () => {
  setup();
  // по умолчанию в jsdom ширина 690 → лайк виден
  await waitFor(() => expect(screen.getByText("Песня")).toBeTruthy());
  const like = screen.getByLabelText("Нравится") as HTMLButtonElement;
  expect(like.disabled).toBe(true);
  expect(like.title).toContain("YANDEX_MUSIC_TOKEN");
});

test("приложение не запущено — кнопка «Открыть Яндекс.Музыку»", async () => {
  const c = setup({ status: "not_running" });
  await waitFor(() => expect(screen.getByText("Яндекс.Музыка не запущена")).toBeTruthy());
  fireEvent.click(screen.getByText(/Открыть Яндекс.Музыку/));
  await act(async () => {});
  expect(c.ops).toEqual([{ op: "open_app", value: undefined }]);
});

test("нет доступа к SMTC — честное состояние без кнопки открытия", async () => {
  setup({ status: "no_smtc" });
  await waitFor(() => expect(screen.getByText(/Нет доступа к панели медиа/)).toBeTruthy());
  expect(screen.queryByText(/Открыть Яндекс.Музыку/)).toBeNull();
});
