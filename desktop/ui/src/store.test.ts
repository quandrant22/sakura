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
  test("п. 1: ходы — повтор (turn_id, kind, text) игнорируется, поздний ответ встаёт к своему ходу", () => {
    const c = new ScriptClient();
    const store = createAppStore(c);
    store.getState().init();
    const m = (id: string, role: "user" | "assistant" | "system", text: string, turn_id: string, kind?: string) =>
      c.emit({ type: "chat_message", message: { id, ts: 1, role, text, channel: "text", device: "pc", turn_id, kind } as never });
    m("u1", "user", "первый", "t1");
    m("u2", "user", "второй", "t2");
    m("a2", "assistant", "ответ на второй", "t2", "llm");
    m("a1", "assistant", "ответ на первый", "t1", "llm");      // пришёл позже — встаёт после «первый»
    m("a1-dup", "assistant", "ответ на первый", "t1", "llm");  // повтор с другим id — игнорируется
    m("c1", "system", "громкость 50%", "t2", "command");
    expect(store.getState().chat.data.map((x) => x.text)).toEqual(
      ["первый", "ответ на первый", "второй", "ответ на второй", "громкость 50%"]);
  });

  test("сервер v1: чат живой без истории, остальное — «сервер не поддерживает»", () => {
    const c = new ScriptClient();
    const store = createAppStore(c);
    store.getState().init();
    c.emit({ type: "connection", server: "online", proto: 1 });
    const s = store.getState();
    expect(s.chat.status).toBe("ready");
    expect(s.historyUnsupported).toBe(true);
    for (const k of ["devices", "status", "scenarios"] as const) expect(s[k].status).toBe("unsupported");
    c.emit({ type: "chat_message", message: { id: "local-1", ts: 1, role: "user", text: "Сакура, как дела?", channel: "voice", device: "pc" } });
    expect(store.getState().chat.data.map((m) => m.text)).toEqual(["Сакура, как дела?"]);
    // разрыв и возврат — снова v1, чат остаётся живым
    c.emit({ type: "connection", server: "offline", proto: null });
    c.emit({ type: "connection", server: "online", proto: 1 });
    expect(store.getState().chat.status).toBe("ready");
    expect(store.getState().server.online).toBe(true);
  });

  test("уровни звука: state.level — для ядра, audio_level — отдельно, без перерисовки", () => {
    const c = new ScriptClient();
    const store = createAppStore(c);
    store.getState().init();
    const renders = vi.fn();
    store.subscribe(renders);
    c.emit({ type: "state", value: "speaking", level: 0.7 });
    expect(store.getState().getLevel()).toBe(0.7);
    c.emit({ type: "audio_level", bars: [1, 0, 0.5] });
    expect(store.getState().getMusicLevel()).toBeCloseTo(0.5);
    expect(store.getState().getLevel()).toBe(0.7);
    expect(renders).toHaveBeenCalledTimes(1); // только смена coreState
    c.emit({ type: "state", value: "idle" });
    expect(store.getState().getLevel()).toBe(0);
  });

  test("listenNow вызывает listen_now; ошибка — понятный тост", async () => {
    const c = new ScriptClient();
    const store = createAppStore(c);
    await store.getState().listenNow();
    expect(c.calls.at(-1)?.type).toBe("listen_now");
    c.call = async () => { throw new CoreError("mic_off", "x"); };
    await store.getState().listenNow();
    expect(store.getState().toast?.text).toBe("Микрофон выключен");
  });

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
    expect(c.calls).toEqual([{ type: "send_text", payload: { text: "Погода", source: "ui" } }]);
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
