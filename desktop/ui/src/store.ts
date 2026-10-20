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
import { pcName } from "./devices";

export const HISTORY_PAGE = 50;

export type LoadStatus = "idle" | "loading" | "ready" | "error" | "unsupported";

export interface Slice<T> {
  data: T;
  status: LoadStatus;
  error?: string;
}

export interface ScenarioEvent { run_id: string; step: number; status: string; detail: string }

export interface ConfirmRequest { id: string; action: string; label: string; ts: number; expires: number }

export interface AppState {
  link: LinkState;
  server: { online: boolean; proto: number | null };
  coreState: CoreState;
  settings: Settings | null;
  gameMode: boolean;
  chat: Slice<Message[]>;
  /** Сервер v1: истории чата нет, видны только сообщения этого сеанса. */
  historyUnsupported: boolean;
  devices: Slice<Device[]>;
  status: Slice<Status | null>;
  scenarios: Slice<Scenario[]>;
  preview: Slice<{ scenario: Scenario; warnings: string[] } | null>;
  toast: { text: string; level: "info" | "warn" | "error" } | null;
  /** Запланировано выключение/перезагрузка: до какого момента (мс) — для тоста с отсчётом и «Отмена». */
  power: { action: "shutdown" | "restart"; until: number } | null;
  /** Сакура выполняет действие с компьютером — индикатор в трее и окне. */
  pcAction: boolean;
  /** Аварийная остановка: управление ПК приостановлено. */
  controlPaused: boolean;
  /** Опасные действия, ждущие «Разрешить?» в окне. */
  confirms: ConfirmRequest[];
  panic(on?: boolean): Promise<void>;
  answerConfirm(id: string, yes: boolean): Promise<void>;
  /** «Отмена» в тосте выключения. */
  cancelPower(): Promise<void>;
  /** Последние уведомления (виджет «Уведомления»); в файл не пишутся. */
  notifications: { ts: number; text: string; level: "info" | "warn" | "error" }[];

  init(): () => void;
  loadHistory(): Promise<void>;
  /** История: есть ли сообщения раньше загруженных (подгрузка вверх). */
  chatMore: boolean;
  loadOlder(): Promise<void>;
  searchHistory(q: string): Promise<Message[]>;
  /** Удалить сообщение из истории на сервере (после подтверждения в окне). */
  deleteMessage(id: string): Promise<void>;
  loadDevices(): Promise<void>;
  loadStatus(): Promise<void>;
  loadScenarios(): Promise<void>;
  /** Журнал запусков сценариев (события scenario_event сервера). */
  scenarioLog: (ScenarioEvent & { ts: number })[];
  runScenario(id: string): Promise<void>;
  deleteScenario(id: string): Promise<void>;
  sendText(text: string): Promise<void>;
  quickAction(id: string, arg?: string): Promise<void>;
  listApps(): Promise<string[]>;
  previewScenario(text: string): Promise<void>;
  toggleMic(): Promise<void>;
  /** «Говорить сейчас» без слова «Сакура» (короткий клик по ядру). */
  listenNow(): Promise<void>;
  /** Уровень микрофона/озвучки 0..1 — для ядра-графики; читается каждый кадр, без перерисовки React. */
  getLevel(): number;
  /** Уровень системного звука (музыки) 0..1 — для эквалайзера. */
  getMusicLevel(): number;
  setGameMode(on: boolean): Promise<void>;
  dismissToast(): void;
}

const empty = <T,>(data: T): Slice<T> => ({ data, status: "idle" });

/** Повтор той же реплики Сакуры (turn_id, kind, text) — не дублируем. */
export function isSameReply(a: Message, b: Message): boolean {
  return a.role !== "user" && a.role === b.role && !!a.turn_id && a.turn_id === b.turn_id &&
    (a.kind ?? "") === (b.kind ?? "") && a.text === b.text;
}

/** Ответ встаёт после последнего сообщения своего хода (поздний ответ на старый ход
 *  не уходит в конец под новый ход); без хода или у пользователя — в конец. */
