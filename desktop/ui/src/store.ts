// Состояние интерфейса (Zustand). Все данные приходят из ядра через CoreClient.
import { createContext, useContext } from "react";
import { createStore, useStore } from "zustand";

import type { CoreClient, LinkState } from "./api/client";
import {
  type CoreEvent,
  CoreError,
  type CoreState,
  type Device,
  type Message,
  type Scenario,
  type Settings,
  type Status,
} from "./api/types";

export type LoadStatus = "idle" | "loading" | "ready" | "error" | "unsupported";

export interface Slice<T> {
  data: T;
  status: LoadStatus;
  error?: string;
}

export interface AppState {
  link: LinkState;
  server: { online: boolean; proto: number | null };
  coreState: CoreState;
  settings: Settings | null;
  gameMode: boolean;
  chat: Slice<Message[]>;
  devices: Slice<Device[]>;
  status: Slice<Status | null>;
  scenarios: Slice<Scenario[]>;
  preview: Slice<{ scenario: Scenario; warnings: string[] } | null>;
  toast: { text: string; level: "info" | "warn" | "error" } | null;

  init(): () => void;
  loadHistory(): Promise<void>;
  loadDevices(): Promise<void>;
  loadStatus(): Promise<void>;
  loadScenarios(): Promise<void>;
  sendText(text: string): Promise<void>;
  quickAction(id: string, arg?: string): Promise<void>;
  listApps(): Promise<string[]>;
  previewScenario(text: string): Promise<void>;
  toggleMic(): Promise<void>;
  setGameMode(on: boolean): Promise<void>;
  dismissToast(): void;
}

const empty = <T,>(data: T): Slice<T> => ({ data, status: "idle" });

/** Понятный текст ошибки для пользователя. */
export function errorText(e: unknown): string {
  if (e instanceof CoreError) {
    switch (e.code) {
      case "offline":
        return "Нет связи с сервером";
      case "core_offline":
        return "Нет связи с ядром Сакуры";
      case "timeout":
        return "Сервер не ответил вовремя";
      case "unsupported":
        return "Сервер не поддерживает";
      case "starting":
        return "Ядро ещё запускается";
      case "not_master":
        return "Доступно только на основных устройствах";
      default:
        return e.message || "Что-то пошло не так";
    }
  }
  return "Что-то пошло не так";
}

const failStatus = (e: unknown): LoadStatus =>
  e instanceof CoreError && e.code === "unsupported" ? "unsupported" : "error";

