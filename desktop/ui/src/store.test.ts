import { describe, expect, test, vi } from "vitest";

import type { CoreClient, LinkState, Listener } from "./api/client";
import { DemoClient } from "./api/demo";
import { CoreError, type CoreEvent } from "./api/types";
import { createAppStore } from "./store";

/** Управляемый клиент: сами решаем, что отвечает сервер и какие события приходят. */
class ScriptClient implements CoreClient {
  listeners = new Set<Listener>();
  calls: { type: string; payload?: Record<string, unknown> }[] = [];
  serverReply: (m: { type: string }) => Promise<unknown> = async () => ({});
  onEvent(cb: Listener) {
    this.listeners.add(cb);
    return () => this.listeners.delete(cb);
  }
  onLink(cb: (s: LinkState) => void) {
    cb("open");
    return () => {};
  }
  start() {}
  stop() {}
  emit(ev: CoreEvent) {
    for (const cb of this.listeners) cb(ev);
  }
  async call<T>(type: string, payload?: Record<string, unknown>): Promise<T> {
    this.calls.push({ type, payload });
    return undefined as T;
  }
  server<T>(m: Record<string, unknown> & { type: string }): Promise<T> {
    return this.serverReply(m) as Promise<T>;
  }
}

describe("store", () => {
  test("подключение сервера с proto 2 загружает все экраны (демо)", async () => {
    const store = createAppStore(new DemoClient("normal"));
    store.getState().init();
    await vi.waitFor(() => expect(store.getState().chat.status).toBe("ready"));
    await vi.waitFor(() => expect(store.getState().devices.status).toBe("ready"));
    const s = store.getState();
    expect(s.chat.data.length).toBe(5);
    expect(s.devices.data.map((d) => d.id)).toEqual(["mostech", "phone", "pc"]);
    await vi.waitFor(() => expect(store.getState().status.data?.tone).toBe("calm"));
    expect(s.settings?.quick_prompts).toContain("Погода");
  });

  test("пустые данные", async () => {
    const store = createAppStore(new DemoClient("empty"));
    store.getState().init();
    await vi.waitFor(() => expect(store.getState().devices.status).toBe("ready"));
    expect(store.getState().devices.data).toEqual([]);
    expect(store.getState().chat.data).toEqual([]);
  });

  test("офлайн: сервер offline, загрузка даёт ошибку с понятным текстом", async () => {
    const store = createAppStore(new DemoClient("offline"));
    store.getState().init();
    expect(store.getState().server.online).toBe(false);
    await store.getState().loadDevices();
    expect(store.getState().devices).toMatchObject({ status: "error", error: "Нет связи с сервером" });
  });

  test("сервер без proto 2 — состояние unsupported", async () => {
    const store = createAppStore(new DemoClient("unsupported"));
    store.getState().init();
    expect(store.getState().devices.status).toBe("unsupported");
    await store.getState().loadStatus();
    expect(store.getState().status.status).toBe("unsupported");
  });

  test("отправка: локальный пузырь pending, эхо сервера заменяет его", async () => {
    const c = new ScriptClient();
    const store = createAppStore(c);
    store.getState().init();
    await store.getState().sendText("  Погода ");
    expect(c.calls).toEqual([{ type: "send_text", payload: { text: "Погода" } }]);
    expect(store.getState().chat.data).toMatchObject([{ text: "Погода", pending: true }]);
    c.emit({ type: "chat_message", message: { id: "m9", ts: 1, role: "user", text: "Погода", channel: "text", device: "x" } });
    c.emit({ type: "chat_message", message: { id: "m10", ts: 2, role: "assistant", text: "Солнечно", channel: "text", device: "x" } });
    c.emit({ type: "chat_message", message: { id: "m10", ts: 2, role: "assistant", text: "Солнечно", channel: "text", device: "x" } });
    expect(store.getState().chat.data.map((m) => [m.id, m.pending ?? false])).toEqual([["m9", false], ["m10", false]]);
  });

  test("ошибка отправки убирает пузырь и показывает тост", async () => {
    const c = new ScriptClient();
    c.call = async () => {
      throw new CoreError("core_offline", "x");
    };
    const store = createAppStore(c);
    await store.getState().sendText("привет");
    expect(store.getState().chat.data).toEqual([]);
    expect(store.getState().toast?.text).toBe("Нет связи с ядром Сакуры");
  });

  test("события state/settings/device_update/status/notify", () => {
    const c = new ScriptClient();
    const store = createAppStore(c);
    store.getState().init();
    c.emit({ type: "state", value: "speaking" });
    c.emit({ type: "settings", settings: { quick_prompts: ["A"], language: "ru", theme: "x", mic_enabled: false } });
    c.emit({ type: "device_update", device: { id: "p", name: "Телефон", kind: "phone", online: true, last_seen: 1, focus: false, stats: {} } });
    c.emit({ type: "status", tone: "warm", mode: "focus", context: "Работа", quote: "q" });
    c.emit({ type: "notify", text: "Чайник вскипел", level: "info" });
    const s = store.getState();
    expect(s.coreState).toBe("speaking");
    expect(s.settings?.mic_enabled).toBe(false);
    expect(s.devices.data[0]!.name).toBe("Телефон");
    expect(s.status.data).toEqual({ tone: "warm", mode: "focus", context: "Работа", quote: "q" });
    expect(s.toast?.text).toBe("Чайник вскипел");
  });

  test("предпросмотр сценария из фразы", async () => {
    const store = createAppStore(new DemoClient("normal"));
    await store.getState().previewScenario("Создай сценарий сна");
    expect(store.getState().preview.status).toBe("ready");
    expect(store.getState().preview.data?.scenario.conditions[0]).toEqual({ type: "phrase", value: "Создай сценарий сна" });
  });

  test("быстрые действия и игровой режим вызывают ядро", async () => {
    const c = new ScriptClient();
    const store = createAppStore(c);
    await store.getState().quickAction("open_app", "Telegram");
    await store.getState().setGameMode(true);
    expect(c.calls).toEqual([
      { type: "quick_action", payload: { id: "open_app", arg: "Telegram" } },
      { type: "game_mode", payload: { on: true } },
    ]);
    expect(store.getState().gameMode).toBe(true);
  });
});