export function insertInTurn(msgs: Message[], m: Message): Message[] {
  if (m.role === "user" || !m.turn_id) return [...msgs, m];
  let at = -1;
  msgs.forEach((x, i) => { if (x.turn_id === m.turn_id) at = i; });
  if (at < 0 || at === msgs.length - 1) return [...msgs, m];
  return [...msgs.slice(0, at + 1), m, ...msgs.slice(at + 1)];
}

/** Понятный текст ошибки для пользователя. */
/** Вид ошибки ответа сервера: экраны различают «ещё не поддерживает», «нужен защищённый канал», «не отвечает». */
export type ErrorKind = "unsupported" | "secure" | "timeout" | "offline" | "error";

export const SECURE_HINT = "Нужен защищённый канал: включи VPN или подключи устройство (Настройки → Безопасность)";

export function errorKind(e: unknown): ErrorKind {
  if (!(e instanceof CoreError)) return "error";
  if (["unsupported", "unknown_type", "unknown_command", "not_supported"].includes(e.code)) return "unsupported";
  if (e.code === "secure_channel_required") return "secure";
  if (e.code === "timeout") return "timeout";
  if (e.code === "offline" || e.code === "core_offline") return "offline";
  return "error";
}

export function errorText(e: unknown): string {
  if (e instanceof CoreError) {
    switch (errorKind(e)) {
      case "unsupported":
        return "Сервер ещё не поддерживает";
      case "secure":
        return SECURE_HINT;
      case "timeout":
        return "Сервер не отвечает";
      default:
        break;
    }
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
      case "mic_off":
        return "Микрофон выключен";
      default:
        return e.message || "Что-то пошло не так";
    }
  }
  return "Что-то пошло не так";
}

export const isConfirmRequired = (e: unknown): e is CoreError => e instanceof CoreError && e.code === "confirm_required";

/** Встроенный сценарий «Фокус» на сервере (core/service.py FOCUS_SCENARIO_ID). */
const FOCUS_SCENARIO_ID = "focus";

const failStatus = (e: unknown): LoadStatus =>
  e instanceof CoreError && e.code === "unsupported" ? "unsupported" : "error";