export function createAppStore(client: CoreClient) {
  return createStore<AppState>()((set, get) => {
    // Загрузка «слайса» с сервера: loading → ready | error | unsupported.
    async function load<K extends "chat" | "devices" | "status" | "scenarios">(
      key: K,
      request: () => Promise<AppState[K]["data"]>,
    ) {
      set({ [key]: { ...get()[key], status: "loading", error: undefined } } as Partial<AppState>);
      try {
        const data = await request();
        set({ [key]: { data, status: "ready" } } as Partial<AppState>);
      } catch (e) {
        set({ [key]: { ...get()[key], status: failStatus(e), error: errorText(e) } } as Partial<AppState>);
      }
    }

    function onEvent(ev: CoreEvent) {
      const s = get();
      switch (ev.type) {
        case "connection": {
          const e = ev as { server: string; proto: number | null };
          const wasOnline = s.server.online && s.server.proto === 2;
          set({ server: { online: e.server === "online", proto: e.proto } });
          // Сервер (пере)подключился с proto 2 — обновляем данные экранов.
          if (e.server === "online" && e.proto === 2 && !wasOnline) {
            void get().loadHistory();
            void get().loadDevices();
            void get().loadStatus();
            void get().loadScenarios();
          }
          if (e.proto === 1) {
            for (const k of ["chat", "devices", "status", "scenarios"] as const) {
              if (k !== "chat") set({ [k]: { ...get()[k], status: "unsupported", error: "Сервер не поддерживает" } } as Partial<AppState>);
            }
          }
          break;
        }
        case "state":
          set({ coreState: (ev as { value: CoreState }).value });
          break;
        case "settings":
          set({ settings: (ev as { settings: Settings }).settings });
          break;
        case "game_mode":
          set({ gameMode: Boolean((ev as { on: boolean }).on) });
          break;
        case "chat_message": {
          const m = (ev as { message: Message }).message;
          const msgs = s.chat.data;
          if (msgs.some((x) => x.id === m.id)) break;
          // Эхо своего сообщения от сервера заменяет локальный «ожидающий» пузырь.
          const pendingIdx = m.role === "user" ? msgs.findIndex((x) => x.pending && x.text === m.text) : -1;
          const next = pendingIdx >= 0 ? msgs.map((x, i) => (i === pendingIdx ? m : x)) : [...msgs, m];
          set({ chat: { ...s.chat, data: next, status: s.chat.status === "idle" ? "ready" : s.chat.status } });
          break;
        }
        case "devices":
          set({ devices: { data: (ev as { devices: Device[] }).devices, status: "ready" } });
          break;
        case "device_update": {
          const d = (ev as { device: Device }).device;
          const list = s.devices.data.some((x) => x.id === d.id)
            ? s.devices.data.map((x) => (x.id === d.id ? d : x))
            : [...s.devices.data, d];
          set({ devices: { ...s.devices, data: list } });
          break;
        }
        case "status": {
          const { type: _t, ...rest } = ev as { type: string } & Status;
          set({ status: { data: rest as Status, status: "ready" } });
          break;
        }
        case "notify": {
          const n = ev as { text: string; level: "info" | "warn" | "error" };
          set({ toast: { text: n.text, level: n.level } });
          break;
        }
      }
    }

    return {
      link: "connecting",
      server: { online: false, proto: null },
      coreState: "idle",
      settings: null,
      gameMode: false,
      chat: empty<Message[]>([]),
      devices: empty<Device[]>([]),
      status: empty<Status | null>(null),
      scenarios: empty<Scenario[]>([]),
      preview: empty(null),
      toast: null,

      init() {
        const offEv = client.onEvent(onEvent);
        const offLink = client.onLink((link) => set({ link }));
        client.start();
        return () => {
          offEv();
          offLink();
          client.stop();
        };
      },

      loadHistory: () =>
        load("chat", async () => {
          const r = await client.server<{ messages: Message[] }>({ type: "history_request", limit: 50 });
          return r.messages;
        }),
      loadDevices: () =>
        load("devices", async () => (await client.server<{ devices: Device[] }>({ type: "devices_request" })).devices),
      loadStatus: () =>
        load("status", async () => {
          const { type: _t, ...rest } = await client.server<Status & { type: string }>({ type: "status_request" });
          return rest as Status;
        }),
      loadScenarios: () =>
        load("scenarios", async () =>
          (await client.server<{ scenarios: Scenario[] }>({ type: "scenarios_list" })).scenarios),

      async sendText(text) {
        const t = text.trim();
        if (!t) return;
        const local: Message = { id: `local-${Date.now()}`, ts: Date.now() / 1000, role: "user", text: t,
                                 channel: "text", device: get().settings?.device_id ?? "", pending: true };
        set({ chat: { ...get().chat, data: [...get().chat.data, local],
                      status: get().chat.status === "idle" ? "ready" : get().chat.status } });
        try {
          await client.call("send_text", { text: t });
        } catch (e) {
          set({ toast: { text: errorText(e), level: "error" },
                chat: { ...get().chat, data: get().chat.data.filter((m) => m.id !== local.id) } });
        }
      },

      async quickAction(id, arg) {
        try {
          await client.call("quick_action", arg ? { id, arg } : { id });
          set({ toast: { text: "Готово", level: "info" } });
        } catch (e) {
          set({ toast: { text: errorText(e), level: "error" } });
        }
      },

      async listApps() {
        const r = await client.call<{ apps: { name: string }[] }>("list_apps");
        return r.apps.map((a) => a.name);
      },

      async previewScenario(text) {
        const t = text.trim();
        if (!t) return;
        set({ preview: { data: null, status: "loading" } });
        try {
          const r = await client.server<{ scenario: Scenario; warnings: string[] }>({ type: "scenario_from_text", text: t });
          set({ preview: { data: { scenario: r.scenario, warnings: r.warnings ?? [] }, status: "ready" } });
        } catch (e) {
          set({ preview: { data: null, status: failStatus(e), error: errorText(e) } });
        }
      },

      async toggleMic() {
        try {
          const r = await client.call<{ mic: boolean }>("mic_toggle");
          const st = get().settings;
          if (st) set({ settings: { ...st, mic_enabled: r.mic } });
        } catch (e) {
          set({ toast: { text: errorText(e), level: "error" } });
        }
      },

      async setGameMode(on) {
        try {
          await client.call("game_mode", { on });
          set({ gameMode: on });
        } catch (e) {
          set({ toast: { text: errorText(e), level: "error" } });
        }
      },

      dismissToast() {
        set({ toast: null });
      },
    };
  });
}

export type AppStore = ReturnType<typeof createAppStore>;

export const StoreContext = createContext<AppStore | null>(null);

export function useApp<T>(selector: (s: AppState) => T): T {
  const store = useContext(StoreContext);
  if (!store) throw new Error("нет StoreContext");
  return useStore(store, selector);
}
