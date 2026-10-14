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
  emitEvent(ev: Record<string, unknown>) { this.emit(ev as never); }
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

const HINT = "Нужен доступ к Яндекс.Музыке. Добавь YANDEX_MUSIC_TOKEN в C:\\sakura-git\\agent\\.env и перезапусти Сакуру";

test("лайк без токена: приглушён, по клику — полная подсказка и «Как это сделать», в ядро не уходит", async () => {
  const c = setup({ ...new RemoteClient("normal").state, like_hint: HINT });
  // по умолчанию в jsdom ширина 690 → лайк виден
  await waitFor(() => expect(screen.getByText("Песня")).toBeTruthy());
  const like = screen.getByLabelText("Нравится") as HTMLButtonElement;
  expect(like.className).toContain("opacity-35");
  expect(like.title).toContain("YANDEX_MUSIC_TOKEN");
  fireEvent.click(like);
  const hint = await screen.findByRole("status");
  expect(hint.textContent).toContain(HINT);           // полностью, без обрезки
  expect(hint.className).toContain("text-warn");      // цвет предупреждения, не акцента
  fireEvent.click(screen.getByText("Как это сделать"));
  expect(screen.getByRole("dialog", { name: "Как подключить Яндекс.Музыку" }).textContent).toContain("перезапустите Сакуру");
  expect(c.ops).toEqual([]);
});

test("ошибка действия — подсказка цветом предупреждения; звук не найден — один повтор через 2 с", async () => {
  const c = setup();
  await waitFor(() => expect(screen.getByText("Песня")).toBeTruthy());
  let calls = 0;
  const orig = c.call.bind(c);
  c.call = async <T,>(type: string, payload: Record<string, unknown> = {}): Promise<T> => {
    if (type === "media_ymremote" && payload.op === "mute") {
      calls += 1;
      return { ok: false, status: "noop", detail: "Звук Яндекс.Музыки не найден: включите трек — повторю через 2 с",
               retry_ms: 20 } as T;
    }
    return orig<T>(type, payload);
  };
  fireEvent.click(screen.getByLabelText("Выключить звук"));
  const hint = await screen.findByRole("status");
  expect(hint.className).toContain("text-warn");
  expect(hint.textContent).toContain("повторю через 2 с");
  await waitFor(() => expect(calls).toBe(2));
  await new Promise((r) => setTimeout(r, 60));
  expect(calls).toBe(2); // повтор только один
});

test("с токеном: сердце закрашено, если лайк стоит; клик шлёт like", async () => {
  const c = setup({ ...new RemoteClient("normal").state, can_like: true, can_lyrics: true, like_hint: null, liked: true });
  await waitFor(() => expect(screen.getByLabelText("Убрать лайк")).toBeTruthy());
  expect(screen.getByLabelText("Убрать лайк").getAttribute("aria-pressed")).toBe("true");
  fireEvent.click(screen.getByLabelText("Убрать лайк"));
  await act(async () => {});
  expect(c.ops.map((o) => o.op)).toContain("like");
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

test("событие music_state применяется сразу (без опроса) и подтверждается окном", async () => {
  const c = setup();
  await waitFor(() => expect(screen.getByText("Песня")).toBeTruthy());
  const acks: unknown[] = [];
  const orig = c.call.bind(c);
  c.call = async <T,>(type: string, payload: Record<string, unknown> = {}): Promise<T> => {
    if (type === "music_ui_ack") { acks.push(payload.seq); return { ms: 5 } as T; }
    return orig<T>(type, payload);
  };
  act(() => c.emitEvent({ type: "music_state", state: { status: "ok", seq: 42, title: "Новый трек", artist: "Кто-то",
                                                         playing: true, position_s: 0, duration_s: 100 } }));
  expect(screen.getByText("Новый трек")).toBeTruthy();
  await waitFor(() => expect(acks).toEqual([42]));
});

test("процесс есть, сессии нет — «Запускается…», а не «Открыть Яндекс.Музыку»", async () => {
  setup({ status: "starting" });
  await waitFor(() => expect(screen.getByText("Запускается…")).toBeTruthy());
  expect(screen.queryByText(/Открыть Яндекс.Музыку/)).toBeNull();
});