export function createAppStore(client: CoreClient) {
  return createStore<AppState>()((set, get) => {
    // Уровни звука меняются десятки раз в секунду — держим их вне состояния Zustand.
    const level = { value: 0 };
    const musicLevel = { value: 0 };

    // «Разрешить?» самого окна (сервер ответил confirm_required): ответ не уходит в ядро.
    const localConfirms = new Map<string, (yes: boolean) => void>();
    let localSeq = 0;
    function askLocal(label: string, timeoutS = 60): Promise<boolean> {
      const id = `ui${++localSeq}`;
      const ts = Date.now() / 1000;
      return new Promise((resolve) => {
        const timer = setTimeout(() => void get().answerConfirm(id, false), timeoutS * 1000);
        localConfirms.set(id, (yes) => { clearTimeout(timer); resolve(yes); });
        set({ confirms: [...get().confirms, { id, action: "scenario_run", label, ts, expires: ts + timeoutS }] });
      });
    }
    /** scenario_run; confirm_required → «Разрешить?» с текстом сервера, «Да» — повтор с confirm: true, «Нет» — null. */
    async function runWithConfirm(id: string) {
      try {
        return await client.server<{ run_id: string }>({ type: "scenario_run", id });
      } catch (e) {
        if (!isConfirmRequired(e)) throw e;
        if (!(await askLocal(e.message))) return null;
        return await client.server<{ run_id: string }>({ type: "scenario_run", id, confirm: true });
      }
    }

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
          // Сервер недоступен: вместо вечных скелетонов — ошибка с кнопкой «Повторить».
          if (e.server !== "online") {
            for (const k of ["chat", "devices", "status", "scenarios"] as const) {
              const sl = get()[k];
              if (sl.status === "idle" || sl.status === "loading") {
                set({ [k]: { ...sl, status: "error", error: "Нет связи с сервером" } } as Partial<AppState>);
              }
            }
          }
          if (e.proto === 1) {
            for (const k of ["devices", "status", "scenarios"] as const) {
              set({ [k]: { ...get()[k], status: "unsupported", error: "Сервер не поддерживает" } } as Partial<AppState>);
            }
            // v1: истории нет, но живой чат работает — ядро собирает сообщения из расшифровки и ответов.
            if (e.server === "online") set({ chat: { ...get().chat, status: "ready", error: undefined }, historyUnsupported: true });
          } else if (e.proto === 2) {
            set({ historyUnsupported: false });
          }
          break;
        }
        case "state": {
          const e = ev as { value: CoreState; level?: number };
          if (typeof e.level === "number") level.value = e.level;
          else if (e.value === "idle") level.value = 0;
          set({ coreState: e.value });
          break;
        }
        case "level": {
          const v = Number((ev as { value?: unknown }).value);
          if (Number.isFinite(v)) level.value = Math.min(1, Math.max(0, v));
          break;
        }
        case "presence": {
          const p = ev as { event?: string; to?: string | null };
          if (!p.to) break;
          const name = pcName(p.to, s.devices.data);
          set({ notifications: [{ ts: Date.now() / 1000, text: `Сакура перешла на ${name}`, level: "info" as const },
                                ...s.notifications].slice(0, 50),
                devices: { ...s.devices, data: s.devices.data.map((d) => ({ ...d, focus: d.id === p.to })) } });
          break;
        }
        case "audio_level": {
          const bars = (ev as { bars: number[] }).bars;
          if (Array.isArray(bars) && bars.length) musicLevel.value = bars.reduce((a, b) => a + b, 0) / bars.length;
          break;
        }
        case "settings":
          set({ settings: (ev as { settings: Settings }).settings });
          break;
        case "game_mode":
          set({ gameMode: Boolean((ev as { on: boolean }).on) });
          break;
        case "chat_message": {
          const m = (ev as { message: Message }).message;
          const msgs = s.chat.data;
          if (msgs.some((x) => x.id === m.id || isSameReply(x, m))) break;
          // Эхо своего сообщения от сервера заменяет локальный «ожидающий» пузырь.
          const pendingIdx = m.role === "user" ? msgs.findIndex((x) => x.pending && x.text === m.text) : -1;
          const next = pendingIdx >= 0 ? msgs.map((x, i) => (i === pendingIdx ? m : x)) : insertInTurn(msgs, m);
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
        case "power_pending": {
          const p = ev as unknown as { action: string; seconds: number };
          set({ power: { action: p.action === "restart" ? "restart" : "shutdown", until: Date.now() + (Number(p.seconds) || 0) * 1000 } });
          break;
        }
        case "power_cancelled":
          set({ power: null });
          break;
        case "scenario_event": {
          const e = ev as unknown as ScenarioEvent;
          set({ scenarioLog: [...get().scenarioLog.slice(-99), { ...e, ts: Date.now() / 1000 }] });
          break;
        }
        case "control_paused":
          set({ controlPaused: Boolean((ev as { on?: boolean }).on) });
          break;
        case "confirm_request": {
          const r = ev as unknown as ConfirmRequest;
          set({ confirms: [...get().confirms.filter((c) => c.id !== r.id), r] });
          break;
        }
        case "confirm_done":
          set({ confirms: get().confirms.filter((c) => c.id !== (ev as { id?: string }).id) });
          break;
        case "pc_action":
          set({ pcAction: Boolean((ev as { active?: boolean }).active) });
          break;
        case "notify": {
          const n = ev as { text: string; level: "info" | "warn" | "error" };
          // Лента уведомлений (виджет) — только в памяти, последние 50.
          set({ toast: { text: n.text, level: n.level },
                notifications: [{ ts: Date.now() / 1000, text: n.text, level: n.level }, ...get().notifications].slice(0, 50) });
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
      historyUnsupported: false,
      devices: empty<Device[]>([]),
      status: empty<Status | null>(null),
      scenarios: empty<Scenario[]>([]),
      preview: empty(null),
      toast: null,
      notifications: [],
      power: null,
      pcAction: false,
      controlPaused: false,
      confirms: [],
      async panic(on = true) {
        try {
          await client.call("panic", { on });
          set({ controlPaused: on });
        } catch {
          // ядро недоступно — кнопка останется видимой
        }
      },
      async answerConfirm(id, yes) {
        set({ confirms: get().confirms.filter((c) => c.id !== id) });
        const local = localConfirms.get(id);
        if (local) { localConfirms.delete(id); local(yes); return; }
        try { await client.call("confirm_answer", { id, yes }); } catch { /* запрос уже закрыт */ }
      },

      async cancelPower() {
        try {
          await client.call("power_cancel");
          set({ power: null });
        } catch (e) {
          set({ toast: { text: errorText(e), level: "error" } });
        }
      },

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
          const r = await client.server<{ messages: Message[] }>({ type: "history_request", limit: HISTORY_PAGE });
          set({ chatMore: r.messages.length >= HISTORY_PAGE });
          return r.messages;
        }),
      chatMore: false,
      scenarioLog: [],
      async runScenario(id) {
        const r = await runWithConfirm(id);
        if (!r) return;
        set({ scenarioLog: [...get().scenarioLog, { run_id: r.run_id, step: -1, status: "started", detail: id, ts: Date.now() / 1000 }] });
      },
      async deleteScenario(id) {
        const r = await client.server<{ scenarios: Scenario[] }>({ type: "scenario_delete", id });
        set({ scenarios: { ...get().scenarios, data: r.scenarios ?? get().scenarios.data.filter((s) => s.id !== id) } });
      },
      async loadOlder() {
        const first = get().chat.data[0];
        if (!first) return;
        const r = await client.server<{ messages: Message[] }>({ type: "history_request", limit: HISTORY_PAGE,
                                                                 before_ts: first.ts });
        const have = new Set(get().chat.data.map((m) => m.id));
        set({ chat: { ...get().chat, data: [...r.messages.filter((m) => !have.has(m.id)), ...get().chat.data] },
              chatMore: r.messages.length >= HISTORY_PAGE });
      },
      async searchHistory(q) {
        return (await client.server<{ messages: Message[] }>({ type: "chat_search", q, limit: 50 })).messages;
      },
      async deleteMessage(id) {
        await client.server({ type: "chat_delete", id });
        set({ chat: { ...get().chat, data: get().chat.data.filter((m) => m.id !== id) } });
      },
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
                                 channel: "text", device: get().settings?.device_id ?? "", pending: true, source: "ui" };
        set({ chat: { ...get().chat, data: [...get().chat.data, local],
                      status: get().chat.status === "idle" ? "ready" : get().chat.status } });
        try {
          await client.call("send_text", { text: t, source: "ui" });
        } catch (e) {
          set({ toast: { text: errorText(e), level: "error" },
                chat: { ...get().chat, data: get().chat.data.filter((m) => m.id !== local.id) } });
        }
      },

      async quickAction(id, arg) {
        try {
          try {
            await client.call("quick_action", arg ? { id, arg } : { id });
          } catch (e) {
            // «Фокус» и сценарии с опасными шагами: сервер просит подтверждение — спрашиваем и повторяем.
            const scenario = id === "focus_mode" ? FOCUS_SCENARIO_ID : id === "run_scenario" ? arg : undefined;
            if (!scenario || !isConfirmRequired(e)) throw e;
            if (!(await askLocal(e.message))) return;
            await client.server({ type: "scenario_run", id: scenario, confirm: true });
          }
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

      async listenNow() {
        try {
          await client.call("listen_now");
        } catch (e) {
          set({ toast: { text: errorText(e), level: "error" } });
        }
      },

      getLevel: () => level.value,
      getMusicLevel: () => musicLevel.value,

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
