// Демо-клиент на фикстурах мок-сервера (desktop/tools/fixtures): для снимков экранов
// и тестов. Режимы: normal — данные; empty — пусто; offline — нет связи с сервером;
// unsupported — сервер без proto 2.
import devicesFx from "../../../tools/fixtures/devices.json";
import historyFx from "../../../tools/fixtures/history.json";
import scenariosFx from "../../../tools/fixtures/scenarios.json";
import statusFx from "../../../tools/fixtures/status.json";
import type { CoreClient, LinkState, Listener } from "./client";
import { CoreError, type CoreEvent, type Device, type Message, type Scenario, type Settings } from "./types";

export type DemoMode = "normal" | "empty" | "offline" | "unsupported";

const SETTINGS: Settings = {
  quick_prompts: ["Что у меня сегодня?", "Погода", "Включи музыку"],
  language: "ru",
  theme: "sakura-night",
  device_id: "mostech",
  mic_enabled: true,
  core_ready: true,
};

const APPS = ["Telegram", "Steam", "Яндекс Музыка", "Visual Studio Code", "Opera GX"];

export class DemoClient implements CoreClient {
  private listeners = new Set<Listener>();
  private linkListeners = new Set<(s: LinkState) => void>();
  private messages: Message[];
  private devices: Device[];
  private scenarios: Scenario[];
  private seq = 0;

  constructor(private mode: DemoMode = "normal") {
    const empty = mode === "empty";
    // Время в фикстурах — фиксированное; сдвигаем к «сегодня», чтобы подписи были живыми.
    const now = Date.now() / 1000;
    const shift = now - 1760090400;
    this.messages = empty ? [] : (historyFx.messages as Message[]).map((m) => ({ ...m, ts: m.ts + shift }));
    this.devices = empty ? [] : (devicesFx.devices as Device[]).map((d) => ({ ...d, last_seen: d.last_seen + shift }));
    this.scenarios = empty ? [] : (scenariosFx.scenarios as Scenario[]);
  }

  start(): void {
    for (const cb of this.linkListeners) cb("open");
    const serverOnline = this.mode !== "offline";
    this.emit({ type: "connection", server: serverOnline ? "online" : "offline",
                proto: this.mode === "unsupported" ? 1 : serverOnline ? 2 : null });
    this.emit({ type: "state", value: "idle", level: 0 });
    this.emit({ type: "settings", settings: SETTINGS });
  }

  stop(): void {}

  onEvent(cb: Listener): () => void {
    this.listeners.add(cb);
    return () => this.listeners.delete(cb);
  }

  onLink(cb: (s: LinkState) => void): () => void {
    this.linkListeners.add(cb);
    return () => this.linkListeners.delete(cb);
  }

  private emit(ev: CoreEvent) {
    for (const cb of this.listeners) cb(ev);
  }

  async call<T>(type: string, payload: Record<string, unknown> = {}): Promise<T> {
    switch (type) {
      case "send_text": {
        const text = String(payload.text ?? "");
        const user: Message = { id: `d${++this.seq}`, ts: Date.now() / 1000, role: "user", text,
                                channel: "text", device: "mostech" };
        setTimeout(() => this.emit({ type: "chat_message", message: user }), 10);
        if (this.mode !== "offline") {
          setTimeout(() => this.emit({ type: "chat_message", message: {
            ...user, id: `d${++this.seq}`, role: "assistant", text: `Демо: «${text}»` } }), 300);
        }
        return undefined as T;
      }
      case "list_apps":
        return { apps: APPS.map((name) => ({ name })) } as T;
      case "quick_action":
        return { text: "готово" } as T;
      case "mic_toggle":
        return { mic: !payload.on } as T;
      case "settings_set":
        return { settings: { ...SETTINGS, [String(payload.key)]: payload.value } } as T;
      case "server":
        return this.server(payload.message as Record<string, unknown> & { type: string });
      default:
        return undefined as T;
    }
  }

  async server<T>(message: Record<string, unknown> & { type: string }): Promise<T> {
    if (this.mode === "offline") throw new CoreError("offline", "нет связи с сервером");
    if (this.mode === "unsupported") throw new CoreError("unsupported", "сервер не поддерживает");
    switch (message.type) {
      case "history_request":
        return { type: "history", messages: this.messages } as T;
      case "devices_request":
        return { type: "devices", devices: this.devices } as T;
      case "status_request":
        return (this.mode === "empty" ? { type: "status", tone: "", mode: "normal", context: "", quote: "" }
                                      : { type: "status", ...statusFx }) as T;
      case "scenarios_list":
        return { type: "scenarios", scenarios: this.scenarios } as T;
      case "scenario_from_text": {
        const text = String(message.text ?? "");
        return { type: "scenario_preview", warnings: [], scenario: {
          id: null, name: text.slice(0, 40), enabled: true,
          conditions: [{ type: "phrase", value: text }], actions: [{ type: "notify", value: text }] } } as T;
      }
      case "scenario_run":
        return { type: "scenario_run_started", run_id: "r1", id: message.id } as T;
      default:
        throw new CoreError("bad_request", `демо: ${message.type}`);
    }
  }
}
